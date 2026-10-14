"""
山海拾光（智旅云图） - 13.2 单日生成链（方案B · 真·逐天生成）

架构定案（REPLICATION_TASKS.md 13.1 / 13.2，2026-10-13）：
- 纯 Python 函数链（不用 LangGraph 子图），逐天循环编排在 13.3（trip_service）。
- 每天：build_day_prompt → generate_day_llm → parse_day_draft → validate_repair_day
  → check_cross_day → _draft_day_to_model（产出 ItineraryDay）。
- 失败语义：LLM 调用失败重试 1 次 → 单日模板兜底（fallback_day），不中止整份。
- 复用：_render_constraints / _render_candidates / extract_json_object /
  _repair_json_with_llm / _validate_repair_day / _collect_fallback_place_names /
  _build_fallback_day / _draft_day_to_model（全部与 batch 模式同源）。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.agents.day_state import DayGenState
from app.agents.llm_factory import (
    build_llm,
    get_llm_thinking_config,
    log_llm_invocation,
    log_llm_reasoning_from_message,
    log_llm_request,
)
from app.agents.rag_tool import rag_tool as default_rag_tool
from app.agents.trip_planner_agent import (
    BUDGET_DAILY_BASE,
    DraftDay,
    DraftHotel,
    DraftItem,
    DraftMeal,
    TripPlannerAgent,
    _render_candidates,
    _render_constraints,
    extract_json_object,
)
from app.models.schemas import ItineraryDay, TripRequest

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 单日预算占比容差（±15%，超出只记 warning，不重试）
BUDGET_TOLERANCE = 0.15

# B级候选按天过滤：每个区域最多带几条、整天最多带几条（控制 token）
CANDIDATE_CAP_PER_CLUSTER = 4
CANDIDATE_CAP_TOTAL = 24

DAY_SYSTEM_PROMPT = """你是「山海拾光（智旅云图）」行程规划助手。根据用户约束与候选POI数据，只生成多日行程中【第 N 天】的安排。

硬性规则：
1. 最终回复必须是单个 JSON 对象（不要 Markdown、不要 days 数组），字段如下：
{
  "day_number": N,
  "day_theme": "当日主题",
  "day_summary": "当日概述（2-3 句，供前端展示与前日摘要）",
  "items": [
    {"start_time": "09:00", "end_time": "11:00", "name": "地点名", "place_id": "候选列表中的place_id", "category": "景点", "activity": "简短活动", "activity_detail": "可选详情", "duration_minutes": 120, "tips": ["提示"], "ticket_price": 0}
  ],
  "daily_tips": ["当日提示 2-3 条"],
  "lunch": {"name": "店名", "place_id": "候选列表中的place_id", "cuisine_type": "菜系", "avg_price": 80},
  "dinner": {"name": "店名", "place_id": "候选列表中的place_id", "cuisine_type": "菜系", "avg_price": 100},
  "hotel": {"name": "酒店名", "place_id": "候选列表中的place_id", "hotel_type": "舒适型", "price": 350}
}
2. 当用户消息附带【候选POI】时，景点、餐厅、酒店优先从候选列表中选择并输出对应 place_id；若某类候选缺失（如候选列表没有酒店/餐饮/景点），对应字段可省略或 place_id 留空（null），系统会自动补充；严禁编造候选列表外或真实不存在的地点。
3. day_number 必须等于 N；每日景点数量不少于 2 个且不超过用户给出的每日最多景点数，尽量排满上午、下午时段。
4. 同一天的景点必须属于同一区域分组（district/cluster），不可跨区域安排；若有区域偏好，优先选择偏好区域。
5. 餐厅优先选择当天景点所在区域的候选。
6. 遵守偏好关键词与排除关键词。同行状态（特殊需求）是硬性约束，必须逐条满足：
   - 携带儿童：安排亲子友好、安全可控、路程适中的景点，避免高强度徒步。
   - 携带老人：安排轻松、少步行、有休息点的景点，控制每日体力消耗。
   - 行动不便：优先选择无障碍可达、台阶少、地面平缓的景点。
