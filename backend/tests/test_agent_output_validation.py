"""
智旅云图 - Agent 输出验证测试

本文件聚焦「输出验证」：验证 TripPlannerAgent 生成的 TripResponse 在
结构、内容与业务约束上的不变量，覆盖：

- draft_to_trip_response：天数/日期/景点数量/时间/地点/评分结构
- enrich_budget_and_summary：预算拆分一致性、贴士分组、摘要补全
- validate_and_repair：排除词、每日景点上限、天数对齐、B类候选池补选
- plan() 端到端：LLM 路径 / edit_day / fallback 的元数据与输出结构
- B 类动态城市：候选池 place_id、真实坐标、食宿自动补选

不打真实 LLM API；不打 ChromaDB（rag_tool 用 mock）。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agents.trip_planner_agent import (
    TIP_CATEGORIES,
    DraftDay,
    DraftHotel,
    DraftItem,
    DraftItinerary,
    DraftMeal,
    TripPlannerAgent,
)
from app.models.schemas import (
    BudgetLevel,
    TravelStyle,
    TripRequest,
    TripResponse,
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _future_range(days: int = 3) -> tuple[date, date]:
    start = date.today() + timedelta(days=10)
    end = start + timedelta(days=days - 1)
    return start, end


def _make_request(**kwargs) -> TripRequest:
    start, end = _future_range(kwargs.pop("days", 3))
    data = {
        "destination": "成都",
        "start_date": start,
        "end_date": end,
        "travelers": 2,
        "budget_level": BudgetLevel.STANDARD,
        "travel_style": TravelStyle.FOODIE,
        "max_places_per_day": 3,
        "preferred_keywords": ["火锅"],
        "excluded_keywords": ["夜店"],
    }
    data.update(kwargs)
    return TripRequest(**data)


def _sample_draft(days: int = 3, places_per_day: int = 2) -> DraftItinerary:
    """构造可通过校验的 DraftItinerary（A类占位模式）。"""
    payload: dict[str, Any] = {
        "trip_name": "成都美食三日游",
        "days": [],
        "trip_highlights": ["火锅", "熊猫"],
        "trip_tips": ["【出行准备】提前预约热门景点"],
        "recommended_foods": ["火锅", "串串"],
    }
    for i in range(1, days + 1):
        items = []
        for j in range(places_per_day):
            items.append(
                {
                    "start_time": f"{9 + j * 3:02d}:00",
                    "end_time": f"{11 + j * 3:02d}:00",
                    "name": f"景点{i}-{j+1}",
                    "category": "景点",
                    "activity": "游览",
                    "duration_minutes": 120,
                    "tips": ["带水"],
                    "ticket_price": 50,
                }
            )
        payload["days"].append(
            {
                "day_number": i,
                "day_theme": f"主题{i}",
                "items": items,
                "lunch": {"name": f"午餐店{i}", "cuisine_type": "川菜", "avg_price": 80},
                "dinner": {"name": f"晚餐店{i}", "cuisine_type": "火锅", "avg_price": 100},
                "hotel": {"name": f"酒店{i}", "hotel_type": "舒适型", "price": 320},
            }
        )
    return DraftItinerary.model_validate(payload)


def _assert_valid_item_times(day) -> None:
    """断言单日 items 时间合法：HH:MM 格式、end>start、排序且不重叠。"""
    prev_end = -1
    for it in day.items:
        assert it.start_time.count(":") == 1 and it.end_time.count(":") == 1
        sh, sm = map(int, it.start_time.split(":"))
        eh, em = map(int, it.end_time.split(":"))
        start = sh * 60 + sm
        end = eh * 60 + em
        assert end > start
        assert start >= prev_end
        prev_end = end


def _assert_budget_consistent(trip: TripResponse, request: TripRequest) -> None:
    """断言预算汇总与拆分一致性。"""
    b = trip.budget
    assert b.total_budget > 0
    components = [
        b.accommodation_budget,
        b.food_budget,
        b.transportation_budget,
        b.ticket_budget,
        b.shopping_budget,
        b.other_budget,
    ]
    assert sum(components) == pytest.approx(b.total_budget, abs=0.06)
    assert b.daily_avg_budget == pytest.approx(b.total_budget / trip.total_days, abs=0.06)
    assert b.budget_per_person == pytest.approx(b.total_budget / request.travelers, abs=0.06)
    assert b.budget_status == "within_budget"


def _assert_trip_invariants(trip: TripResponse, request: TripRequest) -> None:
    """通用输出不变量：结构、天数、日期、评分、地点。"""
    expected_days = (request.end_date - request.start_date).days + 1
    assert trip.destination == request.destination
    assert trip.start_date == request.start_date
    assert trip.end_date == request.end_date
    assert trip.total_days == expected_days
    assert len(trip.days) == expected_days
    assert 0 <= trip.overall_rating <= 5

    for i, day in enumerate(trip.days):
        assert day.day_number == i + 1
        assert day.itinerary_date == request.start_date + timedelta(days=i)
        assert day.total_places == len(day.items)
        assert day.total_places <= request.max_places_per_day
        assert day.total_duration == sum(it.place.suggested_duration for it in day.items)
        assert 0 <= day.total_rating <= 5
        _assert_valid_item_times(day)
        for it in day.items:
            assert it.place.name
            assert it.place.place_id
            assert it.place.address
            assert -90 <= it.place.coordinate.latitude <= 90
            assert -180 <= it.place.coordinate.longitude <= 180

    if trip.budget.total_budget > 0:
        _assert_budget_consistent(trip, request)
# ---------------------------------------------------------------------------
# FakeLLM / Fixtures
# ---------------------------------------------------------------------------

class FakeLLM:
    """模拟 LangChain ChatModel，按预设序列返回 AIMessage。"""

    def __init__(self, responses: Optional[list] = None):
        self.responses = list(responses or [])
        self._idx = 0
        self.invoke_count = 0

    def invoke(self, messages, **kwargs):
        self.invoke_count += 1
        if self._idx >= len(self.responses):
            return self.responses[-1] if self.responses else AIMessage(content="")
        resp = self.responses[self._idx]
        self._idx += 1
        return resp

    def bind_tools(self, tools):
        return self

    def bind(self, **kwargs):
        return self

    @property
    def model_name(self):
        return "fake-llm"


@pytest.fixture
def mock_rag():
    rag = MagicMock()
    rag.as_openai_tools.return_value = [
        {
            "type": "function",
            "function": {
                "name": "search_travel_guides",
                "description": "检索",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    rag.execute.return_value = json.dumps(
        {
            "ok": True,
            "query_info": {"original": "成都"},
            "chunks": [],
            "context_text": "[1] 宽窄巷子是成都著名景点。",
            "stats": {"degraded": False, "chunk_count": 1},
        },
        ensure_ascii=False,
    )
    from types import SimpleNamespace

    rag.search_for_trip.return_value = SimpleNamespace(
        ok=True,
        context_text="【宽窄巷子】成都必去。大熊猫基地值得一去。",
        chunks=[
            SimpleNamespace(section="宽窄巷子", content="【宽窄巷子】很好玩"),
            SimpleNamespace(section="大熊猫基地", content="【大熊猫基地】看熊猫"),
        ],
        stats=SimpleNamespace(degraded=False),
    )
    return rag


@pytest.fixture
def patch_llm(mock_rag, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr("app.agents.nodes.build_llm", lambda **kw: fake)
    monkeypatch.setattr("app.agents.nodes.default_rag_tool", mock_rag)
    return fake


@pytest.fixture
def agent(mock_rag):
    return TripPlannerAgent(
        rag_tool=mock_rag,
        client=None,
        model="test-model",
        max_tool_rounds=3,
    )


# ---------------------------------------------------------------------------
# 1. draft_to_trip_response 输出结构
# ---------------------------------------------------------------------------

class TestDraftToTripResponse:
    def test_days_cover_request_range(self, agent):
        req = _make_request(days=4)
        trip = agent.draft_to_trip_response(_sample_draft(days=4), req)
        _assert_trip_invariants(trip, req)

    def test_day_numbers_and_dates_sequential(self, agent):
        req = _make_request(days=3)
        trip = agent.draft_to_trip_response(_sample_draft(days=3), req)
        for i, day in enumerate(trip.days):
            assert day.day_number == i + 1
            assert day.itinerary_date == req.start_date + timedelta(days=i)

    def test_place_info_complete(self, agent):
        req = _make_request(days=1)
        trip = agent.draft_to_trip_response(_sample_draft(days=1), req)
        place = trip.days[0].items[0].place
        assert place.name == "景点1-1"
        assert place.category == "景点"
        assert place.ticket_price == 50
        assert place.is_free is False
        assert place.address == "待地图服务补全"
        assert place.coordinate.latitude == 0.0
        assert place.coordinate.longitude == 0.0

    def test_meals_and_hotel_present(self, agent):
        req = _make_request(days=1)
        trip = agent.draft_to_trip_response(_sample_draft(days=1), req)
        day = trip.days[0]
        assert day.breakfast is None
        assert day.lunch is not None and day.lunch.name == "午餐店1"
        assert day.dinner is not None and day.dinner.name == "晚餐店1"
        assert day.hotel is not None and day.hotel.price == 320
        assert day.hotel.address == "待地图服务补全"

    def test_trip_metadata_and_ids(self, agent):
        req = _make_request(days=2)
        trip = agent.draft_to_trip_response(
            _sample_draft(days=2), req, meta={"path": "llm", "validation_warnings": []}
        )
        assert trip.trip_id
        assert trip.model_used == "test-model"
        assert trip.metadata["path"] == "llm"
        assert trip.metadata["validation_warnings"] == []

    def test_json_serializable(self, agent):
        req = _make_request(days=2)
        trip = agent.draft_to_trip_response(_sample_draft(days=2), req)
        raw = trip.model_dump_json(ensure_ascii=False)
        assert json.loads(raw)["destination"] == "成都"


# ---------------------------------------------------------------------------
# 2. enrich_budget_and_summary 输出验证
# ---------------------------------------------------------------------------

class TestEnrichBudget:
    def test_budget_breakdown_consistency(self, agent):
        req = _make_request(days=3, travelers=2)
        draft = _sample_draft(days=3)
        trip = agent.draft_to_trip_response(draft, req)
        enriched = agent.enrich_budget_and_summary(trip, req, draft)
        _assert_budget_consistent(enriched, req)
        _assert_trip_invariants(enriched, req)

    def test_daily_cost_matches_breakdown(self, agent):
        req = _make_request(days=2)
        draft = _sample_draft(days=2)
        trip = agent.enrich_budget_and_summary(
            agent.draft_to_trip_response(draft, req), req, draft
        )
        for day in trip.days:
            assert set(day.cost_breakdown) == {
                "accommodation", "food", "ticket", "transportation",
            }
            assert day.daily_cost == pytest.approx(sum(day.cost_breakdown.values()), abs=0.06)

    def test_budget_level_in_metadata(self, agent):
        req = _make_request(days=2, budget_level=BudgetLevel.LUXURY)
        draft = _sample_draft(days=2)
        trip = agent.enrich_budget_and_summary(
            agent.draft_to_trip_response(draft, req), req, draft
        )
        assert trip.metadata["budget_level"] == "luxury"

    def test_tips_grouped_structure(self, agent):
        req = _make_request(days=2)
        draft = _sample_draft(days=2)
        trip = agent.enrich_budget_and_summary(
            agent.draft_to_trip_response(draft, req), req, draft
        )
        cats = [c.category for c in trip.trip_tips_grouped]
        assert len(cats) == len(TIP_CATEGORIES)
        for cat in trip.trip_tips_grouped:
            assert cat.category in TIP_CATEGORIES
            assert cat.icon == TIP_CATEGORIES[cat.category]
            assert cat.tips
        assert trip.trip_tips
        assert trip.trip_highlights
        assert trip.recommended_foods

    def test_highlights_filled_when_empty(self, agent):
        req = _make_request(days=1)
        draft = DraftItinerary(
            trip_name="t",
            days=[
                DraftDay(
                    day_number=1,
                    items=[DraftItem(name="宽窄巷子", start_time="09:00", end_time="11:00")],
                )
            ],
        )
        trip = agent.enrich_budget_and_summary(
            agent.draft_to_trip_response(draft, req), req, draft
        )
        assert trip.trip_highlights
        assert any("宽窄巷子" in h for h in trip.trip_highlights)


# ---------------------------------------------------------------------------
# 3. validate_and_repair 输出验证
# ---------------------------------------------------------------------------

class TestValidateRepair:
    def test_excluded_keywords_removed(self, agent):
        req = _make_request(days=1, excluded_keywords=["夜店"])
        draft = DraftItinerary(
            days=[
                DraftDay(
                    day_number=1,
                    items=[
                        DraftItem(name="景点A", start_time="09:00", end_time="11:00"),
                        DraftItem(name="夜店酒吧", start_time="14:00", end_time="16:00"),
                    ],
                )
            ]
        )
        fixed, warnings = agent.validate_and_repair(draft, req)
        names = [it.name for it in fixed.days[0].items]
        assert "夜店酒吧" not in names
        assert any("排除" in w for w in warnings)

    def test_max_places_per_day_enforced(self, agent):
        req = _make_request(days=1, max_places_per_day=2)
        draft = DraftItinerary(
            days=[
                DraftDay(
                    day_number=1,
                    items=[
                        DraftItem(name=f"点{i}", start_time=f"{9+i}:00", end_time=f"{10+i}:00")
                        for i in range(4)
                    ],
                )
            ]
        )
        fixed, warnings = agent.validate_and_repair(draft, req)
        assert len(fixed.days[0].items) <= 2
        assert any("裁剪" in w for w in warnings)

    def test_days_aligned_to_request(self, agent):
        req = _make_request(days=3)
        draft = DraftItinerary(days=[DraftDay(day_number=1, items=[])])
        fixed, warnings = agent.validate_and_repair(draft, req)
        assert len(fixed.days) == 3
        assert any("对齐" in w or "缺失" in w for w in warnings)

    def test_empty_draft_warns_all_days_empty(self, agent):
        req = _make_request(days=2)
        draft = DraftItinerary(days=[DraftDay(day_number=1, items=[]), DraftDay(day_number=2, items=[])])
        fixed, warnings = agent.validate_and_repair(draft, req)
        assert not any(d.items for d in fixed.days)
        assert any("无景点" in w for w in warnings)


# ---------------------------------------------------------------------------
# 4. 特殊需求输出验证
# ---------------------------------------------------------------------------

class TestSpecialNeeds:
    def test_kids_notes_and_daily_tips(self, agent):
        req = _make_request(days=1, with_kids=True)
        draft = _sample_draft(days=1)
        trip = agent.draft_to_trip_response(draft, req)
        assert trip.special_needs_notes
        assert any("亲子" in n or "儿童" in n for n in trip.special_needs_notes)
        assert any("孩子" in t or "带娃" in t for t in trip.days[0].daily_tips)

    def test_elderly_notes(self, agent):
        req = _make_request(days=1, with_elderly=True)
        draft = _sample_draft(days=1)
        trip = agent.draft_to_trip_response(draft, req)
        assert trip.special_needs_notes
        assert any("老人" in n or "轻松" in n for n in trip.special_needs_notes)
        assert any("老人" in t for t in trip.days[0].daily_tips)

    def test_disability_notes_and_tips(self, agent):
        req = _make_request(days=1, has_disability=True)
        draft = _sample_draft(days=1)
        trip = agent.draft_to_trip_response(draft, req)
        assert trip.special_needs_notes
        assert any("无障碍" in n for n in trip.special_needs_notes)
        assert any("无障碍" in t for t in trip.days[0].daily_tips)

    def test_no_special_needs_no_notes(self, agent):
        req = _make_request(days=1)
        draft = _sample_draft(days=1)
        trip = agent.draft_to_trip_response(draft, req)
        assert trip.special_needs_notes == []


# ---------------------------------------------------------------------------
# 5. plan() 端到端输出验证
# ---------------------------------------------------------------------------

class TestPlanEndToEnd:
    def test_llm_path_output(self, agent, patch_llm):
        payload = {
            "trip_name": "成都三日游",
            "days": [],
            "trip_highlights": ["火锅"],
            "trip_tips": [],
            "recommended_foods": [],
        }
        for i in range(1, 4):
            payload["days"].append(
                {
                    "day_number": i,
                    "day_theme": f"主题{i}",
                    "items": [
                        {
                            "start_time": "09:00",
                            "end_time": "11:00",
                            "name": f"景点{i}-1",
                            "category": "景点",
                            "activity": "游览",
                        },
                        {
                            "start_time": "14:00",
                            "end_time": "16:30",
                            "name": f"景点{i}-2",
                            "category": "景点",
                            "activity": "游览",
                        },
                    ],
                    "lunch": {"name": f"午餐{i}", "cuisine_type": "川菜", "avg_price": 80},
                    "dinner": {"name": f"晚餐{i}", "cuisine_type": "火锅", "avg_price": 100},
                    "hotel": {"name": f"酒店{i}", "hotel_type": "舒适型", "price": 320},
                }
            )
        patch_llm.responses = [AIMessage(content=json.dumps(payload, ensure_ascii=False))]

        req = _make_request(days=3)
        trip = agent.plan(req, context="已有攻略", use_tools=False, allow_fallback=False)
        _assert_trip_invariants(trip, req)
        assert trip.metadata["path"] == "llm"
        assert trip.metadata["validation_warnings"] == []
        assert trip.metadata["needs_enrichment"] is False
        assert trip.metadata["model_used"] == "test-model"
        assert trip.metadata["generation_time"] >= 0

    def test_edit_day_output(self, agent, patch_llm):
        payload = {
            "trip_name": "成都三日游",
            "days": [],
            "trip_highlights": ["火锅"],
            "trip_tips": [],
            "recommended_foods": [],
        }
        for i in range(1, 4):
            payload["days"].append(
                {
                    "day_number": i,
                    "day_theme": f"主题{i}",
                    "items": [
                        {
                            "start_time": "09:00",
                            "end_time": "11:00",
                            "name": f"景点{i}-1",
                            "category": "景点",
                            "activity": "游览",
                        },
                        {
                            "start_time": "14:00",
                            "end_time": "16:30",
                            "name": f"景点{i}-2",
                            "category": "景点",
                            "activity": "游览",
                        },
                    ],
                    "lunch": {"name": f"午餐{i}", "cuisine_type": "川菜", "avg_price": 80},
                    "dinner": {"name": f"晚餐{i}", "cuisine_type": "火锅", "avg_price": 100},
                    "hotel": {"name": f"酒店{i}", "hotel_type": "舒适型", "price": 320},
                }
            )
        patch_llm.responses = [AIMessage(content=json.dumps(payload, ensure_ascii=False))]

        req = _make_request(days=3)
        trip = agent.plan(req, context="c", use_tools=False, allow_fallback=False)
        original_day2 = [it.place.name for it in trip.days[1].items]
        original_day3 = [it.place.name for it in trip.days[2].items]

        edited_payload = {
            "days": [
                {
                    "day_number": 1,
                    "day_theme": "新主题",
                    "items": [
                        {
                            "start_time": "10:00",
                            "end_time": "12:00",
                            "name": "新景点X",
                            "category": "景点",
                            "activity": "打卡",
                        }
                    ],
                    "lunch": {"name": "新午餐", "cuisine_type": "川菜", "avg_price": 70},
                }
            ],
            "trip_highlights": ["新亮点"],
            "trip_tips": [],
        }
        patch_llm._idx = 0
        patch_llm.invoke_count = 0
        patch_llm.responses = [AIMessage(content=json.dumps(edited_payload, ensure_ascii=False))]

        updated = agent.edit_day(trip, 1, "换成更轻松的安排", request=req, allow_fallback=False)
        assert updated.metadata["path"] == "edit_day"
        assert updated.metadata["edited_day"] == 1
        _assert_trip_invariants(updated, req)
        assert any(it.place.name == "新景点X" for it in updated.days[0].items)
        assert [it.place.name for it in updated.days[1].items] == original_day2
        assert [it.place.name for it in updated.days[2].items] == original_day3

    def test_fallback_output(self, agent, mock_rag, monkeypatch):
        broken = MagicMock()
        broken.invoke.side_effect = RuntimeError("llm down")
        broken.bind_tools.return_value = broken
        monkeypatch.setattr("app.agents.nodes.build_llm", lambda **kw: broken)
        monkeypatch.setattr("app.agents.nodes.default_rag_tool", mock_rag)

        req = _make_request(days=2)
        trip = agent.plan(req, allow_fallback=True)
        _assert_trip_invariants(trip, req)
        assert trip.metadata["path"] == "fallback"
        assert trip.metadata.get("fallback_reason") is not None
        assert all(day.items for day in trip.days)


# ---------------------------------------------------------------------------
# 6. B 类动态城市候选池输出验证
# ---------------------------------------------------------------------------

class TestCandidatePoolOutput:
    def _candidate_index(self) -> dict[str, Any]:
        return {
            "s1": {
                "name": "宽窄巷子",
                "address": "青羊区长顺上街127号",
                "coordinate": {"latitude": 30.6699, "longitude": 104.0546},
                "district": "青羊区",
                "category": "景点",
                "rating": 4.6,
                "cost": 0,
                "photos": ["http://img/1.jpg"],
                "tags": ["老街"],
            },
            "s2": {
                "name": "武侯祠",
                "address": "武侯区武侯祠大街231号",
                "coordinate": {"latitude": 30.6454, "longitude": 104.0479},
                "district": "武侯区",
                "category": "景点",
                "rating": 4.5,
                "cost": 50,
                "photos": ["http://img/2.jpg"],
                "tags": ["古迹"],
            },
        }

    def test_real_coords_and_place_ids(self, agent):
        req = _make_request(days=1)
        idx = self._candidate_index()
        draft = DraftItinerary(
            days=[
                DraftDay(
                    day_number=1,
                    items=[
                        DraftItem(
                            name="宽窄巷子", place_id="s1",
                            start_time="09:00", end_time="11:00",
                        ),
                        DraftItem(
                            name="武侯祠", place_id="s2",
                            start_time="14:00", end_time="16:30",
                        ),
                    ],
                    lunch=DraftMeal(name="午餐", avg_price=80),
                    dinner=DraftMeal(name="晚餐", avg_price=100),
                    hotel=DraftHotel(name="酒店", price=300),
                )
            ]
        )
        trip = agent.draft_to_trip_response(draft, req, candidate_index=idx)
        places = [it.place for it in trip.days[0].items]
        assert [p.place_id for p in places] == ["s1", "s2"]
        for p in places:
            assert p.address != "待地图服务补全"
            assert p.coordinate.latitude != 0.0
            assert p.coordinate.longitude != 0.0
        assert places[0].images == ["http://img/1.jpg"]
        assert places[0].rating == 4.6

    def test_food_hotel_backfill(self, agent):
        req = _make_request(days=1)
        idx = self._candidate_index()
        food = [
            {"place_id": "f1", "name": "火锅店", "category": "火锅", "cost": 80, "rating": 4.5},
            {"place_id": "f2", "name": "川菜馆", "category": "川菜", "cost": 60, "rating": 4.2},
        ]
        hotel = [{"place_id": "h1", "name": "春熙路酒店", "cost": 400, "rating": 4.7}]
        draft = DraftItinerary(
            days=[
                DraftDay(
                    day_number=1,
                    items=[DraftItem(name="宽窄巷子", place_id="s1", start_time="09:00", end_time="11:00")],
                )
            ]
        )
        fixed, warnings = agent.validate_and_repair(
            draft, req,
            candidate_index=idx,
            food_candidates=food,
            hotel_candidates=hotel,
        )
        day = fixed.days[0]
        assert day.lunch is not None and day.lunch.place_id in {"f1", "f2"}
        assert day.dinner is not None and day.dinner.place_id in {"f1", "f2"}
        assert day.hotel is not None and day.hotel.place_id == "h1"
        assert any("补选" in w for w in warnings)

    def test_cross_cluster_warning(self, agent):
        req = _make_request(days=1)
        idx = self._candidate_index()
        clusters = {"青羊区": ["s1"], "武侯区": ["s2"]}
        draft = DraftItinerary(
            days=[
                DraftDay(
                    day_number=1,
                    items=[
                        DraftItem(name="宽窄巷子", place_id="s1", start_time="09:00", end_time="11:00"),
                        DraftItem(name="武侯祠", place_id="s2", start_time="14:00", end_time="16:30"),
                    ],
                )
            ]
        )
        fixed, warnings = agent.validate_and_repair(
            draft, req, candidate_index=idx, district_clusters=clusters
        )
        assert any("跨区域" in w for w in warnings)
        assert len(fixed.days[0].items) == 2

    def test_invalid_place_id_repaired_or_warned(self, agent):
        req = _make_request(days=1)
        idx = self._candidate_index()
        draft = DraftItinerary(
            days=[
                DraftDay(
                    day_number=1,
                    items=[
                        DraftItem(name="宽窄巷子", place_id="s1", start_time="09:00", end_time="11:00"),
                        DraftItem(name="不存在景点", place_id="zzz", start_time="14:00", end_time="16:30"),
                    ],
                )
            ]
        )
        fixed, warnings = agent.validate_and_repair(
            draft, req, candidate_index=idx
        )
        assert any("不在候选池" in w for w in warnings)
        assert fixed.days[0].items[0].place_id == "s1"


