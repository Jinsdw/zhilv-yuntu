"""
山海拾光（智旅云图） - 方案B 逐天生成状态定义（13.1 架构决策）

方案B（真·逐天生成）采用「纯 Python 循环编排」：每次 LLM 调用只生成一天，
一天完成（草案 + 地图/天气补全）后立即推 `day` 事件供前端展示，再生成下一天。

架构决策（REPLICATION_TASKS.md 13.1，2026-10-13 定案）：
- 13.1.2 状态：本模块 DayGenState，与主图 PlannerState 分离，避免污染 batch 模式
- 13.1.4 执行形态：纯 Python 循环（for day_no in 1..N）直接复用现有函数
  （build_pool_sync / rag_tool.search_for_trip / extract_json_object /
   DraftDay.model_validate / validate_and_repair / _draft_day_to_model /
   _enrich_map / _enrich_weather），不再引入 LangGraph 单日子图，
  避免图状态序列化复杂度；主图 planner_graph 保留给 TRIP_GEN_MODE=batch。
- 13.1.5 SSE 阶段语义：
    status(day_generating, day_number, total_days)   # 第 N 天生成中
    day(state=draft, day_number, theme, places, day_summary)  # 草案版
    day(state=enriched, day_number, day=ItineraryDay)         # 补全版
    final(trip)                                             # 整份收尾
  poi / error / 缓存命中语义沿用 12.2 SSE 基线不变。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional, TypedDict

from app.models.schemas import ItineraryDay, TripRequest


class DayGenState(TypedDict, total=False):
    """方案B 按天生成状态（13.1.2）。

    纯 Python 循环编排下为普通 dict 即可（无需 LangGraph reducer）；
    跨天记忆（used_* / day_summaries / accumulated_budget）在循环内更新，
    供下一天 build_day_prompt 渲染「前 N-1 天紧凑摘要 + 防重复指令」。
    """

    # --- 循环不变量（一次构建，逐天复用） ---
    request: TripRequest                # 归一化后的请求
    total_days: int                     # (end_date - start_date).days + 1
    day_dates: list[date]               # 每日日期（按下标推进）
    global_constraints: dict[str, Any]  # 预算等级/每日预算/风格/偏好/排除/特殊需求/室内外
    candidate_sections: dict[str, Any]  # B级：scenic/food/hotel + clusters（build_pool_sync 产物）
    rag_context: str                    # A级：rag_tool.search_for_trip 一次检索结果
    candidate_index: dict[str, Any]     # place_id → 候选 dict（回填真实坐标/地址/图片）
    district_clusters: dict[str, list[str]]  # 区域分组：区域名 → place_id 列表
    food_candidates: list[dict]         # 餐饮候选（缺餐时回补）
    hotel_candidates: list[dict]        # 住宿候选（缺酒店时回补）

    # --- 跨天记忆（循环内更新，供下一天 prompt） ---
    used_place_ids: list[str]           # 景点全局去重（place_id）
    used_names: list[str]               # 名称级去重兜底（place_id 为空时）
    prev_district: Optional[str]        # 前日区域（区域衔接偏好）
    prev_hotel: Optional[str]           # 前日酒店名（酒店连续性）
    day_summaries: list[dict]           # day1..N-1 紧凑摘要（date/theme/places/district/hotel/meals/cost）
    accumulated_budget: float           # 累计已排预算（每日预算占比校验）

    # --- 当日执行 ---
    day_number: int                     # 当前第几天（1-based）
    day_date: date                      # 当日日期
    raw_llm_output: str                 # 当日 LLM 原始输出
    draft_day: Any                      # 当日草案 DraftDay（含 day_summary）
    repair_attempts: int                # 当日 JSON 修复尝试次数（上限 1）
    fallback_used: bool                 # 当日是否走了单日模板兜底
    day_warnings: list[str]             # 当日非阻断警告

    # --- 产出 ---
    day: Optional[ItineraryDay]         # 补全后的当日模型（地图/天气已填）
    meta: dict                          # token/耗时/日志（含每日 LLM 调用记录）
    error: Optional[str]                # 当日致命错误（重试+兜底后仍失败时置位）
