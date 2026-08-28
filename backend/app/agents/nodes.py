"""
智旅云图 - LangGraph 节点函数

每个节点是纯函数：输入 state dict → 输出 state dict 的 patch。
LangGraph 会自动 merge 这些 patch 到当前 state。

业务逻辑全部复用 trip_planner_agent.py 中已实现并通过测试的函数：
- build_user_prompt / SYSTEM_PROMPT / extract_json_object
- validate_and_repair / _sort_and_fix_times
- draft_to_trip_response / enrich_budget_and_summary / _fallback_plan
- _repair_json_with_llm

节点列表：
- prefetch_rag_node      预取 RAG 上下文（context 已传入则跳过）
- llm_plan_node          调 LLM（可能产出 tool_calls）
- rag_tool_node          由 LangGraph ToolNode 充当（不在本文件定义）
- parse_draft_node       LLM 输出 → DraftItinerary（失败则记录 retry）
- repair_json_node       LLM 修复 JSON（最多 1 次）
- validate_repair_node   校验 + 自动修复
- build_trip_node        Draft → TripResponse（占位坐标/地址）
- enrich_budget_node     预算估算 + 摘要补全
- fallback_node          兜底方案
- route_after_llm        条件边：根据是否有 tool_calls 决定走 ToolNode 还是 parse
- route_after_parse      条件边：根据是否需要修复决定走 repair 还是 validate
- route_final            条件边：根据是否允许 fallback 决定 END 还是 fallback
"""

from __future__ import annotations

import time
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from loguru import logger

