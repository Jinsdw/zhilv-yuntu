"""
智旅云图 - LangGraph 主图与节点单元测试

测试范围：
- 图可正常编译（build_planner_graph / build_edit_day_graph）
- 路由函数（route_after_llm / route_after_parse 等）决策正确
- 单个节点的纯函数行为（prefetch_rag / parse_draft / validate_repair 等）
- 端到端调用：用 FakeLLM 替换 build_llm，验证主图能产出 TripResponse

不打真实 LLM API；不打 ChromaDB（rag_tool 用 mock）。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents import planner_graph
from app.agents.nodes import (
    build_trip_node,
    enrich_budget_node,
    fallback_node,
    llm_plan_node,
    parse_draft_node,
    prefetch_rag_node,
    repair_json_node,
    route_after_build,
    route_after_llm,
    route_after_parse,
    route_after_validate,
    validate_repair_node,
)
from app.agents.rag_tool import RAGToolResult, RAGQueryInfo, RAGToolStats
from app.agents.state import PlannerState
from app.agents.trip_planner_agent import (
    DraftDay,
    DraftItem,
    DraftItinerary,
    DraftMeal,
    DraftHotel,
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
                "lunch": {"name": f"午餐店{i}", "cuisine_type": "川菜", "avg_price": 80},
                "dinner": {"name": f"晚餐店{i}", "cuisine_type": "火锅", "avg_price": 100},
                "hotel": {"name": f"酒店{i}", "hotel_type": "舒适型", "price": 320},
            }
        )
    return {
        "trip_name": "成都美食三日游",
        "days": out_days,
        "trip_highlights": ["火锅", "熊猫"],
        "trip_tips": ["提前预约"],
        "recommended_foods": ["火锅", "串串"],
    }


class FakeLLM:
    """
    模拟 LangChain ChatModel，按预设序列返回 AIMessage。
    支持 bind_tools（直接返回 self，不影响预设）。
    """

    def __init__(self, responses: list):
        self.responses = list(responses)
        self._idx = 0
        self.invoke_count = 0

    def invoke(self, messages, **kwargs):
        self.invoke_count += 1
        if self._idx >= len(self.responses):
            # 默认返回最后一个响应，避免循环耗尽时报错
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


def _make_state(**kwargs) -> dict:
    """构造 PlannerState 的最小可用字典。"""
    base: dict = {
        "request": _make_request(),
        "context": None,
        "candidate_places": None,
        "use_tools": True,
        "allow_fallback": True,
        "meta": {
            "tool_rounds": 0,
            "rag_degraded": False,
            "validation_warnings": [],
            "path": "llm",
            "needs_enrichment": True,
        },
        "messages": [],
        "validation_warnings": [],
        "repair_attempts": 0,
    }
    base.update(kwargs)
    return base


@pytest.fixture
def mock_rag_tool():
    """模拟 RAGTool：search_for_trip 返回 RAGToolResult。"""
    rag = MagicMock()
    rag.execute.return_value = RAGToolResult(
        ok=True,
        query_info=RAGQueryInfo(original="成都"),
        chunks=[],
        context_text="[1] 宽窄巷子是成都著名景点。",
        stats=RAGToolStats(degraded=False, chunk_count=1),
    ).model_dump_json(ensure_ascii=False)

    rag.search_for_trip.return_value = RAGToolResult(
        ok=True,
        query_info=RAGQueryInfo(original="成都"),
        chunks=[],
        context_text="【宽窄巷子】成都必去。大熊猫基地值得一去。",
        stats=RAGToolStats(degraded=False, chunk_count=2),
    )
    return rag


@pytest.fixture
def patch_default_rag(mock_rag_tool):
    """patch nodes.py 与 trip_planner_agent.py 中引用的 default_rag_tool。"""
    with patch("app.agents.nodes.default_rag_tool", mock_rag_tool), \
         patch("app.agents.trip_planner_agent.trip_planner_agent._rag_tool", mock_rag_tool):
        yield mock_rag_tool


# ---------------------------------------------------------------------------
# 图编译测试
# ---------------------------------------------------------------------------

class TestGraphCompile:
    def test_planner_graph_compiles(self):
        g = planner_graph.build_planner_graph()
        assert g is not None
        # 编译后的图应可调用 invoke
        assert hasattr(g, "invoke")

    def test_edit_day_graph_compiles(self):
        g = planner_graph.build_edit_day_graph()
        assert g is not None
        assert hasattr(g, "invoke")

    def test_get_planner_graph_singleton(self):
        g1 = planner_graph.get_planner_graph()
        g2 = planner_graph.get_planner_graph()
        assert g1 is g2


# ---------------------------------------------------------------------------
# 路由函数测试
# ---------------------------------------------------------------------------

class TestRouters:
    def test_route_after_llm_with_tool_calls(self):
        state = {
            "messages": [AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}])],
            "meta": {"tool_rounds": 1},
        }
        assert route_after_llm(state) == "tools"

    def test_route_after_llm_without_tool_calls(self):
        state = {"messages": [AIMessage(content='{"days":[]}')], "meta": {}}
        assert route_after_llm(state) == "parse"

    def test_route_after_llm_with_error(self):
        state = {"messages": [], "error": "boom", "meta": {}}
        assert route_after_llm(state) == "fallback"

    def test_route_after_llm_force_parse_when_exceed_max_rounds(self):
        state = {
            "messages": [AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}])],
            "meta": {"tool_rounds": 4},
        }
        assert route_after_llm(state) == "parse"

    def test_route_after_parse_with_draft(self):
        state = {"draft": DraftItinerary(days=[]), "repair_attempts": 0}
        assert route_after_parse(state) == "validate"

    def test_route_after_parse_no_draft_first_attempt(self):
        state = {"draft": None, "repair_attempts": 0}
        assert route_after_parse(state) == "repair"

    def test_route_after_parse_no_draft_second_attempt(self):
        state = {"draft": None, "repair_attempts": 1}
        assert route_after_parse(state) == "fallback"

    def test_route_after_validate_ok(self):
        assert route_after_validate({"error": None}) == "build_trip"

    def test_route_after_validate_error_allow_fallback(self):
        assert route_after_validate({"error": "x", "allow_fallback": True}) == "fallback"

    def test_route_after_validate_error_no_fallback(self):
        assert route_after_validate({"error": "x", "allow_fallback": False}) == "build_trip"

    def test_route_after_build_ok(self):
        assert route_after_build({"error": None}) == "enrich"

    def test_route_after_build_error_allow_fallback(self):
        assert route_after_build({"error": "x", "allow_fallback": True}) == "fallback"


# ---------------------------------------------------------------------------
# 节点测试
# ---------------------------------------------------------------------------

class TestPrefetchRag:
    def test_skip_when_context_provided(self, patch_default_rag):
        state = _make_state(context="已有攻略", use_tools=False)
        out = prefetch_rag_node(state)
        assert out["rag_context"] == "已有攻略"
        # 不应触发 rag_tool.search_for_trip
        assert not patch_default_rag.search_for_trip.called

    def test_skip_when_use_tools(self, patch_default_rag):
        state = _make_state(context=None, use_tools=True)
        out = prefetch_rag_node(state)
        assert out["rag_context"] == ""
        assert not patch_default_rag.search_for_trip.called

    def test_prefetch_when_no_context_and_no_tools(self, patch_default_rag):
        state = _make_state(context=None, use_tools=False)
        out = prefetch_rag_node(state)
        assert "宽窄巷子" in out["rag_context"]
        assert patch_default_rag.search_for_trip.called


class TestLlmPlanNode:
    def test_invoke_returns_ai_message(self):
        fake_llm = FakeLLM([AIMessage(content='{"days":[]}')])
        state = _make_state()
        with patch("app.agents.nodes.build_llm", return_value=fake_llm):
            out = llm_plan_node(state)
        assert "messages" in out
        assert isinstance(out["messages"][0], AIMessage)
        assert out["messages"][0].content == '{"days":[]}'

    def test_records_error_on_exception(self):
        fake_llm = MagicMock()
        fake_llm.invoke.side_effect = RuntimeError("boom")
        fake_llm.bind_tools.return_value = fake_llm
        state = _make_state()
        with patch("app.agents.nodes.build_llm", return_value=fake_llm):
            out = llm_plan_node(state)
        assert out.get("error") == "boom"


class TestParseDraftNode:
    def test_parse_success(self):
        payload = _sample_draft_json(days=2)
        state = _make_state(messages=[AIMessage(content=json.dumps(payload))])
        out = parse_draft_node(state)
        assert out.get("draft") is not None
        assert len(out["draft"].days) == 2
        assert out.get("error") is None

    def test_parse_failure_records_error(self):
        state = _make_state(messages=[AIMessage(content="not a json")])
        out = parse_draft_node(state)
        assert out.get("draft") is None
        assert "parse_error" in out["meta"]

    def test_parse_empty_messages(self):
        state = _make_state(messages=[])
        out = parse_draft_node(state)
        assert out.get("error") is not None


class TestValidateRepairNode:
    def test_validate_passes(self):
        payload = _sample_draft_json(days=2, places_per_day=2)
        draft = DraftItinerary.model_validate(payload)
        state = _make_state(draft=draft)
        out = validate_repair_node(state)
        assert out.get("draft") is not None
        assert out.get("error") is None

    def test_validate_no_draft(self):
        state = _make_state(draft=None)
        out = validate_repair_node(state)
        assert out.get("error") is not None


class TestBuildTripNode:
    def test_build_success(self):
        payload = _sample_draft_json(days=2, places_per_day=2)
        draft = DraftItinerary.model_validate(payload)
        # request 天数应与 draft 一致
        state = _make_state(request=_make_request(days=2), draft=draft)
        out = build_trip_node(state)
        assert out.get("trip") is not None
        assert out["trip"].total_days == 2


class TestEnrichBudgetNode:
    def test_enrich_adds_budget(self):
        payload = _sample_draft_json(days=2, places_per_day=2)
        draft = DraftItinerary.model_validate(payload)
        state = _make_state(request=_make_request(days=2), draft=draft)
        built = build_trip_node(state)
        state.update(built)
        out = enrich_budget_node(state)
        assert out["trip"].budget.total_budget > 0
        assert out["trip"].metadata.get("needs_enrichment") is False


class TestFallbackNode:
    def test_fallback_produces_trip(self, patch_default_rag):
        state = _make_state(error="llm failed")
        out = fallback_node(state)
        assert out.get("trip") is not None
        assert out["trip"].total_days == 3
        assert out["meta"]["path"] == "fallback"
        assert out["meta"].get("fallback_reason") == "llm failed"


# ---------------------------------------------------------------------------
# 端到端测试（patch LLM 工厂）
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_plan_graph_success_with_context(self, patch_default_rag):
        """有 context 时不需要工具，直接 LLM → parse → validate → build → enrich。"""
        payload = _sample_draft_json(days=3, places_per_day=2)
        fake_llm = FakeLLM([AIMessage(content=json.dumps(payload, ensure_ascii=False))])

        state = _make_state(context="已有攻略", use_tools=False, allow_fallback=False)
        with patch("app.agents.nodes.build_llm", return_value=fake_llm):
            graph = planner_graph.build_planner_graph()
            final = graph.invoke(state, {"recursion_limit": 24})

        trip = final.get("trip")
        assert trip is not None
        assert trip.destination == "成都"
        assert trip.total_days == 3
        assert trip.budget.total_budget > 0
        assert fake_llm.invoke_count >= 1

    def test_plan_graph_tool_call_loop(self, patch_default_rag):
        """LLM 先调工具，再返回最终 JSON。"""
        payload = _sample_draft_json(days=2, places_per_day=2)
        # 第一轮：tool_calls；第二轮：最终 JSON
        fake_llm = FakeLLM([
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "search_travel_guides",
                    "args": {"query": "成都行程", "city": "成都"},
                    "id": "call_1",
                }],
            ),
            AIMessage(content=json.dumps(payload, ensure_ascii=False)),
        ])

        state = _make_state(
            request=_make_request(days=2),
            context=None,
            use_tools=True,
            allow_fallback=False,
        )
        with patch("app.agents.nodes.build_llm", return_value=fake_llm):
            graph = planner_graph.build_planner_graph()
            final = graph.invoke(state, {"recursion_limit": 24})

        trip = final.get("trip")
        assert trip is not None
        assert trip.total_days == 2
        # 至少调了两次 LLM
        assert fake_llm.invoke_count >= 2

    def test_plan_graph_fallback_on_llm_error(self, patch_default_rag):
        """LLM 抛异常 → 走 fallback。"""
        fake_llm = MagicMock()
        fake_llm.invoke.side_effect = RuntimeError("llm down")
        fake_llm.bind_tools.return_value = fake_llm

        state = _make_state(context=None, use_tools=True, allow_fallback=True)
        with patch("app.agents.nodes.build_llm", return_value=fake_llm):
            graph = planner_graph.build_planner_graph()
            final = graph.invoke(state, {"recursion_limit": 24})

        trip = final.get("trip")
        assert trip is not None
        assert final["meta"].get("path") == "fallback"

    def test_plan_graph_fenced_json(self, patch_default_rag):
        """模型返回 ```json fenced 内容，应能解析。"""
        payload = _sample_draft_json(days=2)
        content = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
        fake_llm = FakeLLM([AIMessage(content=content)])

        state = _make_state(
            request=_make_request(days=2),
            context="ctx",
            use_tools=False,
            allow_fallback=False,
        )
        with patch("app.agents.nodes.build_llm", return_value=fake_llm):
            graph = planner_graph.build_planner_graph()
            final = graph.invoke(state, {"recursion_limit": 24})

        trip = final.get("trip")
        assert trip is not None
        assert len(trip.days) == 2
