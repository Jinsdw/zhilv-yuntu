"""
智旅云图 - 行程规划 Agent 单元测试

全部 mock LLM 与 rag_tool，不打真实 API。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agents.trip_planner_agent import (
    DraftDay,
    DraftItem,
    DraftItinerary,
    PlannerParseError,
    TripPlannerAgent,
    build_user_prompt,
    extract_json_object,
)
from app.models.schemas import (
    BudgetLevel,
    TravelStyle,
    TripRequest,
    TripResponse,
)


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


def _sample_draft_json(days: int = 3, places_per_day: int = 2) -> dict:
    out_days = []
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
        out_days.append(
            {
                "day_number": i,
                "day_theme": f"主题{i}",
                "items": items,
                "lunch": {
                    "name": f"午餐店{i}",
                    "cuisine_type": "川菜",
                    "avg_price": 80,
                },
                "dinner": {
                    "name": f"晚餐店{i}",
                    "cuisine_type": "火锅",
                    "avg_price": 100,
                },
                "hotel": {
                    "name": f"酒店{i}",
                    "hotel_type": "舒适型",
                    "price": 320,
                },
            }
        )
    return {
        "trip_name": "成都美食三日游",
        "days": out_days,
        "trip_highlights": ["火锅", "熊猫"],
        "trip_tips": ["提前预约"],
        "recommended_foods": ["火锅", "串串"],
    }


class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


class _FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = _FakeFunction(name, arguments)


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
def mock_client():
    client = MagicMock()
    return client


@pytest.fixture
def agent(mock_rag, mock_client):
    return TripPlannerAgent(
        rag_tool=mock_rag,
        client=mock_client,
        model="test-model",
        max_tool_rounds=3,
    )


class TestPrompt:
    def test_build_user_prompt_contains_constraints(self):
        req = _make_request()
        text = build_user_prompt(req, context="攻略片段ABC")
        assert "成都" in text
        assert "火锅" in text
        assert "夜店" in text
        assert "攻略片段ABC" in text
        assert str(req.max_places_per_day) in text


class TestExtractJson:
    def test_plain_json(self):
        data = extract_json_object('{"a": 1}')
        assert data["a"] == 1

    def test_fenced_json(self):
        data = extract_json_object('```json\n{"trip_name": "x"}\n```')
        assert data["trip_name"] == "x"

    def test_embedded_json(self):
        data = extract_json_object('说明如下：\n{"days": []}\n结束')
        assert "days" in data

    def test_empty_raises(self):
        with pytest.raises(PlannerParseError):
            extract_json_object("   ")


class TestValidateAndRepair:
    def test_trim_places_and_align_days(self, agent):
        req = _make_request(days=2, max_places_per_day=2)
        draft = DraftItinerary(
            days=[
                DraftDay(
                    day_number=1,
                    items=[
                        DraftItem(name="A", start_time="09:00", end_time="10:00"),
                        DraftItem(name="夜店酒吧", start_time="10:30", end_time="11:30"),
                        DraftItem(name="B", start_time="12:00", end_time="13:00"),
                        DraftItem(name="C", start_time="14:00", end_time="15:00"),
                    ],
                )
            ]
        )
        fixed, warnings = agent.validate_and_repair(draft, req)
        assert len(fixed.days) == 2
        assert all(len(d.items) <= 2 for d in fixed.days)
        assert not any("夜店" in it.name for d in fixed.days for it in d.items)
        assert any("裁剪" in w or "排除" in w or "对齐" in w or "缺失" in w for w in warnings)

    def test_fix_overlapping_times(self, agent):
        req = _make_request(days=1, max_places_per_day=5)
        draft = DraftItinerary(
            days=[
                DraftDay(
                    day_number=1,
                    items=[
                        DraftItem(name="早", start_time="09:00", end_time="12:00"),
                        DraftItem(name="冲突", start_time="10:00", end_time="11:00"),
                    ],
                )
            ]
        )
        fixed, warnings = agent.validate_and_repair(draft, req)
        assert len(fixed.days[0].items) == 2
        assert any("重叠" in w or "修正" in w for w in warnings)


class TestPlanWithLLM:
    def test_plan_success_without_tools(self, agent, mock_client):
        payload = _sample_draft_json(days=3, places_per_day=2)
        mock_client.chat.completions.create.return_value = _FakeResponse(
            _FakeMessage(content=json.dumps(payload, ensure_ascii=False))
        )
        req = _make_request(days=3)
        trip = agent.plan(req, context="已有攻略", use_tools=True, allow_fallback=False)
        assert isinstance(trip, TripResponse)
        assert trip.destination == "成都"
        assert trip.total_days == 3
        assert len(trip.days) == 3
        assert trip.budget.total_budget > 0
        assert trip.model_used == "test-model"
        assert trip.metadata.get("needs_enrichment") is True
        # 有预取 context 时不应强制 tool
        assert trip.days[0].items

    def test_tool_call_loop(self, agent, mock_client, mock_rag):
        payload = _sample_draft_json(days=2, places_per_day=2)
        tool_msg = _FakeMessage(
            content="",
            tool_calls=[
                _FakeToolCall(
                    "call_1",
                    "search_travel_guides",
                    json.dumps({"query": "成都行程", "city": "成都"}),
                )
            ],
        )
        final_msg = _FakeMessage(content=json.dumps(payload, ensure_ascii=False))
        mock_client.chat.completions.create.side_effect = [
            _FakeResponse(tool_msg),
            _FakeResponse(final_msg),
        ]
        req = _make_request(days=2)
        trip = agent.plan(req, context=None, use_tools=True, allow_fallback=False)
        assert trip.total_days == 2
        assert mock_rag.execute.called
        assert trip.metadata.get("tool_rounds") == 1

    def test_fenced_json_parse(self, agent, mock_client):
        payload = _sample_draft_json(days=2)
        content = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
        mock_client.chat.completions.create.return_value = _FakeResponse(
            _FakeMessage(content=content)
        )
        trip = agent.plan(
            _make_request(days=2),
            context="ctx",
            allow_fallback=False,
        )
        assert len(trip.days) == 2


class TestBudget:
    def test_economy_cheaper_than_luxury(self, agent, mock_client):
        payload = _sample_draft_json(days=2, places_per_day=1)
        mock_client.chat.completions.create.return_value = _FakeResponse(
            _FakeMessage(content=json.dumps(payload, ensure_ascii=False))
        )
        # 无酒店时靠 daily_base 区分；这里去掉酒店看等级差
        for day in payload["days"]:
            day.pop("hotel", None)
            day.pop("lunch", None)
            day.pop("dinner", None)

        eco = agent.plan(
            _make_request(days=2, budget_level=BudgetLevel.ECONOMY),
            context="c",
            allow_fallback=False,
        )
        mock_client.chat.completions.create.return_value = _FakeResponse(
            _FakeMessage(content=json.dumps(payload, ensure_ascii=False))
        )
        lux = agent.plan(
            _make_request(days=2, budget_level=BudgetLevel.LUXURY),
            context="c",
            allow_fallback=False,
        )
        assert lux.budget.total_budget > eco.budget.total_budget


class TestEditDay:
    def test_edit_only_target_day(self, agent, mock_client):
        payload = _sample_draft_json(days=3, places_per_day=2)
        mock_client.chat.completions.create.return_value = _FakeResponse(
            _FakeMessage(content=json.dumps(payload, ensure_ascii=False))
        )
        req = _make_request(days=3)
        trip = agent.plan(req, context="c", allow_fallback=False)
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
        mock_client.chat.completions.create.return_value = _FakeResponse(
            _FakeMessage(content=json.dumps(edited_payload, ensure_ascii=False))
        )
        updated = agent.edit_day(trip, 1, "换成更轻松的安排", request=req, allow_fallback=False)
        assert any(it.place.name == "新景点X" for it in updated.days[0].items)
        assert [it.place.name for it in updated.days[1].items] == original_day2
        assert [it.place.name for it in updated.days[2].items] == original_day3


class TestFallback:
    def test_fallback_when_llm_unavailable(self, mock_rag):
        agent = TripPlannerAgent(rag_tool=mock_rag, client=None, model="test")
        trip = agent.plan(_make_request(days=2), allow_fallback=True)
        assert trip.total_days == 2
        assert trip.metadata.get("path") == "fallback"
        assert sum(len(d.items) for d in trip.days) >= 1
        assert trip.budget.total_budget > 0

    def test_fallback_disabled_raises(self, mock_rag):
        agent = TripPlannerAgent(rag_tool=mock_rag, client=None, model="test")
        with pytest.raises(Exception):
            agent.plan(_make_request(days=2), allow_fallback=False)

    def test_fallback_on_llm_error(self, mock_rag):
        broken = MagicMock()
        broken.chat.completions.create.side_effect = RuntimeError("llm down")
        agent = TripPlannerAgent(rag_tool=mock_rag, client=broken, model="test")
        trip = agent.plan(_make_request(days=2), context="c", allow_fallback=True)
        assert trip.metadata.get("path") == "fallback"


class TestDraftToResponse:
    def test_placeholder_coords(self, agent):
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
        trip = agent.draft_to_trip_response(draft, req, meta={"needs_enrichment": True})
        place = trip.days[0].items[0].place
        assert place.address == "待地图服务补全"
        assert place.coordinate.latitude == 0.0