from app.agents.llm_factory import build_json_llm, build_llm
from app.agents.rag_tool import rag_tool as default_rag_tool
from app.agents.state import EditDayState, PlannerState
from app.agents.trip_planner_agent import (
    DraftItinerary,
    PlannerError,
    PlannerParseError,
    SYSTEM_PROMPT,
    build_user_prompt,
    extract_json_object,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _now_meta(meta: Optional[dict]) -> dict:
    base = dict(meta or {})
    base.setdefault("tool_rounds", 0)
    base.setdefault("rag_degraded", False)
    base.setdefault("validation_warnings", [])
    base.setdefault("path", "llm")
    base.setdefault("needs_enrichment", True)
    return base


def _sanitize_messages_for_zhipu(messages: list) -> list:
    """
    智谱兼容端点会拒绝 assistant tool_calls 消息 content 为 null（错误码 1214）。

    langchain-openai 序列化时会把空 content 置为 null，而智谱要求字符串，
    导致带工具结果的第二轮调用返回 400 "messages 参数非法"。
    这里把空 content 的 tool_calls 消息补一个空格字符串以通过校验；
    不影响解析：parse_draft 只取最后一条 AIMessage，中间消息不参与。
    """
    sanitized = []
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            content = m.content
            is_empty = (
                content is None
                or (isinstance(content, str) and not content.strip())
                or (isinstance(content, list) and not content)
            )
            if is_empty:
                m = m.model_copy(update={"content": " "})
        sanitized.append(m)
    return sanitized


def _ensure_meta(state: dict) -> dict:
    """从 state 取 meta，缺省字段补齐。"""
    return _now_meta(state.get("meta", {}))


# ---------------------------------------------------------------------------
# 1. 预取 RAG 上下文
# ---------------------------------------------------------------------------

def prefetch_rag_node(state: PlannerState) -> dict:
    """
    若调用方未传 context，则用 rag_tool.search_for_trip 预取一次攻略上下文。

    设计意图：让"非 tool-call 路径"也能拿到 RAG 上下文，与原 plan() 行为一致。
    若 use_tools=True，则通常 context=None，由后续 LLM 通过 tool_calls 自行检索，
    此节点不预取以避免重复消耗 token。
    """
    request = state["request"]
    use_tools = state.get("use_tools", True)
    context = state.get("context")
    candidate_places = state.get("candidate_places")

    meta_patch: dict = {}

    # 已显式传入 context，直接复用
    if context and context.strip():
        return {"rag_context": context, "meta": {**_ensure_meta(state), **meta_patch}}

    # use_tools=True：交由 LLM 自行决定调工具，不预取
    if use_tools:
        return {"rag_context": "", "meta": {**_ensure_meta(state), **meta_patch}}

    # 动态城市 POI 路径：已有候选地点池，无需再查本地攻略库（珠海等非沉淀城市
    # 检索必然为空，会导致无谓的降级阶梯和 rerank 模型加载，浪费数十秒）
    if candidate_places:
        return {"rag_context": "", "meta": {**_ensure_meta(state), **meta_patch}}

    # use_tools=False 且 context 为空：预取一次
    rag = default_rag_tool
    try:
        result = rag.search_for_trip(request)
        ctx = getattr(result, "context_text", "") or ""
        degraded = bool(getattr(getattr(result, "stats", None), "degraded", False))
        meta_patch["rag_degraded"] = degraded
        return {"rag_context": ctx, "meta": {**_ensure_meta(state), **meta_patch}}
    except Exception as e:
        logger.warning(f"prefetch_rag 失败: {e}")
        meta_patch["rag_degraded"] = True
        return {"rag_context": "", "meta": {**_ensure_meta(state), **meta_patch}}


# ---------------------------------------------------------------------------
# 2. LLM 调用（plan 模式）
# ---------------------------------------------------------------------------

def llm_plan_node(state: PlannerState) -> dict:
    """
    调用 LLM 生成行程草案。可能返回 tool_calls（→ ToolNode → 回到本节点继续）。

    使用 LangChain 的 BaseChatModel.invoke(messages)；
    LangGraph 会在条件边根据 AIMessage.tool_calls 决定下一跳。
    """
    request = state["request"]
    rag_context = state.get("rag_context", "") or ""
    candidate_places = state.get("candidate_places")
    use_tools = state.get("use_tools", True)
    meta = _ensure_meta(state)

    user_prompt = build_user_prompt(
        request,
        context=rag_context or None,
        candidate_places=candidate_places,
    )

    # 构造消息：system + user（首轮写入 state，保证后续轮次消息以 system/user 开头）
    history = list(state.get("messages") or [])
    if history:
        # 已有多轮历史（含 system/user + tool 往返），直接续用
        prefix: list = []
        messages_for_llm = list(history)
    else:
        # 首轮：构造 system + user，并随 ai_msg 一起写回 state
        # （否则二轮调用只剩 [assistant, tool]，智谱报 1214 messages 参数非法）
        prefix = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        messages_for_llm = list(prefix)

    # 智谱 1214 兜底：空 content 的 assistant tool_calls 消息补空格
    messages_for_llm = _sanitize_messages_for_zhipu(messages_for_llm)

    llm = build_llm()
    if use_tools:
        # 把 LangChain 工具 bind 到 LLM，使其能在回复中产出 tool_calls
        from app.agents.tools import get_default_rag_tools
        llm = llm.bind_tools(get_default_rag_tools())

    try:
        ai_msg = llm.invoke(messages_for_llm)
    except Exception as e:
        logger.error(f"llm_plan_node 调用失败: {e}")
        meta["llm_error"] = str(e)
        return {"error": str(e), "meta": meta}

    # 累加 tool_rounds：每次回到本节点视作一轮
    if getattr(ai_msg, "tool_calls", None):
        meta["tool_rounds"] = int(meta.get("tool_rounds", 0)) + 1

    # 首轮 prefix（system+user）也要写回 state，供后续轮次复用
    return {"messages": prefix + [ai_msg], "meta": meta}


# ---------------------------------------------------------------------------
# 3. 解析草稿
# ---------------------------------------------------------------------------

def parse_draft_node(state: PlannerState) -> dict:
    """
    从 messages 末尾的 AIMessage.content 提取 JSON → DraftItinerary。

    失败时不立即降级：交给 route_after_parse 决定是否进 repair_json。
    """
    meta = _ensure_meta(state)
    messages = state.get("messages") or []
    if not messages:
        meta["parse_error"] = "messages 为空"
        return {"error": "messages 为空", "meta": meta, "repair_attempts": 0}

    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if last_ai is None or not (last_ai.content or "").strip():
        meta["parse_error"] = "LLM 未返回文本"
        return {"error": "LLM 未返回文本", "meta": meta, "repair_attempts": 0}

    raw_text = str(last_ai.content).strip()
    try:
        data = extract_json_object(raw_text)
        draft = DraftItinerary.model_validate(data)
        return {
            "raw_llm_output": raw_text,
            "draft": draft,
            "meta": meta,
            "repair_attempts": 0,
        }
    except (PlannerParseError, Exception) as e:
        # 记录原文 + 错误，让 route_after_parse 决定是否修复
        logger.warning(f"parse_draft 首次失败: {e}")
        meta["parse_error"] = str(e)
        return {
            "raw_llm_output": raw_text,
            "error": str(e),
            "meta": meta,
            "repair_attempts": int(state.get("repair_attempts", 0)),
        }


# ---------------------------------------------------------------------------
# 4. 修复 JSON
# ---------------------------------------------------------------------------

def repair_json_node(state: PlannerState) -> dict:
    """LLM 修复 JSON，仅重试 1 次。"""
    meta = _ensure_meta(state)
    raw_text = state.get("raw_llm_output", "") or ""
    error = meta.get("parse_error", "unknown")

    # 已修复过一次仍失败 → 放弃
    attempts = int(state.get("repair_attempts", 0))
    if attempts >= 1:
        return {"repair_attempts": attempts, "meta": meta}

    try:
        from app.agents.trip_planner_agent import TripPlannerAgent
        # 复用原 _repair_json_with_llm 逻辑（需要 client）
        agent = TripPlannerAgent.__new__(TripPlannerAgent)
        agent._auto_client = False
        agent._client = build_json_llm(temperature=0.0)
        agent.model = None  # build_json_llm 已绑定模型
        agent._rag_tool = default_rag_tool
        agent.max_tool_rounds = 0
        agent.temperature = 0.0
        agent.max_tokens = 4096

        fixed = agent._repair_json_with_llm(raw_text, error)
        if not fixed:
            meta["repair_failed"] = True
            return {"repair_attempts": attempts + 1, "meta": meta}

        data = extract_json_object(fixed)
        draft = DraftItinerary.model_validate(data)
        # 修复成功：清空 error
        meta.pop("parse_error", None)
        meta.pop("repair_failed", None)
        return {
            "draft": draft,
            "raw_llm_output": fixed,
            "repair_attempts": attempts + 1,
            "meta": meta,
            "error": None,
        }
    except Exception as e:
        logger.warning(f"repair_json 失败: {e}")
        meta["repair_failed"] = True
        return {"repair_attempts": attempts + 1, "meta": meta}


# ---------------------------------------------------------------------------
# 5. 校验与修复
# ---------------------------------------------------------------------------

def validate_repair_node(state: PlannerState) -> dict:
    """调用 validate_and_repair：对齐天数、裁剪景点、修时间。"""
    from app.agents.trip_planner_agent import TripPlannerAgent

    meta = _ensure_meta(state)
    draft = state.get("draft")
    request = state["request"]

    if draft is None:
        meta["validation_error"] = "draft 为空"
        return {"error": "draft 为空", "meta": meta}

    # 借用 TripPlannerAgent 的实例方法（避免重写逻辑）
    agent = TripPlannerAgent.__new__(TripPlannerAgent)
    agent._rag_tool = default_rag_tool
    agent._auto_client = False
    agent._client = None
    agent.model = "graph"
    agent.max_tool_rounds = 0
    agent.temperature = 0.0
    agent.max_tokens = 0

    try:
        fixed_draft, warnings = agent.validate_and_repair(draft, request)
        meta["validation_warnings"] = list(warnings)
        return {"draft": fixed_draft, "meta": meta, "error": None}
    except Exception as e:
        logger.error(f"validate_repair 失败: {e}")
        meta["validation_error"] = str(e)
        return {"error": str(e), "meta": meta}


# ---------------------------------------------------------------------------
# 6. Draft → TripResponse
# ---------------------------------------------------------------------------

def build_trip_node(state: PlannerState) -> dict:
    """draft_to_trip_response：占位坐标/地址，留给后续 enrichment。"""
    from app.agents.trip_planner_agent import TripPlannerAgent

    meta = _ensure_meta(state)
    draft = state.get("draft")
    request = state["request"]

    if draft is None:
        return {"error": "draft 为空", "meta": meta}

    agent = TripPlannerAgent.__new__(TripPlannerAgent)
    agent._rag_tool = default_rag_tool
    agent._auto_client = False
    agent._client = None
    agent.model = meta.get("model_used", "graph")
    agent.max_tool_rounds = 0
    agent.temperature = 0.0
    agent.max_tokens = 0

    try:
        trip = agent.draft_to_trip_response(draft, request, meta=meta)
        return {"trip": trip, "meta": meta}
    except Exception as e:
        logger.error(f"build_trip 失败: {e}")
        return {"error": str(e), "meta": meta}


# ---------------------------------------------------------------------------
# 7. 预算与摘要
# ---------------------------------------------------------------------------

def enrich_budget_node(state: PlannerState) -> dict:
    """enrich_budget_and_summary：预算估算 + 摘要补全。"""
    from app.agents.trip_planner_agent import TripPlannerAgent

    meta = _ensure_meta(state)
    trip = state.get("trip")
    request = state["request"]
    draft = state.get("draft")

    if trip is None:
        return {"error": "trip 为空", "meta": meta}

    agent = TripPlannerAgent.__new__(TripPlannerAgent)
    agent._rag_tool = default_rag_tool
    agent._auto_client = False
    agent._client = None
    agent.model = "graph"
    agent.max_tool_rounds = 0
    agent.temperature = 0.0
    agent.max_tokens = 0

    try:
        enriched = agent.enrich_budget_and_summary(trip, request, draft)
        meta["needs_enrichment"] = False
        # enrich_budget_and_summary 内部会用 trip.metadata 覆盖，
        # 这里用 final meta 再覆盖一次，确保 needs_enrichment=False 生效
        final_meta = {**(enriched.metadata or {}), **meta}
        enriched = enriched.model_copy(update={"metadata": final_meta})
        return {"trip": enriched, "meta": final_meta}
    except Exception as e:
        logger.error(f"enrich_budget 失败: {e}")
        # 预算失败不阻断，仍返回原 trip
        meta["enrich_error"] = str(e)
        return {"trip": trip, "meta": meta}


# ---------------------------------------------------------------------------
# 8. 兜底方案
# ---------------------------------------------------------------------------

def fallback_node(state: PlannerState) -> dict:
    """走原 _fallback_plan：RAG 片段 + 默认时段模板拼装。"""
    from app.agents.trip_planner_agent import TripPlannerAgent

    meta = _ensure_meta(state)
    meta["path"] = "fallback"
    meta["fallback_reason"] = state.get("error", "unknown")
    request = state["request"]

    # 不允许 fallback 时，返回 error 让上层 plan() 抛错
    if not state.get("allow_fallback", True):
        meta["fallback_blocked"] = True
        return {"error": meta["fallback_reason"], "meta": meta}

    agent = TripPlannerAgent.__new__(TripPlannerAgent)
    agent._rag_tool = default_rag_tool
    agent._auto_client = False
    agent._client = None
    agent.model = "graph-fallback"
    agent.max_tool_rounds = 0
    agent.temperature = 0.0
    agent.max_tokens = 0

    try:
        trip = agent._fallback_plan(request, meta=meta, started_at=time.time())
        return {"trip": trip, "meta": meta, "error": None}
    except Exception as e:
        logger.error(f"fallback 也失败: {e}")
        meta["fallback_failed"] = True
        return {"error": str(e), "meta": meta}


# ---------------------------------------------------------------------------
# 条件路由函数
# ---------------------------------------------------------------------------

def route_after_llm(state: PlannerState) -> str:
    """
    LLM 调用后：
    - 有 tool_calls → "tools"（进 ToolNode）
    - 无 tool_calls → "parse"（进 parse_draft）
    - 有 error → "fallback"
    """
    if state.get("error"):
        return "fallback"

    messages = state.get("messages") or []
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if last_ai and getattr(last_ai, "tool_calls", None):
        # 防止无限循环：超过 max_tool_rounds 则强制进 parse
        meta = state.get("meta", {})
        max_rounds = 4
        if int(meta.get("tool_rounds", 0)) >= max_rounds:
            return "parse"
        return "tools"
    return "parse"


def route_after_parse(state: PlannerState) -> str:
    """
    解析后：
    - 有 draft → "validate"
    - 无 draft 且未修复过 → "repair"
    - 无 draft 且已修复过 → "fallback" 或 "fallback"
    """
    if state.get("draft") is not None:
        return "validate"
    attempts = int(state.get("repair_attempts", 0))
    if attempts >= 1:
        return "fallback"
    return "repair"


def route_after_validate(state: PlannerState) -> str:
    """
    校验后：
    - 无 error → "build_trip"
    - 有 error 且 allow_fallback → "fallback"
    - 有 error 且不允许 fallback → "build_trip"（让下游也尝试用原 draft）
    """
    if not state.get("error"):
        return "build_trip"
    if state.get("allow_fallback", True):
        return "fallback"
    return "build_trip"


def route_after_build(state: PlannerState) -> str:
    """build_trip 后无 error 则进 enrich；有 error 走 fallback。"""
    if state.get("error") and state.get("allow_fallback", True):
        return "fallback"
    return "enrich"


# ---------------------------------------------------------------------------
# Edit Day 节点
# ---------------------------------------------------------------------------

def build_edit_day_input_node(state: EditDayState) -> dict:
    """
    把 base_trip + day_number + instruction 组装为单日编辑 prompt。
    输出到 messages，复用主图的 llm_plan_node。
    """
    from app.agents.trip_planner_agent import TripPlannerAgent

    base_trip = state["base_trip"]
    day_number = state["day_number"]
    instruction = state["instruction"]
    request = state.get("request") or TripPlannerAgent._derive_request_from_trip(base_trip)
    context = state.get("context")

    target = base_trip.days[day_number - 1]
    other_names = [
        it.place.name
        for d in base_trip.days
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
        f"当前该日：{__import__('json').dumps(day_dump, ensure_ascii=False)}"
    )
    user_prompt = build_user_prompt(request, context=context, extra_instruction=extra)
    user_prompt += (
        "\n请只输出包含单日的 JSON："
        '{"days":[{...单日...}],"trip_highlights":[],"trip_tips":[]}'
    )

    return {
        "request": request,
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ],
    }


