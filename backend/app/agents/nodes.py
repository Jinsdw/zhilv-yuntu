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

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from app.agents.llm_factory import (
    build_json_llm,
    build_llm,
    get_llm_thinking_config,
    log_llm_invocation,
    log_llm_reasoning_from_message,
    log_llm_request,
)
from app.agents.rag_tool import rag_tool as default_rag_tool
from app.agents.state import PlannerState
from app.agents.trip_planner_agent import (
    DraftItinerary,
    PlannerParseError,
    SYSTEM_PROMPT,
    analyze_draft_missing,
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

    # 动态城市 POI 路径：已有候选地点池或分类候选池，无需再查本地攻略库
    candidate_sections = state.get("candidate_sections")
    if candidate_places or candidate_sections:
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
    candidate_sections = state.get("candidate_sections")
    use_tools = state.get("use_tools", True)
    meta = _ensure_meta(state)

    user_prompt = build_user_prompt(
        request,
        context=rag_context or None,
        candidate_places=candidate_places,
        candidate_sections=candidate_sections,
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

    # 底层走流式（SSE）：invoke 仍返回完整消息，同时能捕获流式 reasoning_content 写入日志
    llm = build_llm(streaming=True)
    tools = None
    if use_tools:
        # 把 LangChain 工具 bind 到 LLM，使其能在回复中产出 tool_calls
        from app.agents.tools import get_default_rag_tools
        tools = get_default_rag_tools()
        llm = llm.bind_tools(tools)

    log_llm_invocation()
    tool_names = [
        getattr(t, "name", None)
        or ((t.get("function") or {}).get("name") if isinstance(t, dict) else None)
        for t in (tools or [])
    ]
    model_name = getattr(llm, "model_name", None)
    temperature = getattr(llm, "temperature", None)
    max_tokens = getattr(llm, "max_tokens", None)
    log_llm_request(
        messages=messages_for_llm,
        note="plan",
        model=model_name if isinstance(model_name, str) else None,
        temperature=temperature if isinstance(temperature, (int, float)) else None,
        max_tokens=max_tokens if isinstance(max_tokens, int) else None,
        streaming=True,
        thinking=get_llm_thinking_config(),
        tools=tool_names,
    )
    try:
        ai_msg = llm.invoke(messages_for_llm)
    except Exception as e:
        logger.error(f"llm_plan_node 调用失败: {e}")
        meta["llm_error"] = str(e)
        return {"error": str(e), "meta": meta}

    log_llm_reasoning_from_message(ai_msg, note="plan")

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

    candidate_index = state.get("candidate_index") or {}
    district_clusters = state.get("district_clusters") or {}
    food_candidates = state.get("food_candidates") or []
    hotel_candidates = state.get("hotel_candidates") or []

    try:
        fixed_draft, warnings = agent.validate_and_repair(
            draft, request,
            candidate_index=candidate_index,
            district_clusters=district_clusters,
            food_candidates=food_candidates,
            hotel_candidates=hotel_candidates,
        )
        meta["validation_warnings"] = list(warnings)
        return {"draft": fixed_draft, "meta": meta, "error": None}
    except Exception as e:
        logger.error(f"validate_repair 失败: {e}")
        meta["validation_error"] = str(e)
        return {"error": str(e), "meta": meta}


# ---------------------------------------------------------------------------
# 5.5 高德补数据（校验缺失 → 单独拉取对应类别池 → 回填，最多 2 轮）
# ---------------------------------------------------------------------------

MAX_BACKFILL_ROUNDS = 2

# 高德 POI 类型码：与 place_candidate_service 保持一致
_CATEGORY_AMAP_TYPES = {
    "scenic": "110000",  # 风景名胜
    "food": "050000",  # 餐饮服务
    "hotel": "100000",  # 住宿服务
}


def _search_poi_sync(
    map_service: Any,
    *,
    keywords: str,
    city: str,
    types: str,
    page: int,
) -> Any:
    """同步包装 map_service.search_poi（节点是同步执行，事件循环中则放弃）。"""
    import asyncio

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not None:
        return None
    return asyncio.run(
        map_service.search_poi(
            keywords=keywords,
            city=city,
            citylimit=True,
            types=types,
            page=page,
            page_size=20,
        )
    )


def _fetch_backfill_candidates(
    request: Any, categories: list[str], *, round_no: int = 1
) -> dict[str, list[dict]]:
    """按缺失类别单独拉高德 POI，返回 {category: [候选 dict]}。"""
    from app.services.map_service import get_map_service
    from app.services.place_candidate_service import poi_to_candidate

    ms = get_map_service()
    if ms is None:
        return {}
    city = (request.destination or "").strip()
    if not city:
        return {}

    result: dict[str, list[dict]] = {"scenic": [], "food": [], "hotel": []}
    for cat in categories:
        types = _CATEGORY_AMAP_TYPES.get(cat)
        if not types:
            continue
        page = min(round_no, 2)
        keywords = f"{city} 热门" if (round_no > 1 and cat == "scenic") else city
        search = _search_poi_sync(
            ms, keywords=keywords, city=city, types=types, page=page
        )
        if search is None or not search.pois:
            continue
        for poi in search.pois[:15]:
            cand = poi_to_candidate(poi)
            if cand is None:
                continue
            result[cat].append(cand.to_prompt_dict())
    return result


def _merge_backfill_pool(
    existing: list[dict],
    new_items: list[dict],
    index: dict[str, Any],
    clusters: dict[str, list[str]],
) -> tuple[list[dict], dict[str, Any], dict[str, list[str]]]:
    """把新拉取的候选并入对应池与索引（按 place_id 去重）。"""
    seen = {p.get("place_id") for p in existing if isinstance(p, dict)}
    for p in new_items:
        pid = p.get("place_id")
        if not pid or pid in seen:
            continue
        existing.append(p)
        seen.add(pid)
        index[pid] = p
        if p.get("category") == "景点":
            district = p.get("district") or "其他"
            clusters.setdefault(district, []).append(pid)
    return existing, index, clusters


def amap_backfill_node(state: PlannerState) -> dict:
    """模型输出后补数据：校验缺失 → 拉高德对应类别 → 回填（最多 2 轮）。

    仅在 POI 驱动路径（state 已传入 candidate_sections）生效；
    拉取失败或轮次耗尽仍继续进入下一流程（build_trip），不阻断。
    """
    from app.agents.trip_planner_agent import TripPlannerAgent

    meta = _ensure_meta(state)
    draft = state.get("draft")
    request = state.get("request")

    # 非 POI 驱动路径（沉淀城市 RAG 等）不做高德补数据
    if not state.get("candidate_sections"):
        meta["backfill_status"] = "skipped"
        return {"meta": meta}
    if draft is None or request is None:
        meta["backfill_status"] = "skipped"
        return {"meta": meta}

    agent = TripPlannerAgent.__new__(TripPlannerAgent)
    agent._rag_tool = default_rag_tool
    agent._auto_client = False
    agent._client = None
    agent.model = "graph"
    agent.max_tool_rounds = 0
    agent.temperature = 0.0
    agent.max_tokens = 0

    candidate_index = state.get("candidate_index") or {}
    district_clusters = state.get("district_clusters") or {}
    scenic_candidates = state.get("scenic_candidates") or []
    food_candidates = state.get("food_candidates") or []
    hotel_candidates = state.get("hotel_candidates") or []

    backfill_warnings: list[str] = []
    missing = analyze_draft_missing(draft, request, candidate_index)
    if not missing["needs_fetch"]:
        meta.update(
            backfill_status="complete",
            backfill_rounds=0,
            backfill_warnings=[],
            backfill_details=[],
        )
        return {"meta": meta}

    status = "still_incomplete"
    rounds_done = 0
    for round_no in range(1, MAX_BACKFILL_ROUNDS + 1):
        missing = analyze_draft_missing(draft, request, candidate_index)
        if not missing["needs_fetch"]:
            status = "complete"
            break
        rounds_done = round_no

        try:
            fetched = _fetch_backfill_candidates(
                request, missing["categories"], round_no=round_no
            )
        except Exception as exc:
            logger.warning(f"amap_backfill 拉取失败(第{round_no}轮): {exc}")
            backfill_warnings.append(f"第{round_no}轮高德拉取失败: {exc}")
            status = "fetch_failed"
            break
        if not fetched or not any(fetched.values()):
            backfill_warnings.append(
                f"第{round_no}轮高德无可用数据: {missing['categories']}"
            )
            status = "fetch_failed"
            break

        if fetched.get("food"):
            food_candidates, candidate_index, district_clusters = _merge_backfill_pool(
                food_candidates, fetched["food"], candidate_index, district_clusters
            )
        if fetched.get("hotel"):
            hotel_candidates, candidate_index, district_clusters = _merge_backfill_pool(
                hotel_candidates, fetched["hotel"], candidate_index, district_clusters
            )
        if fetched.get("scenic"):
            scenic_candidates, candidate_index, district_clusters = _merge_backfill_pool(
                scenic_candidates, fetched["scenic"], candidate_index, district_clusters
            )

        try:
            draft, warnings = agent.validate_and_repair(
                draft,
                request,
                candidate_index=candidate_index,
                district_clusters=district_clusters,
                food_candidates=food_candidates,
                hotel_candidates=hotel_candidates,
            )
        except Exception as exc:
            logger.warning(f"amap_backfill 回填失败(第{round_no}轮): {exc}")
            backfill_warnings.append(f"第{round_no}轮回填失败: {exc}")
            status = "repair_failed"
            break
        backfill_warnings.extend(warnings)
        status = "still_incomplete" if round_no < MAX_BACKFILL_ROUNDS else "incomplete_after_rounds"

    meta.update(
        backfill_status=status,
        backfill_rounds=rounds_done,
        backfill_warnings=backfill_warnings,
        backfill_details=analyze_draft_missing(draft, request, candidate_index)["details"],
    )
    return {
        "draft": draft,
        "scenic_candidates": scenic_candidates,
        "food_candidates": food_candidates,
        "hotel_candidates": hotel_candidates,
        "candidate_index": candidate_index,
        "district_clusters": district_clusters,
        "meta": meta,
    }


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

    candidate_index = state.get("candidate_index") or {}

    try:
        trip = agent.draft_to_trip_response(draft, request, meta=meta, candidate_index=candidate_index)
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
    - 无 error → "backfill"（进高德补数据，随后进 build_trip）
    - 有 error 且 allow_fallback → "fallback"
    - 有 error 且不允许 fallback → "backfill"（让下游也尝试用原 draft）
    """
    if not state.get("error"):
        return "backfill"
    if state.get("allow_fallback", True):
        return "fallback"
    return "backfill"


def route_after_build(state: PlannerState) -> str:
    """build_trip 后无 error 则进 enrich；有 error 走 fallback。"""
    if state.get("error") and state.get("allow_fallback", True):
        return "fallback"
    return "enrich"


