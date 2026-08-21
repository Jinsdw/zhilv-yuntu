"""
智旅云图 - 行程规划 Agent

将 TripRequest 转为可校验的 TripResponse 草案。
检索走 rag_tool；真实坐标/路线/天气留给后续编排。

功能模块：
- 5.2.1 Agent 骨架：类、配置、异常、plan() 入口
- 5.2.2 Prompt：system / user 模板
- 5.2.3 Tool 循环：挂载 RAG + function calling
- 5.2.4 结构化解析：LLM JSON → Draft → TripResponse
- 5.2.5 约束校验与自动修复
- 5.2.6 预算估算与摘要补全
- 5.2.7 智能编辑 edit_day + 降级路径
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
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_MAX_TOOL_ROUNDS = 4
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 4096
PLACEHOLDER_ADDRESS = "待地图服务补全"
PLACEHOLDER_COORD = Coordinate(latitude=0.0, longitude=0.0)

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
# 5.2.4 草案 Schema（比 TripResponse 松）
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
    cuisine_type: str = Field(default="本地菜")
    avg_price: float = Field(default=50.0, ge=0)
    address: str = Field(default=PLACEHOLDER_ADDRESS)


class DraftHotel(BaseModel):
    name: str = Field(..., min_length=1)
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
    recommended_foods: list[str] = Field(default_factory=list)
    recommended_shopping: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5.2.2 Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是「智旅云图」行程规划助手。根据用户约束与攻略资料，生成可执行的多日行程。

硬性规则：
1. 优先使用检索工具 search_travel_guides 获取本地攻略；无资料时不要编造冷门景点。
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
          "category": "景点|餐饮|住宿|其他",
          "activity": "简短活动",
          "activity_detail": "可选详情",
          "duration_minutes": 120,
          "tips": ["提示"],
          "ticket_price": 0
        }
      ],
      "daily_tips": [],
      "lunch": {"name": "店名", "cuisine_type": "菜系", "avg_price": 80},
      "dinner": {"name": "店名", "cuisine_type": "菜系", "avg_price": 100},
      "hotel": {"name": "酒店名", "hotel_type": "舒适型", "price": 350}
    }
  ],
  "trip_highlights": [],
  "trip_tips": [],
  "recommended_foods": [],
  "recommended_shopping": []
}
4. days 数量必须等于用户行程天数；每日景点数量不超过 max_places_per_day。
5. 遵守偏好关键词与排除关键词；带儿童/老人时优先轻松、少步行的安排。
6. 时间按当日从早到晚排列，避免严重重叠。
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
    extra_instruction: Optional[str] = None,
) -> str:
    """5.2.2 将 TripRequest 渲染为 user 消息。"""
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
        flags.append("有行动不便人员")
    if flags:
        lines.append("特殊需求：" + "、".join(flags))
    lines.append(
        f"室内景点：{'包含' if request.include_indoor else '尽量不含'}；"
        f"室外景点：{'包含' if request.include_outdoor else '尽量不含'}"
    )
    if request.preferred_keywords:
        lines.append("偏好关键词：" + "、".join(request.preferred_keywords))
    if request.excluded_keywords:
        lines.append("排除关键词：" + "、".join(request.excluded_keywords))
    if candidate_places:
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
# TripPlannerAgent
# ---------------------------------------------------------------------------

class TripPlannerAgent:
    """
    行程规划 Agent。

    - plan(): TripRequest → TripResponse
    - edit_day(): 单日智能调整
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
        self._rag_tool = rag_tool
        # client=_UNSET → 懒加载；client=None → 明确禁用 LLM
        self._auto_client = client is _UNSET
        self._client = None if client is _UNSET else client
        self.model = model or settings.ZHIPU_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_tool_rounds = max(1, int(max_tool_rounds))

    # ---------- 依赖 ----------

    @property
    def rag_tool(self) -> Any:
        if self._rag_tool is None:
            from app.agents.rag_tool import rag_tool as default_rag_tool

            self._rag_tool = default_rag_tool
        return self._rag_tool

    @rag_tool.setter
    def rag_tool(self, value: Any) -> None:
        self._rag_tool = value

    def _get_client(self) -> Any:
        if not self._auto_client:
            return self._client
        if self._client is not None:
            return self._client
        try:
            from zai import ZhipuAiClient

            self._client = ZhipuAiClient(api_key=settings.ZHIPU_API_KEY)
            return self._client
        except ImportError:
            logger.warning("zai 未安装，行程规划将无法调用真实 LLM")
            return None

    # ---------- 5.2.1 入口 ----------

    def plan(
        self,
        request: TripRequest,
        *,
        context: Optional[str] = None,
        candidate_places: Optional[list[Any]] = None,
        use_tools: bool = True,
        allow_fallback: bool = True,
    ) -> TripResponse:
        """生成行程草案。"""
        start = time.time()
        meta: dict[str, Any] = {
            "tool_rounds": 0,
            "rag_degraded": False,
            "validation_warnings": [],
            "path": "llm",
            "needs_enrichment": True,
        }
        rag_context = context
        if rag_context is None and not use_tools:
            rag_context = self._prefetch_context(request, meta)

        try:
            raw_text, meta = self._run_llm_plan(
                request,
                context=rag_context,
                candidate_places=candidate_places,
                use_tools=use_tools,
                meta=meta,
            )
            draft = self._parse_draft(raw_text, request, meta)
            draft, warnings = self.validate_and_repair(draft, request)
            meta["validation_warnings"] = warnings
            trip = self.draft_to_trip_response(draft, request, meta=meta, started_at=start)
            return self.enrich_budget_and_summary(trip, request, draft)
        except Exception as e:
            logger.error(f"行程规划 LLM 路径失败: {e}")
            if not allow_fallback:
                raise
            meta["path"] = "fallback"
            meta["fallback_reason"] = str(e)
            return self._fallback_plan(request, meta=meta, started_at=start)

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
        """5.2.7 仅调整指定日，合并回原行程。"""
        start = time.time()
        if day_number < 1 or day_number > len(trip.days):
            raise PlannerValidationError(f"无效 day_number: {day_number}")

        req = request or TripRequest(
            destination=trip.destination,
            start_date=trip.start_date,
            end_date=trip.end_date,
            travelers=1,
        )
        target = trip.days[day_number - 1]
        other_names = [
            it.place.name
            for d in trip.days
            if d.day_number != day_number
            for it in d.items
        ]
        day_dump = {
            "day_number": target.day_number,
            "day_theme": target.day_theme,
            "items": [
                {
                    "start_time": it.start_time,
                    "end_time": it.end_time,
                    "name": it.place.name,
                    "category": it.place.category,
                    "activity": it.activity,
                    "tips": it.tips,
                }
                for it in target.items
            ],
        }
        extra = (
            f"只改写第 {day_number} 天。要求：{instruction}。"
            f"其他日地点勿重复占用：{', '.join(other_names[:20])}。"
            f"当前该日：{json.dumps(day_dump, ensure_ascii=False)}"
        )
        meta: dict[str, Any] = {
            "tool_rounds": 0,
            "rag_degraded": False,
            "validation_warnings": [],
            "path": "edit_day",
            "needs_enrichment": True,
            "edited_day": day_number,
        }
        try:
            user = build_user_prompt(
                req,
                context=context,
                extra_instruction=extra,
            )
            user += (
                "\n请只输出包含单日的 JSON："
                '{"days":[{...单日...}],"trip_highlights":[],"trip_tips":[]}'
            )
            raw_text, meta = self._chat_with_tools(
                user_content=user,
                use_tools=bool(context is None),
                meta=meta,
                force_json_final=True,
            )
            data = extract_json_object(raw_text)
            draft = DraftItinerary.model_validate(data)
            if not draft.days:
                raise PlannerParseError("编辑结果缺少 days")
            # 取 day_number 匹配或第一天
            edited = next(
                (d for d in draft.days if d.day_number == day_number),
                draft.days[0],
            )
            edited.day_number = day_number
            edited.itinerary_date = target.itinerary_date
            mini = DraftItinerary(
                trip_name=trip.trip_name,
                days=[edited],
                trip_highlights=draft.trip_highlights or trip.trip_highlights,
                trip_tips=draft.trip_tips or trip.trip_tips,
                recommended_foods=draft.recommended_foods or trip.recommended_foods,
            )
            # 用「单日请求」做裁剪校验
            one_day_req = req.model_copy(
                update={
                    "start_date": target.itinerary_date,
                    "end_date": target.itinerary_date,
                }
            )
            mini, warnings = self.validate_and_repair(mini, one_day_req)
            meta["validation_warnings"] = warnings
            new_day_trip = self.draft_to_trip_response(
                mini, one_day_req, meta=meta, started_at=start
            )
            new_day = new_day_trip.days[0]
            new_day.day_number = day_number
            new_day.itinerary_date = target.itinerary_date

            merged_days = list(trip.days)
            merged_days[day_number - 1] = new_day
            updated = trip.model_copy(
                update={
                    "days": merged_days,
                    "trip_highlights": mini.trip_highlights or trip.trip_highlights,
                    "trip_tips": mini.trip_tips or trip.trip_tips,
                    "generated_at": datetime.now(),
                    "generation_time": round(time.time() - start, 3),
                    "model_used": self.model,
                    "metadata": {**(trip.metadata or {}), **meta},
                }
            )
            return self.enrich_budget_and_summary(updated, req, mini)
        except Exception as e:
            logger.error(f"edit_day 失败: {e}")
            if not allow_fallback:
                raise
            # 失败则原样返回并记录
            return trip.model_copy(
                update={
                    "metadata": {
                        **(trip.metadata or {}),
                        "edit_failed": True,
                        "edit_error": str(e),
                    }
                }
            )

    # ---------- LLM / Tool ----------

    def _prefetch_context(self, request: TripRequest, meta: dict) -> str:
        try:
            result = self.rag_tool.search_for_trip(request)
            meta["rag_degraded"] = bool(
                getattr(getattr(result, "stats", None), "degraded", False)
            )
            return getattr(result, "context_text", "") or ""
        except Exception as e:
            logger.warning(f"预取 RAG 失败: {e}")
            return ""

    def _run_llm_plan(
        self,
        request: TripRequest,
        *,
        context: Optional[str],
        candidate_places: Optional[list[Any]],
        use_tools: bool,
        meta: dict,
    ) -> tuple[str, dict]:
        user = build_user_prompt(
            request,
            context=context,
            candidate_places=candidate_places,
        )
        return self._chat_with_tools(
            user_content=user,
            use_tools=use_tools and not (context and context.strip()),
            meta=meta,
            force_json_final=True,
        )

    def _chat_with_tools(
        self,
        *,
        user_content: str,
        use_tools: bool,
        meta: dict,
        force_json_final: bool = True,
    ) -> tuple[str, dict]:
        """5.2.3 Tool-Call 循环。"""
        client = self._get_client()
        if client is None:
            raise PlannerError("LLM 客户端不可用")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        tools = self.rag_tool.as_openai_tools() if use_tools else None
        rounds = 0

        while True:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if tools and rounds < self.max_tool_rounds:
                kwargs["tools"] = tools
            elif force_json_final:
                # 最终轮：不再给工具
                pass

            response = client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []

            # 兼容 dict / 对象
            content = getattr(message, "content", None)
            if content is None and isinstance(message, dict):
                content = message.get("content")
                tool_calls = message.get("tool_calls") or tool_calls

            if tool_calls and tools and rounds < self.max_tool_rounds:
                rounds += 1
                meta["tool_rounds"] = rounds
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": content or "",
                    "tool_calls": self._normalize_tool_calls(tool_calls),
                }
                messages.append(assistant_msg)
                for tc in assistant_msg["tool_calls"]:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or ""
                    arguments = fn.get("arguments") or "{}"
                    payload = self.rag_tool.execute(name, arguments)
                    try:
                        parsed = json.loads(payload)
                        if parsed.get("stats", {}).get("degraded"):
                            meta["rag_degraded"] = True
                        ctx = parsed.get("context_text") or ""
                        if ctx:
                            meta.setdefault("last_rag_context", ctx)
                    except Exception:
                        pass
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id") or f"call_{rounds}",
                            "content": payload,
                        }
                    )
                continue

            text = (content or "").strip()
            if not text:
                raise PlannerParseError("模型未返回行程文本")
            meta["tool_rounds"] = rounds
            return text, meta

    @staticmethod
    def _normalize_tool_calls(tool_calls: Any) -> list[dict]:
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

    # ---------- 5.2.4 解析 ----------

    def _parse_draft(
        self,
        raw_text: str,
        request: TripRequest,
        meta: dict,
    ) -> DraftItinerary:
        try:
            data = extract_json_object(raw_text)
            return DraftItinerary.model_validate(data)
        except (PlannerParseError, ValidationError) as first_err:
            logger.warning(f"首次解析失败，尝试修复: {first_err}")
            fixed = self._repair_json_with_llm(raw_text, str(first_err))
            if not fixed:
                raise PlannerParseError(str(first_err)) from first_err
            data = extract_json_object(fixed)
            return DraftItinerary.model_validate(data)

    def _repair_json_with_llm(self, raw_text: str, error: str) -> Optional[str]:
        client = self._get_client()
        if client is None:
            return None
        try:
            resp = client.chat.completions.create(
                model=self.model,
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
    ) -> TripResponse:
        """草案 → TripResponse（坐标/地址占位，供后续 enrichment）。"""
        total_days = (request.end_date - request.start_date).days + 1
        days: list[ItineraryDay] = []
        for i in range(total_days):
            d = request.start_date + timedelta(days=i)
            src = next((x for x in draft.days if x.day_number == i + 1), None)
            if src is None and i < len(draft.days):
                src = draft.days[i]
            if src is None:
                src = DraftDay(day_number=i + 1, items=[])
            days.append(self._draft_day_to_model(src, day_number=i + 1, day_date=d))

        trip_name = draft.trip_name or f"{request.destination}{total_days}日游"
        elapsed = round(time.time() - started_at, 3) if started_at else 0.0
        return TripResponse(
            trip_id=str(uuid.uuid4()),
            destination=request.destination,
            trip_name=trip_name,
            start_date=request.start_date,
            end_date=request.end_date,
            total_days=total_days,
            days=days,
            budget=BudgetInfo(
                total_budget=0,
                daily_avg_budget=0,
                budget_per_person=0,
            ),
            trip_highlights=list(draft.trip_highlights or []),
            trip_tips=list(draft.trip_tips or []),
            recommended_foods=list(draft.recommended_foods or []),
            recommended_shopping=list(draft.recommended_shopping or []),
            generated_at=datetime.now(),
            generation_time=elapsed,
            model_used=self.model,
            metadata=meta or {"needs_enrichment": True},
        )

    def _draft_day_to_model(
        self, src: DraftDay, *, day_number: int, day_date: date
    ) -> ItineraryDay:
        items: list[ItineraryItem] = []
        for idx, it in enumerate(src.items):
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
                    ticket_price=it.ticket_price,
                    tips=list(it.tips or []),
                )
            )

        def meal(m: Optional[DraftMeal]) -> Optional[RestaurantInfo]:
            if not m:
                return None
            return RestaurantInfo(
                place_id=f"meal-{abs(hash(m.name)) % 100000}",
                name=m.name,
                coordinate=PLACEHOLDER_COORD,
                address=m.address or PLACEHOLDER_ADDRESS,
                cuisine_type=m.cuisine_type or "本地菜",
                price_range=f"{int(m.avg_price)}元左右",
                avg_price=m.avg_price,
            )

        hotel = None
        if src.hotel:
            hotel = HotelInfo(
                place_id=f"hotel-{abs(hash(src.hotel.name)) % 100000}",
                name=src.hotel.name,
                coordinate=PLACEHOLDER_COORD,
                address=src.hotel.address or PLACEHOLDER_ADDRESS,
                hotel_type=src.hotel.hotel_type or "舒适型",
                price=src.hotel.price,
                price_range=f"{int(src.hotel.price)}元/晚",
            )

        duration = sum(it.place.suggested_duration for it in items)
        return ItineraryDay(
            day_number=day_number,
            itinerary_date=day_date,
            day_theme=src.day_theme,
            items=items,
            total_places=len(items),
            total_duration=duration,
            daily_tips=list(src.daily_tips or []),
            breakfast=meal(src.breakfast),
            lunch=meal(src.lunch),
            dinner=meal(src.dinner),
            hotel=hotel,
        )

    # ---------- 5.2.5 校验 ----------

    def validate_and_repair(
        self, draft: DraftItinerary, request: TripRequest
    ) -> tuple[DraftItinerary, list[str]]:
        warnings: list[str] = []
        total_days = (request.end_date - request.start_date).days + 1
        excluded = [str(x).strip() for x in (request.excluded_keywords or []) if str(x).strip()]
        max_places = request.max_places_per_day

        # 对齐天数
        by_num: dict[int, DraftDay] = {}
        for d in draft.days:
            by_num[d.day_number] = d
        new_days: list[DraftDay] = []
        for i in range(1, total_days + 1):
            day = by_num.get(i)
            if day is None and draft.days:
                # 回退按顺序取
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

            # 裁剪景点数
            if len(day.items) > max_places:
                warnings.append(
                    f"第{i}天景点 {len(day.items)}>{max_places}，已裁剪"
                )
                day.items = day.items[:max_places]

            # 时间排序与简单去重叠
            day.items = self._sort_and_fix_times(day.items, warnings, day_number=i)
            new_days.append(day)

        if len(draft.days) != total_days:
            warnings.append(f"天数已对齐为 {total_days}")

        draft = draft.model_copy(update={"days": new_days})

        # 硬失败：全部日无任何安排且无餐饮（通常是空模型）
        if total_days > 0 and all(not d.items for d in draft.days):
            # 不在这里抛错，留给 fallback；但给出 warning
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

    # ---------- 5.2.6 预算与摘要 ----------

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
        # 若完全没有酒店信息，住宿已按日累加
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
            tips = ["出行前确认开放时间与预约要求", "合理安排体力，预留交通缓冲"]
        if not foods:
            for d in trip.days:
                for meal in (d.lunch, d.dinner):
                    if meal and meal.name not in foods:
                        foods.append(meal.name)
                if len(foods) >= 5:
                    break

        style = _style_cn(request.travel_style)
        trip_name = trip.trip_name or f"{request.destination}{total_days}日{style}行程"

        return trip.model_copy(
            update={
                "trip_name": trip_name,
                "budget": budget,
                "trip_highlights": highlights,
                "trip_tips": tips,
                "recommended_foods": foods[:8],
                "metadata": {
                    **(trip.metadata or {}),
                    "budget_level": str(level),
                },
            }
        )

    # ---------- 5.2.7 降级 ----------

    def _fallback_plan(
        self,
        request: TripRequest,
        *,
        meta: dict,
        started_at: float,
    ) -> TripResponse:
        """RAG 片段 + 默认时段模板拼装。"""
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
                # subsection / 从内容抽短名
                section = getattr(ch, "section", None) or ""
                content = getattr(ch, "content", "") or ""
                for cand in (section,):
                    if cand and 1 < len(cand) <= 20 and cand not in place_names:
                        place_names.append(cand)
                # 简单从「【】」或书名号取名
                for m in re.finditer(r"[「【]([^」】]{2,12})[」】]", content):
                    name = m.group(1)
                    if name not in place_names:
                        place_names.append(name)
                if len(place_names) >= 20:
                    break
        except Exception as e:
            logger.warning(f"降级预取失败: {e}")

        if not place_names:
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
                        tips=["降级模板生成，建议核对开放时间"],
                    )
                )
            days.append(
                DraftDay(
                    day_number=i + 1,
                    day_theme=f"第{i + 1}天",
                    items=items,
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

        draft = DraftItinerary(
            trip_name=f"{request.destination}{total_days}日行程（降级）",
            days=days,
            trip_highlights=["基于攻略模板的兜底行程"],
            trip_tips=["本方案为降级生成，请以实地信息为准", "建议重新生成以获得更优规划"],
            recommended_foods=[],
        )
        if context:
            meta["fallback_context_chars"] = len(context)
        draft, warnings = self.validate_and_repair(draft, request)
        meta["validation_warnings"] = warnings
        trip = self.draft_to_trip_response(draft, request, meta=meta, started_at=started_at)
        return self.enrich_budget_and_summary(trip, request, draft)


# 模块级单例
trip_planner_agent = TripPlannerAgent()
