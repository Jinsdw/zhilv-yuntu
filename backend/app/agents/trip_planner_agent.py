"""
智旅云图 - 行程规划 Agent（LangGraph 实现）

将 TripRequest 转为可校验的 TripResponse 草案。
控制流由 LangGraph StateGraph 接管（见 planner_graph.py / nodes.py）。
检索走 rag_tool；真实坐标/路线/天气留给后续编排。

模块组织：
- 常量 / 异常 / Draft Schema（与第五阶段保持一致）
- Prompt 与 JSON 抽取工具函数
- TripPlannerAgent：薄壳入口，编译并调用 LangGraph
  - plan(): 主图
  - edit_day(): 单日编辑子图
- 业务方法（被 nodes.py 通过 TripPlannerAgent.__new__ 复用）：
  - _repair_json_with_llm / draft_to_trip_response / _draft_day_to_model
  - validate_and_repair / _sort_and_fix_times
  - enrich_budget_and_summary / _fallback_plan
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Optional, Union

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import settings
from app.models.schemas import (
    BudgetInfo,
    BudgetLevel,
    Coordinate,
    HotelInfo,
    ItineraryDay,
    ItineraryItem,
    PlaceInfo,
    RestaurantInfo,
    TravelStyle,
    TripRequest,
    TripResponse,
    TripTipCategory,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_MAX_TOOL_ROUNDS = 4
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 4096
PLACEHOLDER_ADDRESS = "待地图服务补全"
PLACEHOLDER_COORD = Coordinate(latitude=0.0, longitude=0.0)

# 当日/总体综合评分：默认基准分（0-5）。当某天/整份行程没有任何真实
# 评分数据（占位模式或候选池无 rating）时使用，避免概览显示误导性的 0 分。
DEFAULT_RATING = 4.5

# 每天最少景点数：不足时由校验环节从候选池自动补选
MIN_PLACES_PER_DAY = 2

BUDGET_DAILY_BASE: dict[str, float] = {
    BudgetLevel.ECONOMY.value: 350.0,
    BudgetLevel.STANDARD.value: 600.0,
    BudgetLevel.LUXURY.value: 1200.0,
}

ACCOMMODATION_SHARE = 0.35
FOOD_SHARE = 0.30
TICKET_SHARE = 0.20
TRANSPORT_SHARE = 0.10
OTHER_SHARE = 0.05

DEFAULT_TIME_SLOTS = [
    ("09:00", "11:00"),
    ("11:30", "13:00"),
    ("14:00", "16:30"),
    ("17:00", "19:00"),
]

TIP_CATEGORIES: dict[str, str] = {
    "出行准备": "🎒",
    "交通出行": "🚗",
    "省钱攻略": "💰",
    "美食推荐": "🍜",
    "住宿建议": "🏨",
    "安全须知": "🛡️",
    "文化礼仪": "🏛️",
    "天气穿搭": "🌤️",
    "实用工具": "📱",
    "应急联系": "🚨",
}

CITY_SPECIFIC_TIPS: dict[str, dict[str, list[str]]] = {
    "北京": {
        "出行准备": ["故宫、国家博物馆等热门景点须提前7天在官方平台实名预约", "天安门广场安检较严，建议轻装出行，勿带大包"],
        "交通出行": ["推荐办理北京一卡通，地铁公交通用且有折扣", "早晚高峰地铁限流，建议错峰出行或骑行共享单车"],
        "文化礼仪": ["参观天安门、人民大会堂等场所请着装得体", "老城区胡同游览请尊重居民隐私，勿擅入民宅"],
    },
    "西安": {
        "出行准备": ["兵马俑建议提前在线购票，旺季现场排队可能超2小时", "陕西历史博物馆免费票需提前在公众号预约"],
        "交通出行": ["地铁2号线直达钟楼、小寨等核心区域，覆盖主要景点", "城墙骑行建议选晴天，单人车100元/3小时"],
        "文化礼仪": ["回民街区域请尊重清真饮食禁忌，勿携外食入内", "碑林等文化遗址请勿触摸展品"],
    },
    "成都": {
        "出行准备": ["大熊猫基地建议早7:30前到达，下午熊猫多在休息", "宽窄巷子、锦江等夜间灯光适合晚饭后散步"],
        "交通出行": ["成都地铁覆盖宽窄巷子、武侯祠、春熙路等核心景点", "打车起价低，短途出行性价比高"],
        "美食推荐": ["火锅推荐微辣/鸳鸯锅，不嗜辣者勿贸然点特辣", "建设路小吃街是本地人常去的美食集中地"],
    },
    "厦门": {
        "出行准备": ['鼓浪屿船票须提前在「厦门轮渡」公众号预约，旺季易售罄', "防晒是刚需，海边紫外线强"],
        "交通出行": ["岛内推荐骑行+公交，环岛路有专用自行车道", "鼓浪屿岛内禁止机动车，全程步行请穿舒适鞋"],
        "住宿建议": ["曾厝垵、中山路周边民宿多，但旺季噪音大，建议选离主街远的"],
    },
    "大理": {
        "出行准备": ["洱海环湖约130公里，建议分2天骑行或自驾", "高原紫外线强，防晒霜SPF50+必备"],
        "交通出行": ["环洱海推荐租电动车或包车，公共交通班次少", "大理古城内步行即可，周边景点建议拼车"],
        "文化礼仪": ["白族村寨参观请尊重当地风俗，三月街等节庆可体验", "洱海周边禁止游泳和垂钓，请遵守生态保护规定"],
    },
    "三亚": {
        "出行准备": ["蜈支洲岛、南山寺等热门景点建议提前1天预约", "潜水需选择有资质的正规商家，警惕低价陷阱"],
        "交通出行": ["推荐租车自驾，景点分散且公交不便", "机场到亚龙湾约40分钟，到海棠湾约50分钟"],
        "安全须知": ["海边游泳请在划定区域，远离野海滩", "注意水母蜇伤，下水前观察水面情况"],
    },
}

SEASON_TIPS: dict[str, list[str]] = {
    "spring": ["春季温差大，建议洋葱式穿搭，随身带薄外套", "花粉过敏者请备抗过敏药物，赏花注意风向"],
    "summer": ["夏季高温暴晒，防晒霜+遮阳帽+墨镜三件套必备", "午后易有雷阵雨，随身携带折叠雨伞", "注意防暑降温，及时补水，避免正午长时间户外活动"],
    "autumn": ["秋季天高气爽但早晚温差大，建议带一件抓绒或薄羽绒", "干燥季节注意皮肤保湿和补水"],
    "winter": ["冬季北方景点寒冷，羽绒服+保暖内衣+手套帽子必备", "路面可能结冰，穿防滑鞋，注意行走安全"],
}

TRAVEL_STYLE_TIPS: dict[str, list[str]] = {
    "relaxed": ["行程节奏较慢，建议灵活安排，不必赶场打卡", "预留充足休息时间，享受旅程本身"],
    "compact": ["行程紧凑，建议提前查好路线，利用碎片时间", "热门景点建议预约早场，避开高峰时段"],
    "adventure": ["户外活动较多，注意装备齐全和体力分配", "建议购买旅行意外险，告知紧急联系人行程"],
    "cultural": ["博物馆和历史遗迹建议提前了解背景知识，体验更深", "可预约专业讲解或租用语音导览，提升参观质量"],
    "foodie": ["以美食为线索规划路线，注意餐厅营业时间和排队情况", "建议午餐错峰(11:00前或13:00后)避开排队高峰"],
}

BUDGET_TIPS: dict[str, list[str]] = {
    "economy": ["善用景点免费日/免费时段，很多博物馆周一闭馆其他日免费", "住宿选地铁站附近的经济型连锁，交通便捷且性价比高", "午餐选本地人常去的小馆子，比景区周边便宜不少"],
    "standard": ["景点门票提前在官方平台购买，常有早鸟优惠", "住宿选市中心三星/精品酒店，步行可达主要景点"],
    "luxury": ["可考虑请当地私导定制行程，深度体验文化精髓", "高端酒店通常含早餐和下午茶，性价比比单独用餐高"],
}

SPECIAL_NEEDS_TIPS: dict[str, list[str]] = {
    "with_kids": ["随身携带儿童常用药、创可贴、退烧贴", "每1-2小时安排一次休息，让孩子补充水分和零食", "餐厅优先选择有儿童座椅和儿童餐的店家"],
    "with_elderly": ["随身携带日常用药和病历卡，以防不时之需", "每日景点不超过3个，安排充足休息时间", "选择有电梯和无障碍通道的景点，避免长时间爬坡"],
    "has_disability": ["出行前致电景点确认无障碍通道、电梯、无障碍卫生间位置", "提前预约无障碍停车位或告知车站需要协助", "随身携带残障证件，多数景点可享免票或优惠"],
}

_UNSET = object()


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class PlannerError(Exception):
    """行程规划通用错误"""


class PlannerParseError(PlannerError):
    """LLM 输出无法解析为结构化行程"""


class PlannerValidationError(PlannerError):
    """行程不满足硬约束且无法自动修复"""


# ---------------------------------------------------------------------------
# 草案 Schema（比 TripResponse 松）
# ---------------------------------------------------------------------------

class DraftItem(BaseModel):
    start_time: str = Field(default="09:00", description="开始时间 HH:MM")
    end_time: str = Field(default="11:00", description="结束时间 HH:MM")
    name: str = Field(..., min_length=1)
    category: str = Field(default="景点")
    activity: str = Field(default="游览")
    activity_detail: Optional[str] = None
    duration_minutes: int = Field(default=120, ge=0)
    tips: list[str] = Field(default_factory=list)
    ticket_price: Optional[float] = Field(default=None, ge=0)
    place_id: Optional[str] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def normalize_time(cls, v: str) -> str:
        v = (v or "").strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", v)
        if not m:
            return "09:00"
        h, mi = int(m.group(1)), int(m.group(2))
        h = max(0, min(23, h))
        mi = max(0, min(59, mi))
        return f"{h:02d}:{mi:02d}"


class DraftMeal(BaseModel):
    name: str = Field(..., min_length=1)
    place_id: Optional[str] = None
    cuisine_type: str = Field(default="本地菜")
    avg_price: float = Field(default=50.0, ge=0)
    address: str = Field(default=PLACEHOLDER_ADDRESS)


class DraftHotel(BaseModel):
    name: str = Field(..., min_length=1)
    place_id: Optional[str] = None
    hotel_type: str = Field(default="舒适型")
    price: float = Field(default=300.0, ge=0)
    address: str = Field(default=PLACEHOLDER_ADDRESS)


class DraftDay(BaseModel):
    day_number: int = Field(..., ge=1)
    itinerary_date: Optional[date] = None
    day_theme: Optional[str] = None
    items: list[DraftItem] = Field(default_factory=list)
    daily_tips: list[str] = Field(default_factory=list)
    breakfast: Optional[DraftMeal] = None
    lunch: Optional[DraftMeal] = None
    dinner: Optional[DraftMeal] = None
    hotel: Optional[DraftHotel] = None


class DraftItinerary(BaseModel):
    trip_name: Optional[str] = None
    days: list[DraftDay] = Field(default_factory=list)
    trip_highlights: list[str] = Field(default_factory=list)
    trip_tips: list[str] = Field(default_factory=list)
    special_needs_notes: list[str] = Field(default_factory=list)
    recommended_foods: list[str] = Field(default_factory=list)
    recommended_shopping: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是「智旅云图」行程规划助手。根据用户约束与候选POI数据，生成可执行的多日行程。

硬性规则：
1. 当用户消息附带【候选POI】时，景点、餐厅、酒店必须从候选列表中选择，并输出对应的 place_id。不得使用候选列表外的地点。
2. 若用户消息已附带【攻略上下文】，优先使用，可少调或不调工具。
3. 最终回复必须是单个 JSON 对象（不要 Markdown 说明），字段如下：
{
  "trip_name": "字符串",
  "days": [
    {
      "day_number": 1,
      "day_theme": "可选主题",
      "items": [
        {
          "start_time": "09:00",
          "end_time": "11:00",
          "name": "地点名",
          "place_id": "候选列表中的place_id",
          "category": "景点",
          "activity": "简短活动",
          "activity_detail": "可选详情",
          "duration_minutes": 120,
          "tips": ["提示"],
          "ticket_price": 0
        }
      ],
      "daily_tips": [],
      "lunch": {"name": "店名", "place_id": "候选列表中的place_id", "cuisine_type": "菜系", "avg_price": 80},
      "dinner": {"name": "店名", "place_id": "候选列表中的place_id", "cuisine_type": "菜系", "avg_price": 100},
      "hotel": {"name": "酒店名", "place_id": "候选列表中的place_id", "hotel_type": "舒适型", "price": 350}
    },
    {
      "day_number": 2,
      "day_theme": "同区域/相邻区域景点",
      "items": [
        {
          "start_time": "09:00",
          "end_time": "11:00",
          "name": "景点 A",
          "place_id": "候选列表中的place_id",
          "category": "景点",
          "activity": "简短活动",
          "activity_detail": "可选详情",
          "duration_minutes": 120,
          "tips": ["提示"],
          "ticket_price": 0
        },
        {
          "start_time": "14:00",
          "end_time": "16:30",
          "name": "景点 B",
          "place_id": "候选列表中的place_id",
          "category": "景点",
          "activity": "简短活动",
          "activity_detail": "可选详情",
          "duration_minutes": 150,
          "tips": ["提示"],
          "ticket_price": 0
        }
      ],
      "daily_tips": [],
      "lunch": {"name": "店名", "place_id": "候选列表中的place_id", "cuisine_type": "菜系", "avg_price": 80},
      "dinner": {"name": "店名", "place_id": "候选列表中的place_id", "cuisine_type": "菜系", "avg_price": 100},
      "hotel": {"name": "酒店名", "place_id": "候选列表中的place_id", "hotel_type": "舒适型", "price": 350}
    }
  ],
  "trip_highlights": [],
  "trip_tips": [],
  "special_needs_notes": [],
  "recommended_foods": [],
  "recommended_shopping": []
}
4. days 数量必须等于用户行程天数；每日景点数量不少于 2 个且不超过 max_places_per_day，尽量排满上午、下午时段。
5. 每日必须包含 lunch、dinner 和 hotel（不需要 breakfast）。
6. 同一天的景点必须属于同一区域分组（district/cluster），不可跨区域安排。
7. 餐厅优先选择当天景点所在区域的候选。
8. 遵守偏好关键词与排除关键词。同行状态（特殊需求）是硬性约束，必须逐条满足，并将落实方式写入 special_needs_notes：
   - 携带儿童：安排亲子友好、安全可控、路程适中的景点，避免高强度徒步；餐厅/住宿考虑儿童便利。
   - 携带老人：安排轻松、少步行、有休息点的景点，控制每日体力消耗，避免长时间爬山。
   - 行动不便：优先选择无障碍通道/电梯/坡道可达、台阶少、地面平缓的景点，避免爬山与长距离步行；每日 tips 需写明无障碍提示。
   若没有任何同行状态，special_needs_notes 输出空数组 []。
9. 时间按当日从早到晚排列，避免严重重叠。建议时段：上午09:00-11:00，午餐11:30-13:00，下午14:00-16:30，晚餐17:00-19:00。
10. trip_tips 至少输出 8 条，覆盖以下维度（每条以"【分类】内容"格式书写，便于后续分组）：
   - 【出行准备】行前准备、证件、预约、打包建议
   - 【交通出行】当地交通方式、交通卡、停车、拼车注意
   - 【省钱攻略】门票优惠、免费时段、性价比餐饮、免票景点
   - 【美食推荐】必吃特色、避坑指南、卫生注意
   - 【住宿建议】选区域、入住退房、安全须知
   - 【安全须知】财物保管、人身安全、自然灾害防范
   - 【文化礼仪】当地风俗、宗教禁忌、拍照礼仪
   - 【天气穿搭】季节穿衣、防晒防寒、雨具建议
   - 【实用工具】推荐APP、导航、翻译、支付方式
   - 【应急联系】报警/急救电话、最近医院、领事馆
   daily_tips 每日输出 2-3 条，针对当日具体行程给出实用提示（如该日景点预约提醒、穿搭建议、交通方案）。
"""


