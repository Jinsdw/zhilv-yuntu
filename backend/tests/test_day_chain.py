"""
山海拾光（智旅云图） - 13.2 单日生成链测试

覆盖：
- build_day_prompt：第 1 天无前日摘要；第 N 天含前日摘要/防重复/区域偏好/酒店沿用；
  首日/末日语境；与 batch 的全局约束渲染一致
- _select_day_candidates：B级候选按天过滤（前日区域优先、剔除已用、限量）
- parse_day_draft：合法 JSON / 错天修正 / 非法 JSON 修复失败
- validate_repair_day：B级候选回补（景点/餐/酒店）；空日失败
- check_cross_day：去重替换 / 无候选保留 / 酒店连续性 / 预算占比 warning
- fallback_day：单日模板兜底（只降级当天）
- run_day_chain：happy path / LLM 失败重试后兜底 / day_generating 事件

不打真实 LLM / ChromaDB / Redis（build_llm 与 rag_tool 均 mock）。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.agents import day_chain
from app.agents.day_chain import (
    _check_budget_share,
    _day_cost_estimate,
    _select_day_candidates,
    build_day_prompt,
    check_cross_day,
    fallback_day,
    parse_day_draft,
    render_day_summary_line,
    run_day_chain,
    validate_repair_day,
)
from app.agents.trip_planner_agent import MIN_PLACES_PER_DAY, DraftDay, DraftHotel, DraftItem, DraftMeal
from app.models.schemas import BudgetLevel, ItineraryDay, TripRequest


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _future_range(days: int = 3) -> tuple[date, date]:
    start = date.today() + timedelta(days=10)
    end = start + timedelta(days=days - 1)
    return start, end


def _make_request(**kwargs) -> TripRequest:
    start, end = _future_range(kwargs.pop("days", 3))
    data = {
        "destination": "北京",
        "start_date": start,
        "end_date": end,
        "travelers": 2,
        "budget_level": BudgetLevel.STANDARD,
    }
    data.update(kwargs)
    return TripRequest(**data)


def _scenic(pid: str, name: str, rating: float = 4.5, cost: float = 30.0) -> dict:
    return {
        "place_id": pid,
        "name": name,
        "rating": rating,
        "cost": cost,
        "district": "东城区",
        "address": f"{name}路1号",
        "coordinate": {"latitude": 39.9, "longitude": 116.4},
    }


def _b_sections() -> tuple[dict, dict, list, list]:
    """B级候选：2 个区域簇 + 餐饮/住宿池。"""
    p1 = _scenic("p1", "故宫", rating=4.8, cost=40)
    p2 = _scenic("p2", "景山公园", rating=4.5, cost=10)
    p3 = _scenic("p3", "颐和园", rating=4.7, cost=30)
    p4 = _scenic("p4", "恭王府", rating=4.4, cost=20)
    scenic = [p1, p2, p3, p4]
    food = [
        {"place_id": "f1", "name": "全聚德", "cost": 100, "rating": 4.6, "district": "东城区"},
        {"place_id": "f2", "name": "东来顺", "cost": 120, "rating": 4.5, "district": "东城区"},
    ]
    hotel = [
        {"place_id": "h1", "name": "王府井大酒店", "cost": 500, "rating": 4.6, "district": "东城区"},
        {"place_id": "h2", "name": "西苑饭店", "cost": 450, "rating": 4.4, "district": "西城区"},
    ]
    sections = {
        "scenic": scenic,
        "food": food,
        "hotel": hotel,
        "clusters": {"东城区": ["p1", "p2"], "西城区": ["p3", "p4"]},
    }
    index = {p["place_id"]: p for p in scenic + food + hotel}
    return sections, index, food, hotel


def _make_state(**overrides) -> dict:
    request = _make_request()
    start = request.start_date
    total = (request.end_date - request.start_date).days + 1
    state = {
        "request": request,
        "total_days": total,
        "day_dates": [start + timedelta(days=i) for i in range(total)],
        "day_number": 1,
        "day_date": start,
        "global_constraints": {},
        "candidate_sections": {},
        "rag_context": "",
        "candidate_index": {},
        "district_clusters": {},
        "food_candidates": [],
        "hotel_candidates": [],
        "used_place_ids": [],
        "used_names": [],
        "prev_district": None,
        "prev_hotel": None,
        "day_summaries": [],
        "accumulated_budget": 0.0,
        "meta": {},
    }
    state.update(overrides)
    return state


def _day_payload(day_number: int = 1, names=("故宫", "景山公园"), pids=("p1", "p2")) -> str:
    return json.dumps(
        {
            "day_number": day_number,
            "day_theme": "文化之旅",
            "day_summary": "上午故宫，下午景山公园。",
            "items": [
                {"start_time": "09:00", "end_time": "11:00", "name": names[0], "place_id": pids[0],
                 "category": "景点", "activity": "游览", "duration_minutes": 120,
                 "tips": ["提前预约"], "ticket_price": 40},
                {"start_time": "14:00", "end_time": "16:30", "name": names[1], "place_id": pids[1],
                 "category": "景点", "activity": "游览", "duration_minutes": 120,
                 "tips": [], "ticket_price": 10},
            ],
            "daily_tips": ["早起出发", "注意防晒"],
            "lunch": {"name": "全聚德", "place_id": "f1", "cuisine_type": "京菜", "avg_price": 80},
            "dinner": {"name": "东来顺", "place_id": "f2", "cuisine_type": "火锅", "avg_price": 100},
            "hotel": {"name": "王府井大酒店", "place_id": "h1", "hotel_type": "舒适型", "price": 400},
        },
        ensure_ascii=False,
    )


class _FakeLLM:
    model_name = "fake-model"
    temperature = 0.0
    max_tokens = 100

    def __init__(self, payload: str, fail_times: int = 0):
        self.payload = payload
        self.fail_times = fail_times
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("fake llm failure")
        return AIMessage(content=self.payload)


class _FakeRAGResult:
    context_text = ""
    chunks = []
    stats = SimpleNamespace(degraded=False)


def _patch_rag(monkeypatch) -> None:
    monkeypatch.setattr(
        day_chain.default_rag_tool, "search_for_trip", lambda request: _FakeRAGResult()
    )


# ---------------------------------------------------------------------------
# 13.2.1 build_day_prompt
# ---------------------------------------------------------------------------

def test_build_day_prompt_day1_no_prev_summary():
    request = _make_request()
    prompt = build_day_prompt(
        request,
        day_number=1,
        total_days=3,
        day_date=request.start_date,
    )
    assert "前日行程摘要" not in prompt
    assert "只输出第 1 天" in prompt
    assert "到达/入住" in prompt  # 首日语境
    assert "共 3 天" in prompt
    assert "预算等级" in prompt  # 全局约束与 batch 同源


def test_build_day_prompt_dayN_summary_dedup_district_hotel():
    request = _make_request()
    summary = {
        "day_number": 1,
        "date": request.start_date.isoformat(),
        "theme": "文化之旅",
        "places": ["故宫#p1", "景山公园#p2"],
        "district": "东城区",
        "hotel": "王府井大酒店",
        "lunch": "全聚德",
        "dinner": "东来顺",
        "cost": 800.0,
    }
    prompt = build_day_prompt(
        request,
        day_number=2,
        total_days=3,
        day_date=request.start_date + timedelta(days=1),
        prev_summaries=[summary],
        used_place_ids=["p1", "p2"],
        used_names=["故宫", "景山公园"],
        prev_district="东城区",
        prev_hotel="王府井大酒店",
    )
    assert "前日行程摘要" in prompt
    assert "严禁与以下已选景点重复" in prompt
    assert "故宫#p1" in prompt
    assert "已选景点：故宫、景山公园" in prompt
    assert "区域偏好" in prompt and "东城区" in prompt
    assert "酒店：沿用前一天酒店【王府井大酒店】" in prompt
    assert "只输出第 2 天" in prompt
    assert "返程/退房" not in prompt  # 第 2 天非末日


def test_build_day_prompt_last_day_return_context():
    request = _make_request()
    prompt = build_day_prompt(
        request,
        day_number=3,
        total_days=3,
        day_date=request.start_date + timedelta(days=2),
    )
    assert "返程/退房" in prompt


def test_build_day_prompt_matches_batch_constraints():
    """daily 与 batch 的全局约束渲染口径一致（复用 _render_constraints）。"""
    from app.agents.trip_planner_agent import build_user_prompt

    request = _make_request(preferred_keywords=["古迹"], excluded_keywords=["爬山"], with_kids=True)
    batch = build_user_prompt(request)
    daily = build_day_prompt(
        request,
        day_number=1,
        total_days=2,
        day_date=request.start_date,
    )
    for snippet in (
        "目的地：北京",
        "人数：2",
        "预算等级：标准适中",
        "偏好关键词：古迹",
        "排除关键词：爬山",
        "携带儿童",
    ):
        assert snippet in batch
        assert snippet in daily


# ---------------------------------------------------------------------------
# _select_day_candidates
# ---------------------------------------------------------------------------

def test_select_day_candidates_prev_cluster_first_and_used_excluded():
    sections, _, _, _ = _b_sections()
    state = _make_state(
        candidate_sections=sections,
        district_clusters=sections["clusters"],
        used_place_ids=["p1"],
        prev_district="西城区",
    )
    filtered = _select_day_candidates(state)
    assert filtered["clusters"] is not None
    order = list(filtered["clusters"].keys())
    assert order[0] == "西城区"  # 前日区域排最前
    kept_ids = [p["place_id"] for p in filtered["scenic"]]
    assert "p1" not in kept_ids  # 已用剔除
    assert "p3" in kept_ids


def test_select_day_candidates_caps():
    sections, _, _, _ = _b_sections()
    many = [_scenic(f"px{i}", f"景点{i}", rating=4.0 + i * 0.01) for i in range(30)]
    sections = {
        "scenic": many,
        "food": [],
        "hotel": [],
        "clusters": {"东城区": [p["place_id"] for p in many]},
    }
    state = _make_state(candidate_sections=sections, district_clusters=sections["clusters"])
    filtered = _select_day_candidates(state)
    assert len(filtered["scenic"]) <= 24  # CANDIDATE_CAP_TOTAL


# ---------------------------------------------------------------------------
# parse_day_draft
# ---------------------------------------------------------------------------

def test_parse_day_draft_valid():
    state = _make_state(raw_llm_output=_day_payload(day_number=1))
    result = parse_day_draft(state)
    assert result["error"] is None
    assert isinstance(result["draft_day"], DraftDay)
    assert result["draft_day"].day_number == 1
    assert len(result["draft_day"].items) == 2


def test_parse_day_draft_fixes_wrong_day_number():
    state = _make_state(raw_llm_output=_day_payload(day_number=5))
    result = parse_day_draft(state)
    assert result["draft_day"].day_number == 1


def test_parse_day_draft_invalid_returns_error():
    state = _make_state(raw_llm_output="不是 JSON")
    result = parse_day_draft(state)
    assert result["error"] is not None
    assert "draft_day" not in result


# ---------------------------------------------------------------------------
# validate_repair_day
# ---------------------------------------------------------------------------

def test_validate_repair_day_b_backfills():
    sections, index, food, hotel = _b_sections()
    day = DraftDay(
        day_number=1,
        items=[DraftItem(name="故宫", place_id="p1", category="景点")],
    )
    state = _make_state(
        draft_day=day,
        candidate_index=index,
        district_clusters=sections["clusters"],
        food_candidates=food,
        hotel_candidates=hotel,
    )
    result = validate_repair_day(state)
    assert result["error"] is None
    repaired = result["draft_day"]
    assert len(repaired.items) >= MIN_PLACES_PER_DAY
    assert repaired.lunch is not None
    assert repaired.dinner is not None
    assert repaired.hotel is not None
    assert repaired.breakfast is None  # 强制不安排早餐


def test_validate_repair_day_empty_day_fails():
    day = DraftDay(day_number=1, items=[])
    state = _make_state(draft_day=day)
    result = validate_repair_day(state)
    assert result["error"] is not None


# ---------------------------------------------------------------------------
# check_cross_day
# ---------------------------------------------------------------------------

def test_check_cross_day_dedup_replaces_with_candidate():
    sections, index, food, hotel = _b_sections()
    day = DraftDay(
        day_number=2,
        items=[
            DraftItem(name="故宫", place_id="p1", category="景点"),  # 与第 1 天重复
            DraftItem(name="颐和园", place_id="p3", category="景点"),
        ],
    )
    state = _make_state(
        draft_day=day,
        candidate_index=index,
        district_clusters=sections["clusters"],
        used_place_ids=["p1"],
        used_names=["故宫"],
        prev_district="西城区",
    )
    result = check_cross_day(state)
    items = result["draft_day"].items
    assert items[0].place_id != "p1"  # 已替换
    assert any("已替换" in w for w in result["day_warnings"])


def test_check_cross_day_dedup_warns_without_candidates():
    day = DraftDay(
        day_number=2,
        items=[DraftItem(name="故宫", place_id="p1", category="景点")],
    )
    state = _make_state(
        draft_day=day,
        used_place_ids=["p1"],
        used_names=["故宫"],
    )
    result = check_cross_day(state)
    assert result["draft_day"].items[0].place_id == "p1"  # 无候选，保留
    assert any("无可用替换" in w for w in result["day_warnings"])


def test_check_cross_day_hotel_continuity():
    day = DraftDay(
        day_number=2,
        items=[DraftItem(name="新景点", place_id="p9", category="景点")],
        hotel=DraftHotel(name="如家", price=300),
    )
    state = _make_state(draft_day=day, prev_hotel="王府井大酒店", used_place_ids=["p9"])
    result = check_cross_day(state)
    assert result["draft_day"].hotel.name == "王府井大酒店"
    assert any("酒店沿用前一天" in w for w in result["day_warnings"])


def test_check_cross_day_budget_warning():
    day = DraftDay(
        day_number=1,
        items=[
            DraftItem(name="A", place_id="a", ticket_price=800),
            DraftItem(name="B", place_id="b", ticket_price=800),
        ],
        lunch=DraftMeal(name="L", avg_price=500),
        dinner=DraftMeal(name="D", avg_price=500),
        hotel=DraftHotel(name="H", price=1000),
    )
    state = _make_state(draft_day=day, budget_level=BudgetLevel.STANDARD)
    result = check_cross_day(state)
    assert any("预算占比" in w for w in result["day_warnings"])


def test_day_cost_estimate_and_budget_share():
    day = DraftDay(
        day_number=1,
        items=[DraftItem(name="A", place_id="a", ticket_price=40)],
        lunch=DraftMeal(name="L", avg_price=80),
        dinner=DraftMeal(name="D", avg_price=100),
        hotel=DraftHotel(name="H", price=400),
    )
    request = _make_request(travelers=2)
    cost = _day_cost_estimate(day, request)
    assert cost == 400 + (80 + 100) * 2 + 40 * 2  # 住宿 + 餐×2人 + 门票×2人
    assert _check_budget_share(day, request) is not None  # 840 > 600×1.15 → warning
    single = _make_request(travelers=1)
    assert _check_budget_share(day, single) is None  # 620/600 ≈ 103% ≤ 115%


# ---------------------------------------------------------------------------
# fallback_day
# ---------------------------------------------------------------------------

def test_fallback_day_only_degrades_current_day(monkeypatch):
    _patch_rag(monkeypatch)
    state = _make_state(day_number=2, error="llm down")
    result = fallback_day(state)
    assert result["error"] is None
    assert result["fallback_used"] is True
    assert isinstance(result["day"], ItineraryDay)
    assert len(result["day"].items) >= MIN_PLACES_PER_DAY
    assert result["day"].lunch is not None and result["day"].dinner is not None
    assert result["day"].hotel is not None


# ---------------------------------------------------------------------------
# run_day_chain（单日生成链主入口）
# ---------------------------------------------------------------------------

def test_run_day_chain_happy_path(monkeypatch):
    monkeypatch.setattr(day_chain, "build_llm", lambda **kw: _FakeLLM(_day_payload(day_number=1)))
    events: list[dict] = []
    state = _make_state(day_number=1)
    result = run_day_chain(state, on_event=events.append)

    assert result["error"] is None
    assert result["fallback_used"] is False
    assert isinstance(result["day"], ItineraryDay)
    assert result["day"].day_number == 1
    assert result["memory"]["day_summary"]["theme"] == "文化之旅"
    assert result["memory"]["used_place_ids_added"] == ["p1", "p2"]
    assert result["memory"]["used_names_added"] == ["故宫", "景山公园"]
    # 事件：先推 day_generating
    assert events and events[0]["type"] == "status"
    assert events[0]["stage"] == "day_generating"
    assert events[0]["day_number"] == 1


def test_run_day_chain_llm_failure_then_fallback(monkeypatch):
    _patch_rag(monkeypatch)
    monkeypatch.setattr(
        day_chain, "build_llm", lambda **kw: _FakeLLM(_day_payload(day_number=1), fail_times=2)
    )
    state = _make_state(day_number=1)
    result = run_day_chain(state)
    assert result["fallback_used"] is True  # 重试 1 次仍失败 → 单日兜底
    assert result["error"] is None
    assert isinstance(result["day"], ItineraryDay)
    assert result["meta"]["fallback_reason"] == "fake llm failure"
