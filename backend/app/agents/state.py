"""
智旅云图 - LangGraph 状态定义

主规划图（PlannerState）与单日编辑子图（EditDayState）共享的 TypedDict。
采用 LangGraph 推荐的 reducer 模式：messages 与 validation_warnings 使用 add 累加。
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Optional, TypedDict

from app.models.schemas import TripRequest, TripResponse


class PlannerState(TypedDict, total=False):
    """
    主规划图状态。

    - 输入字段：request / context / candidate_places / use_tools / allow_fallback
    - 中间字段：messages / rag_context / rag_chunks / raw_llm_output / draft
    - 输出字段：trip / meta / error
    """

    # --- 输入 ---
    request: TripRequest
    context: Optional[str]
    candidate_places: list[Any]
    use_tools: bool
    allow_fallback: bool

    # --- 中间产物 ---
    # LangGraph 消息累加器：ToolNode / 节点返回 {"messages": [...]} 时自动 append
    messages: Annotated[list, add]
    rag_context: str
    rag_chunks: list
    raw_llm_output: str
    draft: Any
    repair_attempts: int

    # 用于在节点间传递 LLM 单次调用的原始回复
    # （LangGraph 节点应尽量返回纯 dict，而非 BaseModel，以避免序列化坑）
    validation_warnings: Annotated[list[str], add]

    # --- 输出 ---
    trip: TripResponse
    meta: dict
    error: Optional[str]


class EditDayState(TypedDict, total=False):
    """
    单日编辑子图状态。

    与主规划图共享节点函数（prefetch_rag / llm_plan / parse_draft / validate_repair），
    仅在入参组装和结果合并上不同。
    """

    # --- 输入 ---
    base_trip: TripResponse
    day_number: int
    instruction: str
    request: TripRequest
    context: Optional[str]
    use_tools: bool
    allow_fallback: bool

    # --- 中间产物 ---
    messages: Annotated[list, add]
    rag_context: str
    raw_llm_output: str
    draft: Any
    repair_attempts: int
    validation_warnings: Annotated[list[str], add]

    # --- 输出 ---
    edited_day: Any
    meta: dict
    error: Optional[str]