def merge_edit_day_node(state: EditDayState) -> dict:
    """把单日结果合并回原 base_trip。"""
    from datetime import datetime
    from app.agents.trip_planner_agent import TripPlannerAgent

    base_trip = state["base_trip"]
    day_number = state["day_number"]
    request = state["request"]
    draft = state.get("draft")
    meta = _ensure_meta(state)

    if draft is None or not draft.days:
        meta["edit_failed"] = True
        return {"meta": meta}

    target = base_trip.days[day_number - 1]
    edited = next((d for d in draft.days if d.day_number == day_number), draft.days[0])
    edited.day_number = day_number
    edited.itinerary_date = target.itinerary_date

    mini = DraftItinerary(
        trip_name=base_trip.trip_name,
        days=[edited],
        trip_highlights=draft.trip_highlights or base_trip.trip_highlights,
        trip_tips=draft.trip_tips or base_trip.trip_tips,
        recommended_foods=draft.recommended_foods or base_trip.recommended_foods,
    )

    one_day_req = request.model_copy(
        update={
            "start_date": target.itinerary_date,
            "end_date": target.itinerary_date,
        }
    )

    agent = TripPlannerAgent.__new__(TripPlannerAgent)
    agent._rag_tool = default_rag_tool
    agent._auto_client = False
    agent._client = None
    agent.model = "graph-edit"
    agent.max_tool_rounds = 0
    agent.temperature = 0.0
    agent.max_tokens = 0

    try:
        mini, warnings = agent.validate_and_repair(mini, one_day_req)
        meta["validation_warnings"] = list(warnings)
        new_day_trip = agent.draft_to_trip_response(
            mini, one_day_req, meta=meta, started_at=time.time()
        )
        new_day = new_day_trip.days[0]
        new_day.day_number = day_number
        new_day.itinerary_date = target.itinerary_date

        merged_days = list(base_trip.days)
        merged_days[day_number - 1] = new_day
        updated = base_trip.model_copy(
            update={
                "days": merged_days,
                "trip_highlights": mini.trip_highlights or base_trip.trip_highlights,
                "trip_tips": mini.trip_tips or base_trip.trip_tips,
                "generated_at": datetime.now(),
                "metadata": {**(base_trip.metadata or {}), **meta},
            }
        )
        enriched = agent.enrich_budget_and_summary(updated, request, mini)
        meta["needs_enrichment"] = False
        return {"edited_day": enriched, "meta": meta, "error": None}
    except Exception as e:
        logger.error(f"merge_edit_day 失败: {e}")
        meta["edit_failed"] = True
        meta["edit_error"] = str(e)
        return {"error": str(e), "meta": meta}
