"""
智旅云图 - RAG 工具单元测试

全部 mock Retriever.retrieve，不打真实 Chroma / LLM。
"""

import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agents.rag_tool import (
    TOOL_NAME,
    GuideCategory,
    GuideCity,
    RAGTool,
    SearchGuidesArgs,
    _normalize_category,
    _normalize_city,
    _truncate_content,
)


def _make_doc(
    content: str,
    *,
    city: str = "成都",
    category: str = "景点",
    section: str = "核心景点",
    subsection: str = "宽窄巷子",
    source_file: str = "chengdu_guide.md",
    score: float = 0.8,
) -> dict:
    return {
        "id": f"id-{hash(content) % 100000}",
        "document": content,
        "metadata": {
            "city": city,
            "category": category,
            "section": section,
            "subsection": subsection,
            "source_file": source_file,
        },
        "rerank_score": score,
        "rrf_score": score,
        "similarity": score,
    }


@pytest.fixture
def mock_retriever():
    r = MagicMock()
    r.preprocessor = MagicMock()
    r.preprocessor.extract_city.side_effect = lambda q: (
        "成都" if "成都" in q else ("北京" if "北京" in q else None)
    )
    return r


@pytest.fixture
def tool(mock_retriever):
    return RAGTool(retriever=mock_retriever)


class TestNormalize:
    def test_normalize_city_alias(self):
        assert _normalize_city("Chengdu") == "成都"
        assert _normalize_city("成都市") == "成都"
        assert _normalize_city("纽约") is None

    def test_normalize_category_intent(self):
        assert _normalize_category("scenic_spot") == "景点"
        assert _normalize_category("dining") == "餐饮"
        assert _normalize_category("餐饮") == "餐饮"
        assert _normalize_category("餐厅") == "餐饮"


class TestAsOpenAITools:
    def test_schema_contains_tool(self, tool):
        tools = tool.as_openai_tools()
        assert len(tools) == 1
        fn = tools[0]["function"]
        assert fn["name"] == TOOL_NAME
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "query" in params["properties"]
        assert "query" in params.get("required", [])

    def test_city_and_category_enum(self, tool):
        params = tool.as_openai_tools()[0]["function"]["parameters"]
        city_schema = params["properties"]["city"]
        # anyOf 或直接 enum
        text = json.dumps(city_schema, ensure_ascii=False)
        assert "成都" in text
        assert "北京" in text
        cat_schema = params["properties"]["category"]
        cat_text = json.dumps(cat_schema, ensure_ascii=False)
        assert "景点" in cat_text
        assert "餐饮" in cat_text

    def test_no_defs_left(self, tool):
        params = tool.as_openai_tools()[0]["function"]["parameters"]
        assert "$defs" not in params
        assert "definitions" not in params


class TestExecute:
    def test_unknown_tool(self, tool):
        raw = tool.execute("other_tool", {"query": "x"})
        data = json.loads(raw)
        assert data["ok"] is False
        assert "未知工具" in data["error"]

    def test_invalid_json(self, tool):
        raw = tool.execute(TOOL_NAME, "{not-json")
        data = json.loads(raw)
        assert data["ok"] is False

    def test_top_k_clamped(self, mock_retriever, tool):
        mock_retriever.retrieve.return_value = {
            "results": [_make_doc("宽窄巷子是成都著名街区，适合散步拍照。")],
            "query_info": {
                "original": "成都景点",
                "city": "成都",
                "days": None,
                "intent": "scenic_spot",
                "confidence": 0.9,
            },
            "cached": False,
        }
        raw = tool.execute(
            TOOL_NAME,
            {"query": "成都景点", "city": "成都", "top_k": 99},
        )
        data = json.loads(raw)
        assert data["ok"] is True
        # 调用时 top_k 应被钳制到 8
        call_kwargs = mock_retriever.retrieve.call_args.kwargs
        assert call_kwargs["top_k"] <= 8

    def test_invalid_city_ignored(self, mock_retriever, tool):
        mock_retriever.retrieve.return_value = {
            "results": [_make_doc("故宫是北京核心景点，建议预留半天时间。", city="北京")],
            "query_info": {
                "original": "北京景点",
                "city": None,
                "days": None,
                "intent": "scenic_spot",
                "confidence": 0.8,
            },
            "cached": False,
        }
        raw = tool.execute(
            TOOL_NAME,
            {"query": "北京景点", "city": "纽约"},
        )
        data = json.loads(raw)
        assert data["ok"] is True
        # city 过滤应为 None
        assert mock_retriever.retrieve.call_args.kwargs["city"] is None