def _style_cn(style: Any) -> str:
    value = getattr(style, "value", style)
    return {
        "relaxed": "休闲度假",
        "compact": "紧凑高效",
        "adventure": "探险挑战",
        "cultural": "文化体验",
        "foodie": "美食之旅",
    }.get(str(value), str(value or ""))


def _budget_cn(level: Any) -> str:
    value = getattr(level, "value", level)
    return {
        "economy": "经济实惠",
        "standard": "标准适中",
        "luxury": "豪华享受",
    }.get(str(value), str(value or ""))


def build_user_prompt(
    request: TripRequest,
    *,
    context: Optional[str] = None,
    candidate_places: Optional[list[Any]] = None,
    candidate_sections: Optional[dict[str, Any]] = None,
    extra_instruction: Optional[str] = None,
) -> str:
    """将 TripRequest 渲染为 user 消息。

    当 candidate_sections 传入时（B类动态城市），按景点/餐饮/住宿三段分类输出，
    并标注区域分组，强制 LLM 从候选池中选点并输出 place_id。
    """
    days = (request.end_date - request.start_date).days + 1
    lines = [
        f"目的地：{request.destination}",
        f"日期：{request.start_date.isoformat()} 至 {request.end_date.isoformat()}（共 {days} 天）",
        f"人数：{request.travelers}",
        f"预算等级：{_budget_cn(request.budget_level)}",
        f"旅行风格：{_style_cn(request.travel_style)}",
        f"每日最多景点数：{request.max_places_per_day}",
        f"每餐餐饮预算约：{request.restaurant_budget_per_meal} 元",
    ]
    if request.daily_budget is not None:
        lines.append(f"每日预算上限：{request.daily_budget} 元")
    flags = []
    if request.with_kids:
        flags.append("携带儿童")
    if request.with_elderly:
        flags.append("携带老人")
    if request.has_disability:
        flags.append("行动不便")
    if flags:
        lines.append("特殊需求（硬性约束，必须满足并在 special_needs_notes 说明落实方式）：" + "、".join(flags))
    lines.append(
        f"室内景点：{'包含' if request.include_indoor else '尽量不含'}；"
        f"室外景点：{'包含' if request.include_outdoor else '尽量不含'}"
    )
    if request.preferred_keywords:
        lines.append("偏好关键词：" + "、".join(request.preferred_keywords))
    if request.excluded_keywords:
        lines.append("排除关键词：" + "、".join(request.excluded_keywords))

    # ---- 分类候选池输出（B类动态城市新路径） ----
    if candidate_sections and candidate_sections.get("scenic"):
        lines.append("")
        lines.append("【候选POI】")
        lines.append("以下为高德真实POI数据，你必须从中选择地点并输出对应 place_id，禁止使用列表外地点。")
        lines.append("")

        # 景点（按区域分组）
        clusters = candidate_sections.get("clusters") or {}
        scenic_list = candidate_sections.get("scenic") or []
        lines.append("## 景点候选（按区域分组）")
        if clusters:
            # 按 cluster 分组输出
            scenic_by_id = {p.get("place_id"): p for p in scenic_list if isinstance(p, dict)}
            for cluster_name, place_ids in clusters.items():
                lines.append(f"### {cluster_name}")
                for pid in place_ids:
                    p = scenic_by_id.get(pid)
                    if not p:
                        continue
                    coord = p.get("coordinate") or {}
                    lines.append(
                        f"- [place_id={p.get('place_id')}] {p.get('name')} "
                        f"| 评分{p.get('rating') or '无'} "
                        f"| {('门票' + str(p.get('cost')) + '元') if p.get('cost') else '门票未知'} "
                        f"| 坐标({coord.get('latitude', '?')},{coord.get('longitude', '?')}) "
                        f"| {p.get('address') or ''}"
                    )
        else:
            for p in scenic_list[:30]:
                if not isinstance(p, dict):
                    continue
                coord = p.get("coordinate") or {}
                lines.append(
                    f"- [place_id={p.get('place_id')}] {p.get('name')} "
                    f"| 评分{p.get('rating') or '无'} "
                    f"| {p.get('district') or '区域未知'} "
                    f"| 坐标({coord.get('latitude', '?')},{coord.get('longitude', '?')})"
                )
        lines.append("")

        # 餐饮
        food_list = candidate_sections.get("food") or []
        if food_list:
            lines.append("## 餐饮候选")
            for p in food_list[:20]:
                if not isinstance(p, dict):
                    continue
                lines.append(
                    f"- [place_id={p.get('place_id')}] {p.get('name')} "
                    f"| {('人均' + str(p.get('cost')) + '元') if p.get('cost') else '人均未知'} "
                    f"| {p.get('district') or '区域未知'} "
                    f"| 评分{p.get('rating') or '无'}"
                )
            lines.append("")

        # 住宿
        hotel_list = candidate_sections.get("hotel") or []
        if hotel_list:
            lines.append("## 住宿候选")
            for p in hotel_list[:10]:
                if not isinstance(p, dict):
                    continue
                lines.append(
                    f"- [place_id={p.get('place_id')}] {p.get('name')} "
                    f"| {(str(p.get('cost')) + '元/晚') if p.get('cost') else '价格未知'} "
                    f"| {p.get('district') or '区域未知'} "
                    f"| 评分{p.get('rating') or '无'}"
                )
            lines.append("")

        lines.append("## 规则")
        lines.append("1. 每日格式：上午景点 → 午餐 → 下午景点 → 晚餐 → 酒店（不需要早餐）")
        lines.append("2. 景点必须引用候选列表中的 place_id，同一天的景点必须在同一区域分组内；每天至少 2 个景点，尽量安排 3 个或更多，把上午和下午时段都用上。")
        lines.append("3. 餐厅优先选当天景点所在区域的候选")
        lines.append("4. 每日必须包含 lunch、dinner 和 hotel，且都需输出 place_id")
        lines.append("5. 多日行程时，每天选择不同区域的景点，保证多样性")
        lines.append("")
    elif candidate_places:
        # 旧路径：扁平列表（A类沉淀城市降级等场景）
        names = []
        for p in candidate_places[:40]:
            if isinstance(p, dict):
                names.append(str(p.get("name") or p.get("place_id") or p))
            else:
                names.append(str(getattr(p, "name", p)))
        lines.append("候选地点（请优先从中选择，勿使用列表外冷门点）：" + "、".join(names))

    if extra_instruction:
        lines.append("额外要求：" + extra_instruction)
    if context and context.strip():
        lines.append("")
        lines.append("【攻略上下文】")
        lines.append(context.strip())
    lines.append("")
    lines.append("请输出符合规范的行程 JSON。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON 抽取
# ---------------------------------------------------------------------------

def extract_json_object(text: str) -> dict:
    """从模型回复中提取首个 JSON 对象。"""
    if not text or not str(text).strip():
        raise PlannerParseError("模型返回空内容")
    content = str(text).strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        raise PlannerParseError("未找到 JSON 对象")
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError as e:
        raise PlannerParseError(f"JSON 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise PlannerParseError("JSON 根节点必须是对象")
    return data


def _parse_time_minutes(t: str) -> int:
    m = re.match(r"^(\d{1,2}):(\d{2})$", (t or "").strip())
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2))