7. 时间按当日从早到晚排列，避免严重重叠。建议时段：上午09:00-11:00，午餐11:30-13:00，下午14:00-16:30，晚餐17:00-19:00。
8. 严禁重复【前日行程摘要】中已列出的景点（名称或 place_id 相同都算重复）。
9. 每日尽量包含 lunch、dinner 和 hotel（不需要 breakfast）；若对应候选缺失，可留空（字段为 null 或省略 place_id），由系统后续补充。
10. daily_tips 输出 2-3 条，针对当日具体行程给出实用提示（如该日景点预约提醒、穿搭建议、交通方案）。
"""


# ---------------------------------------------------------------------------
# 13.2.1 单日 prompt
# ---------------------------------------------------------------------------

def render_day_summary_line(entry: dict) -> str:
    """把一天的前日摘要条目渲染为紧凑单行（供第 N 天 prompt）。"""
    day_no = entry.get("day_number") or "?"
    d = entry.get("date") or ""
    theme = entry.get("theme") or f"第{day_no}天"
    places = entry.get("places") or []
    places_str = "、".join(str(p) for p in places) if places else "-"
    district = entry.get("district") or "未知"
    hotel = entry.get("hotel") or "-"
    lunch = entry.get("lunch") or "-"
    dinner = entry.get("dinner") or "-"
    cost = entry.get("cost")
    cost_str = f"约¥{cost:g}" if isinstance(cost, (int, float)) else "-"
    return (
        f"D{day_no}({d}) 主题：{theme} ｜ 景点：{places_str} ｜ 区域：{district} "
        f"｜ 酒店：{hotel} ｜ 餐：{lunch}/{dinner} ｜ {cost_str}"
    )


def _format_used_places(
    used_place_ids: Optional[list[str]],
    used_names: Optional[list[str]],
) -> str:
    """渲染已选景点（名称 + place_id），供防重复指令。"""
    parts = []
    if used_names:
        parts.append("、".join(used_names))
    if used_place_ids:
        parts.append("place_id: " + "、".join(used_place_ids))
    return "；".join(parts)


def build_day_prompt(
    request: TripRequest,
    *,
    day_number: int,
    total_days: int,
    day_date: date,
    prev_summaries: Optional[list[dict]] = None,
    used_place_ids: Optional[list[str]] = None,
    used_names: Optional[list[str]] = None,
    rag_context: Optional[str] = None,
    candidate_sections: Optional[dict[str, Any]] = None,
    prev_district: Optional[str] = None,
    prev_hotel: Optional[str] = None,
    extra_instruction: Optional[str] = None,
) -> str:
    """13.2.1 单日 user prompt。

    结构：全局约束（_render_constraints，与 batch 同源）→ 前 N-1 天紧凑摘要 + 防重复指令
    → 当日要求（第 N 天 / 首末日语境 / 区域偏好 / 酒店沿用）→ 当日候选（_render_candidates）
    → RAG 攻略上下文 → 「只输出第 N 天 JSON」指令。
    """
    parts = [_render_constraints(request)]

    prev_summaries = prev_summaries or []
    if prev_summaries:
        parts.append("")
        parts.append("【前日行程摘要】（严禁与以下已选景点重复）")
        for entry in prev_summaries:
            parts.append(render_day_summary_line(entry))
        used_text = _format_used_places(used_place_ids, used_names)
        if used_text:
            parts.append("已选景点：" + used_text)

    parts.append("")
    parts.append(f"【当日要求】今天是行程第 {day_number} 天（{day_date.isoformat()}，共 {total_days} 天）。")
    if day_number == 1:
        parts.append("首日：请包含到达/入住语境，节奏适中。")
    if total_days > 1 and day_number == total_days:
        parts.append("末日：请包含返程/退房语境，避免排得过满。")
    if prev_district:
        parts.append(
            f"区域偏好：前一天在【{prev_district}】区域，今天优先选择同一或相邻区域"
            "（同一天内景点仍须在同一区域分组）。"
        )
    if prev_hotel:
        parts.append(f"酒店：沿用前一天酒店【{prev_hotel}】。")

    candidates = _render_candidates(candidate_sections=candidate_sections)
    if candidates:
        parts.append(candidates.rstrip("\n"))

    if rag_context and rag_context.strip():
        parts.append("")
        parts.append("【攻略上下文】")
        parts.append(rag_context.strip())

    if extra_instruction:
        parts.append("额外要求：" + extra_instruction)

    parts.append("")
    parts.append(f"请只输出第 {day_number} 天的单个 JSON 对象（不要 days 数组，字段见系统提示）。")
    return "\n".join(parts)


def _select_day_candidates(state: DayGenState) -> dict[str, Any]:
    """B级候选按天过滤（13.2.1/D2 推荐方案）。

    - 前日区域（prev_district）的候选排最前，作为区域衔接的首选；
    - 剔除已用 place_id（配合 13.2.5 去重）；
    - 每区域限量 + 总量限量，控制 token。
    """
    sections = state.get("candidate_sections") or {}
    if not sections:
        return {}
    scenic = [p for p in (sections.get("scenic") or []) if isinstance(p, dict)]
    clusters = sections.get("clusters") or {}
    used = set(state.get("used_place_ids") or [])
    prev_district = state.get("prev_district")

    if not clusters:
        return {
            "scenic": scenic[:CANDIDATE_CAP_TOTAL],
            "food": (sections.get("food") or [])[:12],
            "hotel": (sections.get("hotel") or [])[:8],
        }

    ordered = list(clusters.keys())
    if prev_district and prev_district in clusters:
        ordered.remove(prev_district)
        ordered.insert(0, prev_district)

    scenic_by_id = {p.get("place_id"): p for p in scenic if p.get("place_id")}
    kept: list[dict] = []
    kept_clusters: dict[str, list[str]] = {}
    for cname in ordered:
        if len(kept) >= CANDIDATE_CAP_TOTAL:
            break
        picked: list[dict] = []
        for pid in clusters.get(cname, []):
            if pid in used:
                continue
            p = scenic_by_id.get(pid)
            if p is None:
                continue
            picked.append(p)
            if len(picked) >= CANDIDATE_CAP_PER_CLUSTER:
                break
        kept.extend(picked)
        kept_clusters[cname] = [p.get("place_id") for p in picked]

    return {
        "scenic": kept,
        "food": (sections.get("food") or [])[:12],
        "hotel": (sections.get("hotel") or [])[:8],
        "clusters": kept_clusters,
    }


# ---------------------------------------------------------------------------
# 13.2.2 单日 LLM 调用（流式）
# ---------------------------------------------------------------------------

def generate_day_llm(
    state: DayGenState,
    *,
    on_event: Optional[Callable[[dict], None]] = None,
) -> dict:
    """单日 LLM 调用：复用 llm_plan_node 的 invoke 形态（build_llm(streaming=True)）。

    先推 `status(day_generating)` 事件；invoke 失败重试 1 次，仍失败返回 error（由
    run_day_chain 转单日兜底）。token/耗时记录进 meta["daily_llm_calls"]。
    """
    request = state["request"]
    day_number = state["day_number"]
    total_days = state["total_days"]
    meta = dict(state.get("meta") or {})
    meta.setdefault("daily_llm_calls", [])

    if on_event is not None:
        try:
            on_event({
                "type": "status",
                "stage": "day_generating",
                "day_number": day_number,
                "total_days": total_days,
                "message": f"正在规划第 {day_number}/{total_days} 天…",
                # 与 trip_service.STREAM_STAGES["day_generating"] 对齐
                "progress": 40,
            })
        except Exception:
            logger.debug("day_generating 事件推送失败（忽略）")

    user_prompt = build_day_prompt(
        request,
        day_number=day_number,
        total_days=total_days,
        day_date=state["day_date"],
        prev_summaries=state.get("day_summaries"),
        used_place_ids=state.get("used_place_ids"),
        used_names=state.get("used_names"),
        rag_context=state.get("rag_context"),
        candidate_sections=_select_day_candidates(state),
        prev_district=state.get("prev_district"),
        prev_hotel=state.get("prev_hotel"),
    )
    messages = [
        SystemMessage(content=DAY_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]
    llm = build_llm(streaming=True)

    log_llm_invocation()
    model_name = getattr(llm, "model_name", None)
    log_llm_request(
        messages=messages,
        note=f"day_{day_number}",
        model=model_name if isinstance(model_name, str) else None,
        temperature=getattr(llm, "temperature", None),
        max_tokens=getattr(llm, "max_tokens", None),
        streaming=True,
        thinking=get_llm_thinking_config(),
    )

    last_error: Optional[str] = None
    for attempt in (1, 2):
        try:
            ai_msg = llm.invoke(messages)
            content = getattr(ai_msg, "content", "") or ""
            if not str(content).strip():
                raise ValueError("模型返回空内容")
            log_llm_reasoning_from_message(ai_msg, note=f"day_{day_number}")
            meta["daily_llm_calls"].append({"day": day_number, "attempt": attempt, "ok": True})
            return {"raw_llm_output": str(content), "meta": meta, "error": None}
        except Exception as e:
            last_error = str(e)
            logger.warning(f"第{day_number}天 LLM 调用失败(第{attempt}次): {e}")

    meta["daily_llm_calls"].append(
        {"day": day_number, "attempt": 2, "ok": False, "error": last_error}
    )
    meta["llm_error"] = last_error
    return {"error": last_error, "meta": meta}


# ---------------------------------------------------------------------------
# 13.2.3 单日解析 / 校验 / 修复
# ---------------------------------------------------------------------------

def parse_day_draft(state: DayGenState) -> dict:
    """单日 JSON 解析：extract_json_object → DraftDay；失败用 LLM 修复 1 次。

    LLM 输出错天时强制修正 day_number。
    """
    meta = dict(state.get("meta") or {})
    raw = state.get("raw_llm_output") or ""
    day_number = state["day_number"]

    try:
        data = extract_json_object(raw)
        day = DraftDay.model_validate(data)
    except Exception as e:
        attempts = int(state.get("repair_attempts", 0))
        if attempts < 1:
            fixed = _agent_shell()._repair_json_with_llm(raw, str(e))
            meta["repair_attempts"] = attempts + 1
            if fixed:
                try:
                    data = extract_json_object(fixed)
                    day = DraftDay.model_validate(data)
                    meta["day_repair_used"] = True
                    return {"draft_day": day, "meta": meta, "error": None}
                except Exception as e2:
                    logger.warning(f"第{day_number}天 JSON 修复后仍解析失败: {e2}")
                    return {
                        "error": f"第{day_number}天 JSON 修复后仍解析失败: {e2}",
                        "meta": meta,
                    }
        return {"error": f"第{day_number}天 JSON 解析失败: {e}", "meta": meta}

    if day.day_number != day_number:
        day = day.model_copy(update={"day_number": day_number})
    return {"draft_day": day, "meta": meta, "error": None}


def validate_repair_day(state: DayGenState) -> dict:
    """单日校验/回补：复用 _validate_repair_day（与 batch 的 validate_and_repair 同源）。

    景点不足/缺餐缺酒店按当日候选回补；无任何景点安排视为单日失败（走兜底）。
    """
    request = state["request"]
    day = state["draft_day"]
    day_number = state["day_number"]
    day, warnings = _agent_shell()._validate_repair_day(
        day,
        request,
        day_number=day_number,
        candidate_index=state.get("candidate_index"),
        district_clusters=state.get("district_clusters"),
        food_candidates=state.get("food_candidates"),
        hotel_candidates=state.get("hotel_candidates"),
        used_global_scenic=set(state.get("used_place_ids") or []),
    )
    if not day.items:
        return {"error": f"第{day_number}天无任何景点安排", "day_warnings": warnings}
    return {"draft_day": day, "day_warnings": warnings, "error": None}


# ---------------------------------------------------------------------------
# 13.2.5 跨天约束校验
# ---------------------------------------------------------------------------

def _day_cost_estimate(day: DraftDay, request: TripRequest) -> float:
    """当日成本估算：住宿 + 餐（×人数）+ 门票（×人数）。"""
    travelers = max(1, request.travelers)
    accommodation = float(day.hotel.price) if day.hotel else 0.0
    food = sum(
        float(m.avg_price or 0) * travelers
        for m in (day.lunch, day.dinner)
        if m is not None
    )
    ticket = sum(float(it.ticket_price or 0) for it in day.items) * travelers
    return accommodation + food + ticket


def _check_budget_share(day: DraftDay, request: TripRequest) -> Optional[str]:
    """每日预算占比校验：超 ±15% 返回 warning 文案（不触发重试）。"""
    level = getattr(request.budget_level, "value", request.budget_level)
    base = BUDGET_DAILY_BASE.get(str(level), 600.0)
    if request.daily_budget is not None:
        base = float(request.daily_budget)
    if base <= 0:
        return None
    cost = _day_cost_estimate(day, request)
    ratio = cost / base
    if ratio > 1.0 + BUDGET_TOLERANCE:
        return (
            f"第{day.day_number}天预算占比 {ratio:.0%}（约{cost:.0f}元 > 每日基准 {base:.0f}元），超出预算"
        )
    if ratio < 1.0 - BUDGET_TOLERANCE:
        return (
            f"第{day.day_number}天预算占比仅 {ratio:.0%}（约{cost:.0f}元 < 每日基准 {base:.0f}元），可能偏省"
        )
    return None


def _pick_unused_scenic(
    state: DayGenState,
    used_pids: set[str],
    *,
    pref_cluster: Optional[str] = None,
) -> Optional[str]:
    """从候选池挑一个未使用的景点 place_id（去重替换用，优先同区域 + 高评分）。"""
    idx_map = state.get("candidate_index") or {}
    clusters = state.get("district_clusters") or {}
    pid_to_cluster = {pid: c for c, pids in clusters.items() for pid in pids}
    used_names = set(state.get("used_names") or [])
    excluded = [
        str(x).strip()
        for x in (state["request"].excluded_keywords or [])
        if str(x).strip()
    ]

    def _ok(pid: str) -> bool:
        if pid in used_pids:
            return False
        cp = idx_map.get(pid)
        if not isinstance(cp, dict):
            return False
        name = cp.get("name") or ""
        if name and name in used_names:
            return False
        if excluded and any(ex in name for ex in excluded):
            return False
        return True

    pref: list[tuple[float, str]] = []
    others: list[tuple[float, str]] = []
    for pid, cp in idx_map.items():
        if not _ok(pid):
            continue
        try:
            rating = float(cp.get("rating") or 0.0)
        except (TypeError, ValueError):
            rating = 0.0
        bucket = pref if (pref_cluster and pid_to_cluster.get(pid) == pref_cluster) else others
        bucket.append((rating, pid))
    pref.sort(key=lambda x: -x[0])
    others.sort(key=lambda x: -x[0])
    if pref:
        return pref[0][1]
    if others:
        return others[0][1]
    return None


def check_cross_day(state: DayGenState) -> dict:
    """13.2.5 跨天约束校验：

    - 景点全局去重（name/place_id）：有候选替换、无候选保留并 warning；
    - 区域衔接（软）：前日区域已写入 prompt，此处只统计当日区域供循环更新；
    - 酒店连续性：沿用前日酒店（软对齐，不强制）；
    - 每日预算占比：±15% 记 warning。
    """
    request = state["request"]
    day = state["draft_day"].model_copy(deep=True)
    day_number = state["day_number"]
    warnings = list(state.get("day_warnings") or [])

    used_pids = set(state.get("used_place_ids") or [])
    used_names = set(state.get("used_names") or [])
    idx_map = state.get("candidate_index") or {}
    clusters = state.get("district_clusters") or {}
    pid_to_cluster = {pid: c for c, pids in clusters.items() for pid in pids}

    # 1) 景点全局去重
    for it in day.items:
        is_dup = (it.place_id and it.place_id in used_pids) or (
            it.name and it.name in used_names
        )
        if not is_dup:
            continue
        new_pid = _pick_unused_scenic(
            state,
            used_pids | ({it.place_id} if it.place_id else set()),
            pref_cluster=pid_to_cluster.get(it.place_id or ""),
        )
        if new_pid:
            cp = idx_map.get(new_pid) or {}
            old_name = it.name
            it.place_id = new_pid
            it.name = cp.get("name") or it.name
            it.category = "景点"
            if cp.get("cost"):
                try:
                    it.ticket_price = float(cp.get("cost"))
                except (TypeError, ValueError):
                    pass
            warnings.append(
                f"第{day_number}天 [{old_name}] 与已选景点重复，已替换为 [{it.name}]"
            )
        else:
            warnings.append(
                f"第{day_number}天 [{it.name}] 与已选景点重复且无可用替换，保留"
            )

    # 2) 酒店连续性（沿用前日酒店）
    prev_hotel = state.get("prev_hotel")
    if prev_hotel:
        prev_pid = next(
            (
                pid
                for pid, cp in idx_map.items()
                if isinstance(cp, dict) and cp.get("name") == prev_hotel
            ),
            None,
        )
        if day.hotel is None:
            day.hotel = DraftHotel(
                name=prev_hotel,
                place_id=prev_pid,
                hotel_type="舒适型",
                price=300.0,
            )
            warnings.append(f"第{day_number}天酒店缺失，沿用前一天: {prev_hotel}")
        elif day.hotel.name != prev_hotel:
            day.hotel = DraftHotel(
                name=prev_hotel,
                place_id=prev_pid,
                hotel_type=day.hotel.hotel_type or "舒适型",
                price=day.hotel.price,
                address=day.hotel.address,
            )
            warnings.append(f"第{day_number}天酒店沿用前一天: {prev_hotel}")

    # 3) 每日预算占比
    budget_warning = _check_budget_share(day, request)
    if budget_warning:
        warnings.append(budget_warning)

    # 4) 当日区域（供循环更新 prev_district）
    chosen_district = next(
        (
            pid_to_cluster[pid]
            for pid in (it.place_id for it in day.items if it.place_id)
            if pid in pid_to_cluster
        ),
        None,
    )
    return {
        "draft_day": day,
        "day_warnings": warnings,
        "chosen_district": chosen_district,
        "error": None,
    }


# ---------------------------------------------------------------------------
# 13.2.4 单日兜底
# ---------------------------------------------------------------------------

def fallback_day(state: DayGenState) -> dict:
    """单日模板兜底：复用 _collect_fallback_place_names + _build_fallback_day。

    只降级当天，不中止整份行程；meta 记录 fallback_used / fallback_reason，
    供前端提示「第 N 天降级模板」。
    """
    request = state["request"]
    day_number = state["day_number"]
    meta = dict(state.get("meta") or {})
    agent = _agent_shell()

    place_names, context = agent._collect_fallback_place_names(request, meta)
    draft_day, _ = agent._build_fallback_day(
        request, day_number, place_names=place_names, cursor=0
    )
    if context:
        meta["fallback_context_chars"] = len(context)
    meta["fallback_used"] = True
    meta["fallback_reason"] = state.get("error") or "unknown"

    warnings = [f"第{day_number}天使用降级模板生成"]
    day_model = _to_itinerary_day(
        agent,
        draft_day,
        request,
        day_number,
        state["day_date"],
        state.get("candidate_index"),
    )
    return {
        "draft_day": draft_day,
        "day": day_model,
        "day_warnings": warnings,
        "fallback_used": True,
        "meta": meta,
        "error": None,
    }


# ---------------------------------------------------------------------------
# 辅助 / 单日链主入口
# ---------------------------------------------------------------------------

def _agent_shell() -> TripPlannerAgent:
    """无实例状态的 TripPlannerAgent 壳（与 nodes.py 的 __new__ 模式一致），

    用于复用实例方法：_repair_json_with_llm / _validate_repair_day /
    _draft_day_to_model / _collect_fallback_place_names / _build_fallback_day。
    """
    agent = TripPlannerAgent.__new__(TripPlannerAgent)
    agent._rag_tool = default_rag_tool
    agent._auto_client = False
    agent._client = None
    agent.model = "day-chain"
    agent.max_tool_rounds = 0
    agent.temperature = 0.0
    agent.max_tokens = 0
    return agent


def _to_itinerary_day(
    agent: TripPlannerAgent,
    draft_day: DraftDay,
    request: TripRequest,
    day_number: int,
    day_date: date,
    candidate_index: Optional[dict[str, Any]],
) -> ItineraryDay:
    """DraftDay → ItineraryDay（复用 _draft_day_to_model，含候选池真实坐标/地址回填）。"""
    return agent._draft_day_to_model(
        draft_day,
        day_number=day_number,
        day_date=day_date,
        candidate_index=candidate_index,
        request=request,
    )


def _build_day_summary(
    draft_day: DraftDay,
    state: DayGenState,
    used_pids: list[str],
) -> dict:
    """生成当日紧凑摘要条目（供下一天 prompt 与前端 day 事件）。"""
    pid_to_cluster = {
        pid: cname
        for cname, pids in (state.get("district_clusters") or {}).items()
        for pid in pids
    }
    district = next((pid_to_cluster[p] for p in used_pids if p in pid_to_cluster), None)
    return {
        "day_number": draft_day.day_number,
        "date": (draft_day.itinerary_date or state.get("day_date")).isoformat(),
        "theme": draft_day.day_theme or f"第{draft_day.day_number}天",
        "places": [
            f"{it.name}#{it.place_id}" if it.place_id else it.name
            for it in draft_day.items
        ],
        "district": district,
        "hotel": draft_day.hotel.name if draft_day.hotel else None,
        "lunch": draft_day.lunch.name if draft_day.lunch else None,
        "dinner": draft_day.dinner.name if draft_day.dinner else None,
        "cost": round(_day_cost_estimate(draft_day, state["request"]), 2),
    }


def run_day_chain(
    state: DayGenState,
    *,
    on_event: Optional[Callable[[dict], None]] = None,
) -> dict:
    """13.2 单日生成链主入口：generate → parse → validate/repair → cross-day → ItineraryDay。

    返回 patch（供 13.3 逐天循环消费）：
    - draft_day / day（ItineraryDay，占位坐标，地图/天气由循环补全）
    - day_warnings / meta / error / fallback_used
    - memory：used_place_ids_added / used_names_added / prev_district /
      prev_hotel / day_summary（供循环更新跨天记忆）
    """
    gen = generate_day_llm(state, on_event=on_event)
    if gen.get("error"):
        return fallback_day({**state, **gen})

    parsed = parse_day_draft({**state, **gen})
    if parsed.get("error"):
        return fallback_day({**state, **gen, **parsed})

    validated = validate_repair_day({**state, **gen, **parsed})
    if validated.get("error"):
        return fallback_day({**state, **gen, **parsed, **validated})

    crossed = check_cross_day({**state, **gen, **parsed, **validated})
    if crossed.get("error"):
        return fallback_day({**state, **gen, **parsed, **validated, **crossed})

    draft_day = crossed["draft_day"]
    day_model = _to_itinerary_day(
        _agent_shell(),
        draft_day,
        state["request"],
        state["day_number"],
        state["day_date"],
        state.get("candidate_index"),
    )

    meta = dict(gen.get("meta") or {})
    meta.update(parsed.get("meta") or {})
    meta["day_warnings"] = list(crossed.get("day_warnings") or [])

    used_pids = [it.place_id for it in draft_day.items if it.place_id]
    used_names = [it.name for it in draft_day.items]
    return {
        "draft_day": draft_day,
        "day": day_model,
        "day_warnings": meta["day_warnings"],
        "meta": meta,
        "error": None,
        "fallback_used": False,
        "memory": {
            "used_place_ids_added": used_pids,
            "used_names_added": used_names,
            "prev_district": crossed.get("chosen_district"),
            "prev_hotel": draft_day.hotel.name if draft_day.hotel else state.get("prev_hotel"),
            "day_summary": _build_day_summary(draft_day, state, used_pids),
        },
    }