class TestSearchGuides:
    def test_single_path_success(self, mock_retriever, tool):
        mock_retriever.retrieve.return_value = {
            "results": [
                _make_doc("宽窄巷子是成都著名街区，适合散步拍照。", category="景点"),
                _make_doc("火锅是成都必尝美食，人均约100元。", category="餐饮", subsection="火锅"),
            ],
            "query_info": {
                "original": "成都美食",
                "city": "成都",
                "days": None,
                "intent": "dining",
                "confidence": 0.85,
            },
            "cached": True,
        }
        result = tool.search_guides(
            SearchGuidesArgs(query="成都美食", city=GuideCity.CHENGDU, category=GuideCategory.DINING)
        )
        assert result.ok is True
        assert result.stats.chunk_count >= 1
        assert result.context_text.startswith("【攻略检索】")
        assert "[1]" in result.context_text
        assert result.query_info.city == "成都"

    def test_empty_then_degraded_flag(self, mock_retriever, tool):
        mock_retriever.retrieve.return_value = {
            "results": [],
            "query_info": {
                "original": "火星旅行",
                "city": None,
                "days": None,
                "intent": "scenic_spot",
                "confidence": 0.3,
            },
            "cached": False,
        }
        result = tool.search_guides(query="火星旅行")
        assert result.ok is True
        assert result.stats.degraded is True
        assert result.chunks == []
        assert result.error is not None

    def test_fallback_drop_category(self, mock_retriever, tool):
        # 第一次带 category 空，第二次去掉 category 有结果
        mock_retriever.retrieve.side_effect = [
            {
                "results": [],
                "query_info": {
                    "original": "成都",
                    "city": "成都",
                    "intent": "dining",
                    "confidence": 0.5,
                },
                "cached": False,
            },
            {
                "results": [_make_doc("成都火锅推荐若干家老店。", category="餐饮")],
                "query_info": {
                    "original": "成都",
                    "city": "成都",
                    "intent": "dining",
                    "confidence": 0.5,
                },
                "cached": False,
            },
        ]
        result = tool.search_guides(
            query="成都美食",
            city="成都",
            category="餐饮",
        )
        assert result.ok is True
        assert result.stats.degraded is True
        assert len(result.chunks) == 1
        assert mock_retriever.retrieve.call_count >= 2

    def test_multi_path_for_itinerary(self, mock_retriever, tool):
        def _resp(cat: str, text: str):
            return {
                "results": [_make_doc(text, category=cat, subsection=cat)],
                "query_info": {
                    "original": "成都三天行程",
                    "city": "成都",
                    "days": 3,
                    "intent": "itinerary",
                    "confidence": 0.9,
                },
                "cached": False,
            }

        # 首次单路探测 + 最多 4 路
        mock_retriever.retrieve.side_effect = [
            _resp("行程", "成都三日经典行程安排如下，第一天宽窄巷子。"),
            _resp("行程", "成都三日经典行程安排如下，第一天宽窄巷子。"),
            _resp("景点", "大熊猫基地建议游玩三小时。"),
            _resp("餐饮", "火锅人均一百左右。"),
            _resp("住宿", "春熙路附近住宿方便。"),
        ]
        result = tool.search_guides(query="成都三天行程", city="成都")
        assert result.ok is True
        assert result.stats.paths_used >= 2
        assert result.stats.chunk_count >= 1


class TestFormatContext:
    def test_truncate_and_token_budget(self, tool):
        long_text = "宽窄巷子。" * 200
        docs = [
            _make_doc(long_text, subsection=f"块{i}", source_file=f"f{i}.md")
            for i in range(20)
        ]
        chunks, context, tokens = tool.format_context(
            docs,
            query_info={"city": "成都", "intent": "scenic_spot", "confidence": 0.7},
            top_k=8,
        )
        assert len(chunks) <= 8
        assert tokens <= 3000 + 50  # 允许少量误差（最后一块可能越过判断前）
        for c in chunks:
            assert len(c.content) <= 401

    def test_dedup_same_section(self, tool):
        docs = [
            _make_doc("内容A内容A内容A内容A", score=0.9),
            _make_doc("内容A内容A内容A内容A", score=0.5),
        ]
        chunks, _, _ = tool.format_context(docs, top_k=5)
        assert len(chunks) == 1


class TestSearchForTrip:
    def test_builds_query_and_multi_path(self, mock_retriever, tool):
        mock_retriever.retrieve.return_value = {
            "results": [_make_doc("成都三日游玩攻略包含景点餐饮住宿。", category="行程")],
            "query_info": {
                "original": "x",
                "city": "成都",
                "days": 3,
                "intent": "itinerary",
                "confidence": 0.8,
            },
            "cached": False,
        }
        req = SimpleNamespace(
            destination="成都",
            start_date=date.today() + timedelta(days=7),
            end_date=date.today() + timedelta(days=9),
            travel_style=SimpleNamespace(value="foodie"),
            preferred_keywords=["火锅"],
            excluded_keywords=["夜店"],
        )
        result = tool.search_for_trip(req)
        assert result.ok is True
        assert mock_retriever.retrieve.call_count >= 1


class TestTruncate:
    def test_truncate_at_sentence(self):
        text = "第一句。第二句内容很长" + ("啊" * 500)
        out = _truncate_content(text, max_chars=50)
        assert len(out) <= 51
        assert "。" in out or out.endswith("…")