# ---------------------------------------------------------------------------
# TripPlannerAgent（LangGraph 薄壳）
#
# 自第五阶段起，控制流迁移至 LangGraph StateGraph（见 planner_graph.py）。
# 本类保留为对外兼容入口：plan() / edit_day() 签名与返回值不变，
# 内部编译并调用 graph。
#
# 业务纯函数（validate_and_repair / draft_to_trip_response
# / enrich_budget_and_summary / _fallback_plan / _repair_json_with_llm
# / _sort_and_fix_times / _draft_day_to_model）作为本类的实例方法保留，
# 供 nodes.py 通过 TripPlannerAgent.__new__(TripPlannerAgent) 最小实例化复用。
# ---------------------------------------------------------------------------

class TripPlannerAgent:
    """
    行程规划 Agent（LangGraph 实现）。

    - plan(): TripRequest → TripResponse（走主图）
    - edit_day(): 单日智能调整（走单日编辑子图）

    内部使用 langgraph StateGraph；外部接口与第五阶段命令式实现保持一致。
    """

    def __init__(
        self,
        *,
        rag_tool: Any = None,
        client: Any = _UNSET,
        model: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ):
        # 兼容旧字段：仍允许外部注入 rag_tool / client
        self._rag_tool = rag_tool
        self._auto_client = client is _UNSET
        self._client = None if client is _UNSET else client
        self.model = model or settings.ZHIPU_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_tool_rounds = max(1, int(max_tool_rounds))

        # 已编译图（懒加载，首次 plan/edit_day 时构造）
        self._planner_graph = None
        self._edit_day_graph = None

    # ---------- 图懒加载 ----------

    @property
    def rag_tool(self) -> Any:
        if self._rag_tool is None:
            from app.agents.rag_tool import rag_tool as default_rag_tool

            self._rag_tool = default_rag_tool
        return self._rag_tool

    @rag_tool.setter
    def rag_tool(self, value: Any) -> None:
        self._rag_tool = value
        # 注入新 rag_tool 时重置已编译图
        self._planner_graph = None
        self._edit_day_graph = None

    def _get_planner_graph(self):
        if self._planner_graph is None:
            from app.agents.planner_graph import build_planner_graph

            # 用注入的 rag_tool 构造图（测试时可注入 mock）
            self._planner_graph = build_planner_graph(
                rag_tool=self._rag_tool if self._rag_tool is not None else None
            )
        return self._planner_graph

    def _get_edit_day_graph(self):
        if self._edit_day_graph is None:
            from app.agents.planner_graph import build_edit_day_graph

            self._edit_day_graph = build_edit_day_graph(
                rag_tool=self._rag_tool if self._rag_tool is not None else None
            )
        return self._edit_day_graph

    # ---------- LLM 客户端（仅供 _repair_json_with_llm 等老路径复用） ----------

    def _get_client(self) -> Any:
        """返回 LLM 客户端；LangGraph 主路径不使用此方法（走 llm_factory.build_llm）。"""
        if not self._auto_client:
            return self._client
        if self._client is not None:
            return self._client
        try:
            from app.agents.llm_factory import build_llm

            self._client = build_llm()
            return self._client
        except Exception as e:
            logger.warning(f"LangChain LLM 构造失败: {e}")
            return None

    # ---------- 主入口 ----------

    def plan(
        self,
        request: TripRequest,
        *,
        context: Optional[str] = None,
        candidate_places: Optional[list[Any]] = None,
        candidate_sections: Optional[dict[str, Any]] = None,
        use_tools: bool = True,
        allow_fallback: bool = True,
    ) -> TripResponse:
        """
        生成行程草案。内部走 LangGraph 主图。

        新增参数（B类动态城市）：
        - candidate_sections: 分类候选池 {scenic, food, hotel, clusters, index}
          传入时走全链路 POI 驱动模式，Agent 从候选池选点并输出 place_id。
        """
        start = time.time()
        meta: dict[str, Any] = {
            "tool_rounds": 0,
            "rag_degraded": False,
            "validation_warnings": [],
            "path": "llm",
            "needs_enrichment": True,
            "model_used": self.model,
        }

        # 从 candidate_sections 拆出分类字段供 state 使用
        sections = candidate_sections or {}
        scenic_candidates = sections.get("scenic") or []
        food_candidates = sections.get("food") or []
        hotel_candidates = sections.get("hotel") or []
        district_clusters = sections.get("clusters") or {}
        candidate_index = sections.get("index") or {}

        state: dict = {
            "request": request,
            "context": context,
            "candidate_places": candidate_places,
            "candidate_sections": candidate_sections,
            "scenic_candidates": scenic_candidates,
            "food_candidates": food_candidates,
            "hotel_candidates": hotel_candidates,
            "district_clusters": district_clusters,
            "candidate_index": candidate_index,
            "use_tools": use_tools,
            "allow_fallback": allow_fallback,
            "meta": meta,
            "messages": [],
            "validation_warnings": [],
            "repair_attempts": 0,
        }

        try:
            graph = self._get_planner_graph()
            final_state = graph.invoke(state, {"recursion_limit": 24})
        except Exception as e:
            logger.error(f"LangGraph 主图执行失败: {e}")
            if not allow_fallback:
                raise PlannerError(f"graph 执行失败: {e}") from e
            meta["path"] = "fallback"
            meta["fallback_reason"] = f"graph_crash: {e}"
            return self._fallback_plan(request, meta=meta, started_at=start)

        trip = final_state.get("trip")
        if trip is None:
            err = final_state.get("error", "graph produced no trip")
            if not allow_fallback:
                raise PlannerError(err)
            meta["path"] = "fallback"
            meta["fallback_reason"] = err
            return self._fallback_plan(request, meta=meta, started_at=start)

        # 把最终 meta 回填到 trip.metadata
        final_meta = final_state.get("meta", meta)
        final_meta.setdefault("generation_time", round(time.time() - start, 3))
        return trip.model_copy(update={"metadata": final_meta})

    def edit_day(
        self,
        trip: TripResponse,
        day_number: int,
        instruction: str,
        *,
        request: Optional[TripRequest] = None,
        context: Optional[str] = None,
        allow_fallback: bool = True,
    ) -> TripResponse:
        """单日智能调整。内部走 LangGraph 单日编辑子图。"""
        if day_number < 1 or day_number > len(trip.days):
            raise PlannerValidationError(f"无效 day_number: {day_number}")

        req = request or self._derive_request_from_trip(trip)
        meta: dict[str, Any] = {
            "tool_rounds": 0,
            "rag_degraded": False,
            "validation_warnings": [],
            "path": "edit_day",
            "needs_enrichment": True,
            "edited_day": day_number,
            "model_used": self.model,
        }

        state: dict = {
            "base_trip": trip,
            "day_number": day_number,
            "instruction": instruction,
            "request": req,
            "context": context,
            "use_tools": bool(context is None),
            "allow_fallback": allow_fallback,
            "meta": meta,
            "messages": [],
            "validation_warnings": [],
            "repair_attempts": 0,
        }

        try:
            graph = self._get_edit_day_graph()
            final_state = graph.invoke(state, {"recursion_limit": 24})
        except Exception as e:
            logger.error(f"edit_day graph 执行失败: {e}")
            if not allow_fallback:
                raise PlannerError(f"edit_day graph 失败: {e}") from e
            return trip.model_copy(
                update={
                    "metadata": {
                        **(trip.metadata or {}),
                        "edit_failed": True,
                        "edit_error": str(e),
                    }
                }
            )

        edited = final_state.get("edited_day")
        if edited is None:
            err = final_state.get("error", "edit_day produced no result")
            if not allow_fallback:
                raise PlannerError(err)
            return trip.model_copy(
                update={
                    "metadata": {
                        **(trip.metadata or {}),
                        "edit_failed": True,
                        "edit_error": err,
                    }
                }
            )
        return edited

    @staticmethod
    def _derive_request_from_trip(trip: TripResponse) -> TripRequest:
        """从 TripResponse 反推一个最小可用的 TripRequest（用于 edit_day 的单日裁剪）。

        尽量从 special_needs_notes 和 metadata 中反推原始特殊需求设置，
        确保单日编辑时特殊需求约束仍然生效。
        """
        # 从 metadata 中反推（如果保存了原始请求信息）
        meta = trip.metadata or {}
        req_data = meta.get("original_request") or {}

        # 从 special_needs_notes 反推特殊需求标志
        notes = trip.special_needs_notes or []
        notes_text = " ".join(notes)
        with_kids = bool(req_data.get("with_kids")) or ("亲子" in notes_text or "儿童" in notes_text)
        with_elderly = bool(req_data.get("with_elderly")) or ("老人" in notes_text or "适老" in notes_text)
        has_disability = bool(req_data.get("has_disability")) or ("无障碍" in notes_text or "轮椅" in notes_text)

        return TripRequest(
            destination=trip.destination,
            start_date=trip.start_date,
            end_date=trip.end_date,
            travelers=1,
            with_kids=with_kids,
            with_elderly=with_elderly,
            has_disability=has_disability,
        )

    # ------------------------------------------------------------------
    # 业务方法：以下函数被 nodes.py 通过 TripPlannerAgent.__new__ 复用。
    # 保持纯函数性质（不依赖 self 的可变状态，只读取 self.model 等只读字段）。
    # ------------------------------------------------------------------

    def _repair_json_with_llm(self, raw_text: str, error: str) -> Optional[str]:
        """LLM 修复 JSON。供 nodes.repair_json_node 复用。"""
        client = self._get_client()
        if client is None:
            return None
        try:
            # 兼容 LangChain BaseChatModel 与旧版 zai 客户端
            if hasattr(client, "chat") and hasattr(client.chat, "completions"):
                # 旧版 zai 路径
                resp = client.chat.completions.create(
                    model=self.model or settings.ZHIPU_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": "你只输出合法 JSON 对象，不要解释。修复用户给出的行程 JSON。",
                        },
                        {
                            "role": "user",
                            "content": f"校验错误：{error}\n\n原始内容：\n{raw_text[:6000]}",
                        },
                    ],
                    temperature=0.0,
                    max_tokens=self.max_tokens,
                )
                return (resp.choices[0].message.content or "").strip()
            else:
                # LangChain BaseChatModel 路径
                from langchain_core.messages import HumanMessage, SystemMessage

                resp = client.invoke(
                    [
                        SystemMessage(
                            content="你只输出合法 JSON 对象，不要解释。修复用户给出的行程 JSON。"
                        ),
                        HumanMessage(
                            content=f"校验错误：{error}\n\n原始内容：\n{raw_text[:6000]}"
                        ),
                    ],
                    temperature=0.0,
                    max_tokens=self.max_tokens,
                )
                content = getattr(resp, "content", "") or ""
                return content.strip()
        except Exception as e:
            logger.warning(f"JSON 修复调用失败: {e}")
            return None

    def draft_to_trip_response(
        self,
        draft: DraftItinerary,
        request: TripRequest,
        *,
        meta: Optional[dict] = None,
        started_at: Optional[float] = None,
        candidate_index: Optional[dict[str, Any]] = None,
    ) -> TripResponse:
        """草案 → TripResponse。

        当 candidate_index 传入时（B类动态城市），用候选池中的真实坐标/地址/图片填充，
        不再使用占位符。无候选数据时退回占位模式（A类路径不变）。
        """
        total_days = (request.end_date - request.start_date).days + 1
        days: list[ItineraryDay] = []
        for i in range(total_days):
            d = request.start_date + timedelta(days=i)
            src = next((x for x in draft.days if x.day_number == i + 1), None)
            if src is None and i < len(draft.days):
                src = draft.days[i]
            if src is None:
                src = DraftDay(day_number=i + 1, items=[])
            days.append(self._draft_day_to_model(
                src, day_number=i + 1, day_date=d, candidate_index=candidate_index,
                request=request,
            ))

        trip_name = draft.trip_name or f"{request.destination}{total_days}日游"
        elapsed = round(time.time() - started_at, 3) if started_at else 0.0

        # 总体综合评分：取每天综合评分的平均值（每天都已是非零基准分或真实均值）。
        overall_rating = (
            round(sum(d.total_rating for d in days) / len(days), 1) if days else DEFAULT_RATING
        )
        overall_rating = min(5.0, max(0.0, overall_rating))

        special_needs_notes = list(draft.special_needs_notes or [])
        if not special_needs_notes:
            notes = []
            if request.with_kids:
                notes.append("已优先安排亲子友好、安全可控的景点，避免高强度徒步与危险区域")
                notes.append("行程节奏舒缓，预留充足休息与用餐时间，适合儿童体力")
            if request.with_elderly:
                notes.append("已安排轻松、少步行的路线，每日景点数量适中，控制体力消耗")
                notes.append("优先选择有休息设施、平坦好走的景点，避免长时间爬山")
            if request.has_disability:
                notes.append("已优先选择无障碍通道可达、台阶少、地面平缓的景点")
                notes.append("每日行程均考虑轮椅通行便利性，尽量减少步行距离")
            special_needs_notes = notes

        return TripResponse(
            trip_id=str(uuid.uuid4()),
            destination=request.destination,
            trip_name=trip_name,
            start_date=request.start_date,
            end_date=request.end_date,
            total_days=total_days,
            days=days,
            overall_rating=overall_rating,
            budget=BudgetInfo(
                total_budget=0,
                daily_avg_budget=0,
                budget_per_person=0,
            ),
            trip_highlights=list(draft.trip_highlights or []),
            trip_tips=list(draft.trip_tips or []),
            special_needs_notes=special_needs_notes,
            recommended_foods=list(draft.recommended_foods or []),
            recommended_shopping=list(draft.recommended_shopping or []),
            generated_at=datetime.now(),
            generation_time=elapsed,
            model_used=self.model,
            metadata=meta or {"needs_enrichment": True},
        )

    def _draft_day_to_model(
        self,
        src: DraftDay,
        *,
        day_number: int,
        day_date: date,
        candidate_index: Optional[dict[str, Any]] = None,
        request: Optional[TripRequest] = None,
    ) -> ItineraryDay:
        idx_map = candidate_index or {}

        def _lookup(place_id: Optional[str]) -> Optional[dict[str, Any]]:
            """从候选索引中按 place_id 查找完整 POI 数据。"""
            if not place_id or not idx_map:
                return None
            return idx_map.get(place_id)

        def _coord_from_dict(d: dict[str, Any]) -> Coordinate:
            c = d.get("coordinate")
            if isinstance(c, dict) and c.get("latitude") is not None:
                return Coordinate(
                    latitude=float(c["latitude"]),
                    longitude=float(c["longitude"]),
                )
            return PLACEHOLDER_COORD

        items: list[ItineraryItem] = []
        for idx, it in enumerate(src.items):
            cp = _lookup(it.place_id)
            if cp:
                # B类动态城市：用候选池真实数据
                place = PlaceInfo(
                    place_id=it.place_id or cp.get("place_id", ""),
                    name=cp.get("name", it.name),
                    address=cp.get("address") or PLACEHOLDER_ADDRESS,
                    coordinate=_coord_from_dict(cp),
                    district=cp.get("district"),
                    category=it.category or cp.get("category") or "景点",
                    tags=list(cp.get("tags") or [])[:6],
                    suggested_duration=it.duration_minutes,
                    ticket_price=it.ticket_price if it.ticket_price is not None else cp.get("cost"),
                    is_free=(it.ticket_price == 0) if it.ticket_price is not None else False,
                    rating=cp.get("rating"),
                    images=list(cp.get("photos") or [])[:3],
                    cover_image=(cp.get("photos") or [None])[0] if cp.get("photos") else None,
                    phone=cp.get("telephone") or None,
                    highlight=it.activity,
                    # 适合人群（从候选池推断结果填充）
                    suitable_for_kids=bool(cp.get("suitable_for_kids", True)),
                    suitable_for_elderly=bool(cp.get("suitable_for_elderly", True)),
                    has_wheelchair=bool(cp.get("has_wheelchair_access", False)),
                )
            else:
                # A类沉淀城市 / 降级路径：占位模式
                place = PlaceInfo(
                    place_id=it.place_id or f"draft-{day_number}-{idx}-{abs(hash(it.name)) % 100000}",
                    name=it.name,
                    address=PLACEHOLDER_ADDRESS,
                    coordinate=PLACEHOLDER_COORD,
                    category=it.category or "景点",
                    suggested_duration=it.duration_minutes,
                    ticket_price=it.ticket_price,
                    is_free=(it.ticket_price == 0) if it.ticket_price is not None else False,
                    highlight=it.activity,
                )
            items.append(
                ItineraryItem(
                    start_time=it.start_time,
                    end_time=it.end_time,
                    place=place,
                    activity=it.activity or "游览",
                    activity_detail=it.activity_detail,
                    ticket_price=place.ticket_price,
                    tips=list(it.tips or []),
                )
            )

        def meal(m: Optional[DraftMeal]) -> Optional[RestaurantInfo]:
            if not m:
                return None
            cp = _lookup(m.place_id)
            if cp:
                coord = _coord_from_dict(cp)
                photos = list(cp.get("photos") or [])
                return RestaurantInfo(
                    place_id=m.place_id or cp.get("place_id", ""),
                    name=cp.get("name", m.name),
                    coordinate=coord,
                    address=cp.get("address") or PLACEHOLDER_ADDRESS,
                    cuisine_type=m.cuisine_type or "本地菜",
                    price_range=f"{int(m.avg_price)}元左右",
                    avg_price=m.avg_price,
                    rating=cp.get("rating"),
                    images=photos[:3],
                    tags=list(cp.get("tags") or [])[:4],
                    suitable_for_kids=bool(cp.get("suitable_for_kids", True)),
                    suitable_for_elderly=bool(cp.get("suitable_for_elderly", True)),
                    has_wheelchair=bool(cp.get("has_wheelchair_access", False)),
                )
            return RestaurantInfo(
                place_id=m.place_id or f"meal-{abs(hash(m.name)) % 100000}",
                name=m.name,
                coordinate=PLACEHOLDER_COORD,
                address=m.address or PLACEHOLDER_ADDRESS,
                cuisine_type=m.cuisine_type or "本地菜",
                price_range=f"{int(m.avg_price)}元左右",
                avg_price=m.avg_price,
            )

        hotel = None
        if src.hotel:
            cp = _lookup(src.hotel.place_id)
            if cp:
                coord = _coord_from_dict(cp)
                photos = list(cp.get("photos") or [])
                hotel = HotelInfo(
                    place_id=src.hotel.place_id or cp.get("place_id", ""),
                    name=cp.get("name", src.hotel.name),
                    coordinate=coord,
                    address=cp.get("address") or PLACEHOLDER_ADDRESS,
                    hotel_type=src.hotel.hotel_type or "舒适型",
                    price=src.hotel.price,
                    price_range=f"{int(src.hotel.price)}元/晚",
                    rating=cp.get("rating"),
                    images=photos[:3],
                    cover_image=photos[0] if photos else None,
                    tags=list(cp.get("tags") or [])[:4],
                    suitable_for_kids=bool(cp.get("suitable_for_kids", True)),
                    suitable_for_elderly=bool(cp.get("suitable_for_elderly", True)),
                    has_wheelchair=bool(cp.get("has_wheelchair_access", True)),
                )
            else:
                hotel = HotelInfo(
                    place_id=src.hotel.place_id or f"hotel-{abs(hash(src.hotel.name)) % 100000}",
                    name=src.hotel.name,
                    coordinate=PLACEHOLDER_COORD,
                    address=src.hotel.address or PLACEHOLDER_ADDRESS,
                    hotel_type=src.hotel.hotel_type or "舒适型",
                    price=src.hotel.price,
                    price_range=f"{int(src.hotel.price)}元/晚",
                )

        duration = sum(it.place.suggested_duration for it in items)
        lunch_model = meal(src.lunch)
        dinner_model = meal(src.dinner)

        # 当日综合评分：取当天所有有评分的项目（景点/餐厅/酒店）的平均值。
        # 若当天没有任何真实评分（占位模式），则回落到默认基准分。
        day_ratings: list[float] = []
        for it in items:
            if it.place.rating is not None:
                day_ratings.append(float(it.place.rating))
        for m in (lunch_model, dinner_model):
            if m and m.rating is not None:
                day_ratings.append(float(m.rating))
        if hotel and hotel.rating is not None:
            day_ratings.append(float(hotel.rating))
        total_rating = (
            round(sum(day_ratings) / len(day_ratings), 1) if day_ratings else DEFAULT_RATING
        )
        total_rating = min(5.0, max(0.0, total_rating))

        # 根据特殊需求补充每日提示
        extra_tips: list[str] = []
        if request and request.with_kids:
            extra_tips.append("带娃出行：请看好孩子，注意安全，备好水和零食")
            extra_tips.append("每1-2小时安排休息，避免孩子过度疲劳哭闹")
        if request and request.with_elderly:
            extra_tips.append("老人出行：量力而行，累了及时休息，随身携带常用药品")
            extra_tips.append("选择有座椅和遮阴的休息点，避免长时间暴晒或站立")
        if request and request.has_disability:
            extra_tips.append("无障碍提示：出行前确认景点无障碍设施开放情况，建议提前预约")
            extra_tips.append("随身携带残障证件，多数景点可享免票或优惠")

        daily_tips = list(src.daily_tips or []) + extra_tips

        return ItineraryDay(
            day_number=day_number,
            itinerary_date=day_date,
            day_theme=src.day_theme,
            items=items,
            total_places=len(items),
            total_duration=duration,
            total_rating=total_rating,
            daily_tips=daily_tips,
            breakfast=None,  # 不安排早餐
            lunch=lunch_model,
            dinner=dinner_model,
            hotel=hotel,
        )

    # ---------- 校验 ----------

    def validate_and_repair(
        self,
        draft: DraftItinerary,
        request: TripRequest,
        *,
        candidate_index: Optional[dict[str, Any]] = None,
        district_clusters: Optional[dict[str, list[str]]] = None,
        food_candidates: Optional[list[Any]] = None,
        hotel_candidates: Optional[list[Any]] = None,
    ) -> tuple[DraftItinerary, list[str]]:
        """校验与修复草案。

        新增（B类动态城市）：
        - place_id 合法性校验：检查景点/餐饮/酒店是否在候选池内
        - 跨 cluster 检测：同日景点必须在同一区域分组
        - 食宿缺失补选：lunch/dinner/hotel 缺失时从候选池自动补选
        """
        warnings: list[str] = []
        total_days = (request.end_date - request.start_date).days + 1
        excluded = [str(x).strip() for x in (request.excluded_keywords or []) if str(x).strip()]
        max_places = request.max_places_per_day

        idx_map = candidate_index or {}
        clusters = district_clusters or {}
        food_pool = food_candidates or []
        hotel_pool = hotel_candidates or []

        # 构建反向索引：place_id → cluster_name
        pid_to_cluster: dict[str, str] = {}
        for cluster_name, pids in clusters.items():
            for pid in pids:
                pid_to_cluster[pid] = cluster_name

        # 对齐天数
        by_num: dict[int, DraftDay] = {}
        for d in draft.days:
            by_num[d.day_number] = d
        new_days: list[DraftDay] = []
        used_global_scenic: set[str] = set()
        for i in range(1, total_days + 1):
            day = by_num.get(i)
            if day is None and draft.days:
                if i - 1 < len(draft.days):
                    day = draft.days[i - 1].model_copy(deep=True)
                    day.day_number = i
                else:
                    day = DraftDay(day_number=i, items=[])
                    warnings.append(f"第{i}天缺失，已补空日")
            elif day is None:
                day = DraftDay(day_number=i, items=[])
                warnings.append(f"第{i}天缺失，已补空日")
            else:
                day = day.model_copy(deep=True)
                day.day_number = i

            day.itinerary_date = request.start_date + timedelta(days=i - 1)

            # 排除词
            if excluded:
                kept = []
                for it in day.items:
                    if any(ex in it.name for ex in excluded):
                        warnings.append(f"第{i}天移除排除地点: {it.name}")
                    else:
                        kept.append(it)
                day.items = kept

            # place_id 合法性校验（B类路径）
            if idx_map:
                for it in day.items:
                    if it.place_id and it.place_id not in idx_map:
                        # 尝试按名称匹配候选池
                        matched = False
                        for pid, cp in idx_map.items():
                            if isinstance(cp, dict) and cp.get("name") == it.name:
                                it.place_id = pid
                                matched = True
                                break
                        if not matched:
                            warnings.append(f"第{i}天 [{it.name}] place_id 不在候选池")

            # 跨 cluster 检测
            if pid_to_cluster and day.items:
                cluster_counts: dict[str, int] = {}
                for it in day.items:
                    c = pid_to_cluster.get(it.place_id or "", "未知")
                    cluster_counts[c] = cluster_counts.get(c, 0) + 1
                if len(cluster_counts) > 1:
                    majority = max(cluster_counts, key=cluster_counts.get)
                    minority_pids = [
                        it.place_id for it in day.items
                        if pid_to_cluster.get(it.place_id or "", "") != majority
                    ]
                    if minority_pids:
                        warnings.append(
                            f"第{i}天跨区域: 多数在[{majority}]，"
                            f"少数{minority_pids}建议替换"
                        )

            # 特殊需求硬约束校验（B类路径，有候选池时）
            if idx_map and (request.with_kids or request.with_elderly or request.has_disability):
                kept_items = []
                replaced_count = 0
                for it in day.items:
                    cp = idx_map.get(it.place_id or "")
                    if not cp:
                        kept_items.append(it)
                        continue
                    suitable = True
                    reasons = []
                    if request.with_kids and not cp.get("suitable_for_kids", True):
                        suitable = False
                        reasons.append("不适合儿童")
                    if request.with_elderly and not cp.get("suitable_for_elderly", True):
                        suitable = False
                        reasons.append("不适合老人")
                    if request.has_disability and not cp.get("has_wheelchair_access", False):
                        suitable = False
                        reasons.append("无障碍不便")
                    if suitable:
                        kept_items.append(it)
                    else:
                        replaced_count += 1
                        warnings.append(
                            f"第{i}天 [{it.name}] 不符合特殊需求（{'/'.join(reasons)}），将替换"
                        )
                if replaced_count > 0:
                    day.items = kept_items

            # 裁剪景点数
            if len(day.items) > max_places:
                warnings.append(f"第{i}天景点 {len(day.items)}>{max_places}，已裁剪")
                day.items = day.items[:max_places]

            # 景点数不足补选（B类路径）：每天至少 MIN_PLACES_PER_DAY 个
            used_global_scenic.update(it.place_id for it in day.items if it.place_id)
            if idx_map and len(day.items) < MIN_PLACES_PER_DAY:
                need = MIN_PLACES_PER_DAY - len(day.items)
                current_pids = {it.place_id for it in day.items if it.place_id}
                existing_clusters = {
                    pid_to_cluster.get(pid)
                    for pid in current_pids
                    if pid_to_cluster.get(pid)
                }

                def _is_suitable(pid: str) -> bool:
                    """检查候选是否符合特殊需求硬约束。"""
                    cp = idx_map.get(pid)
                    if not isinstance(cp, dict):
                        return True  # 无数据时默认通过
                    if request.with_kids and not cp.get("suitable_for_kids", True):
                        return False
                    if request.with_elderly and not cp.get("suitable_for_elderly", True):
                        return False
                    if request.has_disability and not cp.get("has_wheelchair_access", False):
                        # 行动不便时严格要求无障碍，若无则跳过
                        return False
                    return True

                same_cluster_suitable: list[str] = []
                same_cluster_other: list[str] = []
                other_cluster_suitable: list[str] = []
                other_cluster_other: list[str] = []

                for cluster_name, pids in clusters.items():
                    in_same = cluster_name in existing_clusters
                    for pid in pids:
                        if pid in used_global_scenic or pid in current_pids:
                            continue
                        cp = idx_map.get(pid)
                        if not isinstance(cp, dict):
                            continue
                        name = cp.get("name", "")
                        if excluded and any(ex in name for ex in excluded):
                            continue
                        suitable = _is_suitable(pid)
                        if in_same:
                            if suitable:
                                same_cluster_suitable.append(pid)
                            else:
                                same_cluster_other.append(pid)
                        else:
                            if suitable:
                                other_cluster_suitable.append(pid)
                            else:
                                other_cluster_other.append(pid)

                def _rating_key(pid: str) -> float:
                    cp = idx_map.get(pid) or {}
                    try:
                        return -float(cp.get("rating") or 0.0)
                    except (TypeError, ValueError):
                        return 0.0

                # 优先级：同区域符合特殊需求 > 同区域其他 > 跨区域符合 > 跨区域其他
                same_cluster_suitable.sort(key=_rating_key)
                same_cluster_other.sort(key=_rating_key)
                other_cluster_suitable.sort(key=_rating_key)
                other_cluster_other.sort(key=_rating_key)

                picked: list[str] = []
                for bucket in [same_cluster_suitable, same_cluster_other,
                               other_cluster_suitable, other_cluster_other]:
                    if len(picked) >= need:
                        break
                    remaining = need - len(picked)
                    picked += bucket[:remaining]

                for pid in picked:
                    cp = idx_map[pid]
                    name = cp.get("name", "")
                    cost = cp.get("cost")
                    try:
                        ticket = float(cost) if cost else 0.0
                    except (TypeError, ValueError):
                        ticket = 0.0
                    day.items.append(
                        DraftItem(
                            name=name,
                            place_id=pid,
                            category="景点",
                            activity="游览",
                            start_time="14:00",
                            end_time="16:30",
                            duration_minutes=150,
                            ticket_price=ticket,
                        )
                    )
                    used_global_scenic.add(pid)
                    warnings.append(f"第{i}天景点不足，已自动补选: {name}")

            # 食宿缺失补选（B类路径）- 优先选择符合特殊需求的
            has_special_needs = request.with_kids or request.with_elderly or request.has_disability

            def _food_is_suitable(fp: dict) -> bool:
                """检查餐厅是否符合特殊需求。"""
                if not has_special_needs:
                    return True
                if request.with_kids and not fp.get("suitable_for_kids", True):
                    return False
                if request.with_elderly and not fp.get("suitable_for_elderly", True):
                    return False
                # 餐厅无障碍一般不做强约束，只做优先排序
                return True

            def _hotel_is_suitable(hp: dict) -> bool:
                """检查酒店是否符合特殊需求。"""
                if not has_special_needs:
                    return True
                if request.with_kids and not hp.get("suitable_for_kids", True):
                    return False
                if request.with_elderly and not hp.get("suitable_for_elderly", True):
                    return False
                if request.has_disability and not hp.get("has_wheelchair_access", False):
                    return False
                return True

            def _pick_best_food(used_pids: set[str]) -> Optional[dict]:
                """优先选择符合特殊需求的餐厅，其次选评分最高的。"""
                suitable = []
                others = []
                for fp in food_pool:
                    if not isinstance(fp, dict):
                        continue
                    pid = fp.get("place_id")
                    if not pid or pid in used_pids:
                        continue
                    if _food_is_suitable(fp):
                        suitable.append(fp)
                    else:
                        others.append(fp)
                # 按评分排序
                suitable.sort(key=lambda x: -(x.get("rating") or 0))
                others.sort(key=lambda x: -(x.get("rating") or 0))
                pool = suitable + others
                return pool[0] if pool else None

            if food_pool and not day.lunch:
                used_pids = {m.place_id for m in [day.lunch, day.dinner] if m}
                best = _pick_best_food(used_pids)
                if best:
                    day.lunch = DraftMeal(
                        name=best.get("name", ""),
                        place_id=best.get("place_id", ""),
                        cuisine_type=best.get("category", "本地菜"),
                        avg_price=float(best.get("cost") or 50),
                    )
                    used_pids.add(best.get("place_id", ""))
                    warnings.append(f"第{i}天午餐缺失，已自动补选: {best.get('name')}")
            if food_pool and not day.dinner:
                used_pids = {m.place_id for m in [day.lunch, day.dinner] if m}
                best = _pick_best_food(used_pids)
                if best:
                    day.dinner = DraftMeal(
                        name=best.get("name", ""),
                        place_id=best.get("place_id", ""),
                        cuisine_type=best.get("category", "本地菜"),
                        avg_price=float(best.get("cost") or 80),
                    )
                    warnings.append(f"第{i}天晚餐缺失，已自动补选: {best.get('name')}")

            if hotel_pool and not day.hotel:
                # 优先选择符合特殊需求的酒店
                suitable_hotels = []
                other_hotels = []
                for hp in hotel_pool:
                    if not isinstance(hp, dict):
                        continue
                    if _hotel_is_suitable(hp):
                        suitable_hotels.append(hp)
                    else:
                        other_hotels.append(hp)
                suitable_hotels.sort(key=lambda x: -(x.get("rating") or 0))
                other_hotels.sort(key=lambda x: -(x.get("rating") or 0))
                all_hotels = suitable_hotels + other_hotels
                best = all_hotels[0] if all_hotels else None
                if best:
                    day.hotel = DraftHotel(
                        name=best.get("name", ""),
                        place_id=best.get("place_id", ""),
                        hotel_type="舒适型",
                        price=float(best.get("cost") or 300),
                    )
                    warnings.append(f"第{i}天酒店缺失，已自动补选: {best.get('name')}")

            # 强制清除 breakfast（不安排早餐）
            day.breakfast = None

            # 时间排序与简单去重叠
            day.items = self._sort_and_fix_times(day.items, warnings, day_number=i)
            new_days.append(day)

        if len(draft.days) != total_days:
            warnings.append(f"天数已对齐为 {total_days}")

        draft = draft.model_copy(update={"days": new_days})

        # 硬失败：全部日无任何安排且无餐饮（通常是空模型）
        if total_days > 0 and all(not d.items for d in draft.days):
            warnings.append("所有日均无景点安排")

        return draft, warnings

    def _sort_and_fix_times(
        self, items: list[DraftItem], warnings: list[str], *, day_number: int
    ) -> list[DraftItem]:
        if not items:
            return items
        ordered = sorted(items, key=lambda x: _parse_time_minutes(x.start_time))
        fixed: list[DraftItem] = []
        prev_end = -1
        for it in ordered:
            start = _parse_time_minutes(it.start_time)
            end = _parse_time_minutes(it.end_time)
            if end <= start:
                end = start + max(30, it.duration_minutes or 60)
                it.end_time = f"{end // 60:02d}:{end % 60:02d}"
                warnings.append(f"第{day_number}天修正时间段: {it.name}")
            if start < prev_end:
                start = prev_end
                duration = max(30, end - _parse_time_minutes(it.start_time))
                end = start + duration
                if end >= 24 * 60:
                    end = 24 * 60 - 1
                it.start_time = f"{start // 60:02d}:{start % 60:02d}"
                it.end_time = f"{end // 60:02d}:{end % 60:02d}"
                warnings.append(f"第{day_number}天调整重叠时间: {it.name}")
            prev_end = _parse_time_minutes(it.end_time)
            fixed.append(it)
        return fixed

    # ---------- 贴士增强 ----------

    def _build_enriched_tips(
        self,
        raw_tips: list[str],
        request: TripRequest,
        destination: Optional[str] = None,
    ) -> tuple[list[str], list[TripTipCategory]]:
        """将 LLM 生成的扁平贴士 + 上下文信息合成为结构化分类贴士。

        返回 (flat_tips, grouped_tips)：
        - flat_tips: 兼容旧字段的扁平字符串列表
        - grouped_tips: List[TripTipCategory]，按 TIP_CATEGORIES 顺序排列
        """
        dest = destination or request.destination or ""
        grouped: dict[str, list[str]] = {cat: [] for cat in TIP_CATEGORIES}

        # 1) 解析 LLM 生成的贴士（支持"【分类】内容"格式或无格式纯文本）
        for tip in raw_tips:
            tip = tip.strip()
            if not tip:
                continue
            matched = False
            for cat in TIP_CATEGORIES:
                if f"【{cat}】" in tip:
                    content = tip.replace(f"【{cat}】", "").strip()
                    if content and content not in grouped[cat]:
                        grouped[cat].append(content)
                    matched = True
                    break
            if not matched:
                # 尝试关键词匹配
                tip_lower = tip
                keyword_map = {
                    "出行准备": ["准备", "预约", "证件", "打包", "行前"],
                    "交通出行": ["交通", "地铁", "公交", "打车", "租车", "停车", "骑行"],
                    "省钱攻略": ["省钱", "优惠", "免费", "折扣", "性价比"],
                    "美食推荐": ["美食", "吃", "餐厅", "小吃", "火锅"],
                    "住宿建议": ["住宿", "酒店", "民宿", "入住", "退房"],
                    "安全须知": ["安全", "财物", "防盗", "危险", "急救"],
                    "文化礼仪": ["礼仪", "风俗", "禁忌", "宗教", "拍照"],
                    "天气穿搭": ["天气", "穿搭", "防晒", "保暖", "穿衣", "雨具"],
                    "实用工具": ["APP", "应用", "导航", "翻译", "支付", "工具"],
                    "应急联系": ["报警", "急救", "医院", "领事馆", "应急", "110", "120", "119"],
                }
                for cat, keywords in keyword_map.items():
                    if any(kw in tip_lower for kw in keywords):
                        if tip not in grouped[cat]:
                            grouped[cat].append(tip)
                        matched = True
                        break
                if not matched:
                    if tip not in grouped["出行准备"]:
                        grouped["出行准备"].append(tip)

        # 2) 追加城市专属贴士
        city_tips = CITY_SPECIFIC_TIPS.get(dest, {})
        for cat, tips_list in city_tips.items():
            for t in tips_list:
                if t not in grouped.get(cat, []):
                    grouped.setdefault(cat, []).append(t)

        # 3) 追加季节贴士
        month = request.start_date.month if request.start_date else 1
        if month in (3, 4, 5):
            season = "spring"
        elif month in (6, 7, 8):
            season = "summer"
        elif month in (9, 10, 11):
            season = "autumn"
        else:
            season = "winter"
        for t in SEASON_TIPS.get(season, []):
            if t not in grouped["天气穿搭"]:
                grouped["天气穿搭"].append(t)

        # 4) 追加旅行风格贴士
        style_key = getattr(request.travel_style, "value", str(request.travel_style))
        for t in TRAVEL_STYLE_TIPS.get(str(style_key), []):
            if t not in grouped["出行准备"]:
                grouped["出行准备"].append(t)

        # 5) 追加预算贴士
        budget_key = getattr(request.budget_level, "value", str(request.budget_level))
        for t in BUDGET_TIPS.get(str(budget_key), []):
            if t not in grouped["省钱攻略"]:
                grouped["省钱攻略"].append(t)

        # 6) 追加特殊需求贴士
        if request.with_kids:
            for t in SPECIAL_NEEDS_TIPS.get("with_kids", []):
                if t not in grouped["安全须知"]:
                    grouped["安全须知"].append(t)
        if request.with_elderly:
            for t in SPECIAL_NEEDS_TIPS.get("with_elderly", []):
                if t not in grouped["安全须知"]:
                    grouped["安全须知"].append(t)
        if request.has_disability:
            for t in SPECIAL_NEEDS_TIPS.get("has_disability", []):
                if t not in grouped["安全须知"]:
                    grouped["安全须知"].append(t)

        # 7) 补充通用兜底贴士（仅当该分类为空时）
        default_tips = {
            "出行准备": ["出行前确认景点开放时间与预约要求，热门景点建议提前7天预约"],
            "交通出行": ["建议下载离线地图，以防信号不佳时导航中断"],
            "省钱攻略": ["关注景点官方公众号，常有限时优惠和免票活动"],
            "美食推荐": ["避开景区门口的餐厅，往巷子里走200米往往性价比更高"],
            "住宿建议": ["入住时确认退房时间，部分酒店可免费延迟退房"],
            "安全须知": ["贵重物品随身携带，酒店保险箱存放护照和多余现金"],
            "文化礼仪": ["进入宗教场所请着装得体，部分场所需脱鞋或戴头巾"],
            "天气穿搭": ["建议穿舒适运动鞋，每日步行量可能超过1万步"],
            "实用工具": ["建议安装当地公交/地铁APP，比通用地图更准实时班次"],
            "应急联系": ["全国统一报警电话110，急救120，火警119"],
        }
        for cat, tips_list in default_tips.items():
            if not grouped.get(cat):
                grouped[cat] = tips_list[:]

        # 8) 构建 TripTipCategory 列表（按 TIP_CATEGORIES 顺序）
        result_grouped: list[TripTipCategory] = []
        flat: list[str] = []
        for cat, icon in TIP_CATEGORIES.items():
            tips = grouped.get(cat, [])
            if tips:
                result_grouped.append(
                    TripTipCategory(category=cat, icon=icon, tips=tips)
                )
                for t in tips:
                    flat.append(f"【{cat}】{t}")

        return flat, result_grouped

    # ---------- 预算与摘要 ----------

    def enrich_budget_and_summary(
        self,
        trip: TripResponse,
        request: TripRequest,
        draft: Optional[DraftItinerary] = None,
    ) -> TripResponse:
        level = getattr(request.budget_level, "value", request.budget_level)
        daily_base = BUDGET_DAILY_BASE.get(str(level), 600.0)
        if request.daily_budget is not None:
            daily_base = float(request.daily_budget)

        total_days = trip.total_days
        travelers = max(1, request.travelers)

        accommodation = 0.0
        food = 0.0
        ticket = 0.0
        for day in trip.days:
            if day.hotel:
                accommodation += float(day.hotel.price or 0)
            else:
                accommodation += daily_base * ACCOMMODATION_SHARE
            meal_cost = 0.0
            for meal in (day.breakfast, day.lunch, day.dinner):
                if meal:
                    meal_cost += float(meal.avg_price or 0) * travelers
            if meal_cost <= 0:
                meal_cost = request.restaurant_budget_per_meal * 3 * travelers
            food += meal_cost
            day_ticket = 0.0
            for it in day.items:
                if it.ticket_price is not None:
                    day_ticket += float(it.ticket_price) * travelers
                elif it.place.ticket_price is not None:
                    day_ticket += float(it.place.ticket_price) * travelers
            if day_ticket <= 0:
                day_ticket = daily_base * TICKET_SHARE * travelers
            ticket += day_ticket
            day_cost = (
                (float(day.hotel.price) if day.hotel else daily_base * ACCOMMODATION_SHARE)
                + meal_cost
                + day_ticket
                + daily_base * TRANSPORT_SHARE
            )
            day.daily_cost = round(day_cost, 2)
            day.cost_breakdown = {
                "accommodation": round(
                    float(day.hotel.price) if day.hotel else daily_base * ACCOMMODATION_SHARE,
                    2,
                ),
                "food": round(meal_cost, 2),
                "ticket": round(day_ticket, 2),
                "transportation": round(daily_base * TRANSPORT_SHARE, 2),
            }

        transport = daily_base * TRANSPORT_SHARE * total_days
        other = daily_base * OTHER_SHARE * total_days
        total = accommodation + food + ticket + transport + other
        budget = BudgetInfo(
            total_budget=round(total, 2),
            daily_avg_budget=round(total / max(1, total_days), 2),
            budget_per_person=round(total / travelers, 2),
            accommodation_budget=round(accommodation, 2),
            food_budget=round(food, 2),
            transportation_budget=round(transport, 2),
            ticket_budget=round(ticket, 2),
            shopping_budget=0.0,
            other_budget=round(other, 2),
            budget_status="within_budget",
        )

        highlights = list(trip.trip_highlights or [])
        tips = list(trip.trip_tips or [])
        foods = list(trip.recommended_foods or [])
        if draft:
            if not highlights:
                highlights = list(draft.trip_highlights or [])
            if not tips:
                tips = list(draft.trip_tips or [])
            if not foods:
                foods = list(draft.recommended_foods or [])
        if not highlights:
            names = [it.place.name for d in trip.days for it in d.items][:5]
            if names:
                highlights = [f"打卡{'、'.join(names)}"]
        if not tips:
            tips = [
                "【出行准备】出行前确认景点开放时间与预约要求，热门景点建议提前7天预约",
                "【出行准备】合理安排体力，预留交通缓冲时间",
                "【交通出行】建议下载离线地图，以防信号不佳时导航中断",
                "【省钱攻略】关注景点官方公众号，常有限时优惠和免票活动",
                "【安全须知】贵重物品随身携带，酒店保险箱存放护照和多余现金",
                "【应急联系】全国统一报警电话110，急救120，火警119",
            ]
        if not foods:
            for d in trip.days:
                for meal in (d.lunch, d.dinner):
                    if meal and meal.name not in foods:
                        foods.append(meal.name)
                if len(foods) >= 5:
                    break

        flat_tips, grouped_tips = self._build_enriched_tips(
            tips, request, destination=trip.destination
        )

        style = _style_cn(request.travel_style)
        trip_name = trip.trip_name or f"{request.destination}{total_days}日{style}行程"

        return trip.model_copy(
            update={
                "trip_name": trip_name,
                "budget": budget,
                "trip_highlights": highlights,
                "trip_tips": flat_tips,
                "trip_tips_grouped": grouped_tips,
                "recommended_foods": foods[:8],
                "metadata": {
                    **(trip.metadata or {}),
                    "budget_level": str(level),
                },
            }
        )

    # ---------- 降级 ----------

    def _fallback_plan(
        self,
        request: TripRequest,
        *,
        meta: dict,
        started_at: float,
    ) -> TripResponse:
        """RAG 片段 + 默认时段模板拼装。供 nodes.fallback_node 复用。"""
        context = ""
        place_names: list[str] = []
        try:
            result = self.rag_tool.search_for_trip(request)
            context = getattr(result, "context_text", "") or ""
            chunks = getattr(result, "chunks", None) or []
            meta["rag_degraded"] = bool(
                getattr(getattr(result, "stats", None), "degraded", False)
            )
            for ch in chunks:
                section = getattr(ch, "section", None) or ""
                content = getattr(ch, "content", "") or ""
                for cand in (section,):
                    if cand and 1 < len(cand) <= 20 and cand not in place_names:
                        place_names.append(cand)
                for m in re.finditer(r"[「【]([^」】]{2,12})[」】]", content):
                    name = m.group(1)
                    if name not in place_names:
                        place_names.append(name)
                if len(place_names) >= 20:
                    break
        except Exception as e:
            logger.warning(f"降级预取失败: {e}")

        if not place_names:
            # 根据特殊需求调整降级默认景点
            if request.with_kids:
                place_names = [
                    f"{request.destination}亲子公园",
                    f"{request.destination}科技馆",
                    f"{request.destination}动物园",
                    f"{request.destination}儿童乐园",
                ]
            elif request.with_elderly:
                place_names = [
                    f"{request.destination}休闲公园",
                    f"{request.destination}博物馆",
                    f"{request.destination}古镇漫步",
                    f"{request.destination}文化广场",
                ]
            elif request.has_disability:
                place_names = [
                    f"{request.destination}博物馆",
                    f"{request.destination}城市广场",
                    f"{request.destination}美术馆",
                    f"{request.destination}商场步行街",
                ]
            else:
                place_names = [
                    f"{request.destination}市区漫步",
                    f"{request.destination}特色街区",
                    f"{request.destination}当地餐厅",
                    f"{request.destination}夜景点",
                ]

        total_days = (request.end_date - request.start_date).days + 1
        max_places = request.max_places_per_day
        days: list[DraftDay] = []
        cursor = 0
        for i in range(total_days):
            items: list[DraftItem] = []
            n = min(max_places, max(1, len(DEFAULT_TIME_SLOTS)))
            for j in range(n):
                name = place_names[cursor % len(place_names)]
                cursor += 1
                start_t, end_t = DEFAULT_TIME_SLOTS[j % len(DEFAULT_TIME_SLOTS)]
                items.append(
                    DraftItem(
                        start_time=start_t,
                        end_time=end_t,
                        name=name,
                        category="景点",
                        activity="游览",
                        tips=["建议提前查询开放时间和门票政策", "降级模板生成，实地信息以官方为准"],
                    )
                )
            # 每日特殊需求提示
            daily_extra_tips: list[str] = []
            if request.with_kids:
                daily_extra_tips.append("带娃出行：请看好孩子，注意安全，备好水和零食")
            if request.with_elderly:
                daily_extra_tips.append("老人出行：量力而行，累了及时休息，随身携带常用药品")
            if request.has_disability:
                daily_extra_tips.append("无障碍提示：出行前确认景点无障碍设施开放情况")

            days.append(
                DraftDay(
                    day_number=i + 1,
                    day_theme=f"第{i + 1}天",
                    items=items,
                    daily_tips=[
                        "降级模板生成，建议核对开放时间和预约要求",
                        "当日景点间距较远时建议提前规划交通路线",
                    ] + daily_extra_tips,
                    lunch=DraftMeal(
                        name=f"{request.destination}特色午餐",
                        avg_price=float(request.restaurant_budget_per_meal),
                    ),
                    dinner=DraftMeal(
                        name=f"{request.destination}特色晚餐",
                        avg_price=float(request.restaurant_budget_per_meal),
                    ),
                    hotel=DraftHotel(
                        name=f"{request.destination}舒适酒店",
                        price=BUDGET_DAILY_BASE.get(
                            getattr(request.budget_level, "value", "standard"),
                            600.0,
                        )
                        * ACCOMMODATION_SHARE,
                    ),
                )
            )

        # 特殊需求说明
        special_notes: list[str] = []
        if request.with_kids:
            special_notes.append("已优先安排亲子友好、安全可控的景点，避免高强度徒步")
            special_notes.append("行程节奏舒缓，预留充足休息与用餐时间")
        if request.with_elderly:
            special_notes.append("已安排轻松、少步行的路线，每日景点数量适中")
            special_notes.append("优先选择有休息设施、平坦好走的景点")
        if request.has_disability:
            special_notes.append("已优先选择无障碍可达、台阶少、地面平缓的景点")
            special_notes.append("每日行程均考虑轮椅通行便利性")

        draft = DraftItinerary(
            trip_name=f"{request.destination}{total_days}日行程（降级）",
            days=days,
            trip_highlights=["基于攻略模板的兜底行程"],
            trip_tips=[
                "本方案为降级生成，景点名称和安排请以实地信息为准",
                "建议重新生成以获得更优规划",
                "【出行准备】出行前务必确认各景点最新开放时间和预约政策",
                "【交通出行】建议提前规划当日交通路线，预留通勤时间",
                "【安全须知】保管好个人财物，尤其在人流密集的景区",
            ],
            special_needs_notes=special_notes,
            recommended_foods=[],
        )
        if context:
            meta["fallback_context_chars"] = len(context)
        draft, warnings = self.validate_and_repair(draft, request)
        meta["validation_warnings"] = warnings
        trip = self.draft_to_trip_response(draft, request, meta=meta, started_at=started_at)
        return self.enrich_budget_and_summary(trip, request, draft)


# ---------------------------------------------------------------------------
# 兼容旧代码：tool_calls 规范化函数（保留供测试或外部代码兼容使用）
# ---------------------------------------------------------------------------

def _normalize_tool_calls(tool_calls: Any) -> list[dict]:
    """旧版 tool_calls 规范化函数；保留供测试兼容使用。新路径走 LangGraph ToolNode。"""
    normalized = []
    for i, tc in enumerate(tool_calls):
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            normalized.append(
                {
                    "id": tc.get("id") or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": fn.get("name") or "",
                        "arguments": fn.get("arguments")
                        if isinstance(fn.get("arguments"), str)
                        else json.dumps(fn.get("arguments") or {}, ensure_ascii=False),
                    },
                }
            )
            continue
        fn = getattr(tc, "function", None)
        args = getattr(fn, "arguments", "{}") if fn else "{}"
        if not isinstance(args, str):
            args = json.dumps(args or {}, ensure_ascii=False)
        normalized.append(
            {
                "id": getattr(tc, "id", None) or f"call_{i}",
                "type": "function",
                "function": {
                    "name": getattr(fn, "name", "") if fn else "",
                    "arguments": args,
                },
            }
        )
    return normalized


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

trip_planner_agent = TripPlannerAgent()
