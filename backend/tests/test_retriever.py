"""
智旅云图 - RAG 检索器测试
"""

import pytest
from unittest.mock import Mock, patch
from app.rag.retriever import (
    QueryPreprocessor,
    IntentDetector,
    QueryExpander,
    RetrievalCache,
    Reranker,
    Retriever,
)


class TestQueryPreprocessor:
    """测试查询预处理器"""

    def setup_method(self):
        self.preprocessor = QueryPreprocessor()

    def test_extract_city(self):
        """测试城市提取"""
        assert self.preprocessor.extract_city("北京三天怎么玩") == "北京"
        assert self.preprocessor.extract_city("去大理玩几天") == "大理"
        assert self.preprocessor.extract_city("成都美食推荐") == "成都"
        assert self.preprocessor.extract_city("随便逛逛") is None

    def test_extract_days(self):
        """测试天数提取"""
        assert self.preprocessor.extract_days("北京玩三天") == 3
        assert self.preprocessor.extract_days("去五日游") == 5
        assert self.preprocessor.extract_days("两天行程安排") == 2
        assert self.preprocessor.extract_days("北京玩") is None

    def test_preprocess(self):
        """测试完整预处理"""
        result = self.preprocessor.preprocess("北京三天怎么玩")
        assert result["original"] == "北京三天怎么玩"
        assert result["city"] == "北京"
        assert result["days"] == 3


class TestIntentDetector:
    """测试意图检测器"""

    def setup_method(self):
        self.detector = IntentDetector()

    def test_detect_with_fallback(self):
        """测试降级意图检测（无 LLM 时）"""
        result = self.detector.detect("北京有什么好吃的")
        assert "primary_intent" in result
        assert result["primary_intent"] in ["scenic_spot", "dining", "accommodation", "itinerary"]
        assert 0 <= result["confidence"] <= 1

    def test_detect_intent_itinerary(self):
        """测试行程规划意图"""
        result = self.detector.detect("北京三天行程安排")
        assert result["primary_intent"] in ["itinerary", "dining", "scenic_spot"]

    def test_detect_intent_scenic_spot(self):
        """测试景点推荐意图"""
        result = self.detector.detect("北京有哪些好玩的地方")
        assert "primary_intent" in result

    def test_detect_intent_dining(self):
        """测试餐饮推荐意图"""
        result = self.detector.detect("成都必吃的美食")
        assert "primary_intent" in result


class TestQueryExpander:
    """测试查询扩展器"""

    def setup_method(self):
        self.expander = QueryExpander()

    def test_expand_scenic_spot(self):
        """测试景点扩展"""
        result = self.expander.expand("北京景点", "scenic_spot", top_k=5)
        assert isinstance(result, list)
        assert len(result) <= 5

    def test_expand_dining(self):
        """测试餐饮扩展"""
        result = self.expander.expand("成都美食", "dining", top_k=5)
        assert isinstance(result, list)
        assert len(result) <= 5

    def test_expand_returns_default_terms(self):
        """测试无 Embedding 时返回默认词表"""
        result = self.expander.expand("测试", "itinerary", top_k=3)
        assert len(result) == 3


class TestRetrievalCache:
    """测试检索缓存"""

    def setup_method(self):
        self.cache = RetrievalCache(redis_url="redis://localhost:6379/0")

    def test_generate_key(self):
        """测试缓存键生成"""
        key1 = self.cache._generate_key("北京三天", "北京", "itinerary")
        key2 = self.cache._generate_key("北京三天", "北京", "itinerary")
        key3 = self.cache._generate_key("北京三天", "大理", "itinerary")

        assert key1 == key2
        assert key1 != key3
        assert key1.startswith("rag:retrieval:")

    def test_cache_disconnected(self):
        """测试 Redis 未连接时返回 None"""
        result = self.cache.get("测试查询")
        assert result is None

    def test_cache_set_disconnected(self):
        """测试 Redis 未连接时写入返回 False"""
        result = self.cache.set("测试", "北京", "itinerary", [], {})
        assert result is False

    def test_get_stats_disconnected(self):
        """测试 Redis 未连接时统计"""
        stats = self.cache.get_stats()
        assert stats["status"] == "disconnected"


class TestReranker:
    """测试重排序器"""

    def setup_method(self):
        self.reranker = Reranker()

    def test_rerank_empty_documents(self):
        """测试空文档"""
        result = self.reranker.rerank("测试查询", [], top_n=5)
        assert result == []

    def test_rerank_single_document(self):
        """测试单文档"""
        docs = [{"document": "这是一个测试文档", "score": 0.8}]
        result = self.reranker.rerank("测试查询", docs, top_n=5)
        assert len(result) == 1

    def test_rerank_multiple_documents(self):
        """测试多文档"""
        docs = [
            {"document": "文档1", "score": 0.5},
            {"document": "文档2", "score": 0.9},
            {"document": "文档3", "score": 0.3},
        ]
        result = self.reranker.rerank("测试查询", docs, top_n=2)
        assert len(result) <= 2


class TestRetriever:
    """测试统一检索服务"""

    def setup_method(self):
        self.retriever = Retriever()

    def test_retriever_components(self):
        """测试组件初始化"""
        assert isinstance(self.retriever.preprocessor, QueryPreprocessor)
        assert isinstance(self.retriever.intent_detector, IntentDetector)
        assert isinstance(self.retriever.query_expander, QueryExpander)
        assert isinstance(self.retriever.reranker, Reranker)
        assert isinstance(self.retriever.cache, RetrievalCache)

    @patch("app.rag.retriever.hybrid_search_engine")
    def test_retrieve_basic(self, mock_search_engine):
        """测试基本检索流程"""
        mock_search_engine.search.return_value = [
            {
                "id": "doc1",
                "document": "测试文档",
                "metadata": {"city": "北京"},
                "similarity": 0.9
            }
        ]

        result = self.retriever.retrieve(
            query="北京景点推荐",
            city="北京",
            use_cache=False,
            use_rerank=False,
            top_k=5
        )

        assert "results" in result
        assert "query_info" in result
        assert "total_time_ms" in result
        assert "stages" in result
        assert result["cached"] is False

    def test_retrieve_extracts_city(self):
        """测试自动提取城市"""
        with patch.object(self.retriever, "_get_query_embedding", return_value=[0.0] * 256):
            with patch.object(self.retriever.search_engine, "search", return_value=[]):
                result = self.retriever.retrieve(
                    query="大理三天怎么玩",
                    use_cache=False,
                    use_rerank=False
                )

                assert result["query_info"]["city"] == "大理"
                assert result["query_info"]["days"] == 3

    def test_retrieve_stages_timing(self):
        """测试各阶段耗时"""
        result = self.retriever.retrieve(
            query="测试查询",
            use_cache=False,
            use_rerank=False
        )

        assert "stages" in result
        assert "preprocess_ms" in result["stages"]
        assert "intent_detect_ms" in result["stages"]
        assert "total_ms" in result["stages"]


class TestRetrievalCacheIntegration:
    """测试缓存集成"""

    def test_cache_key_uniqueness(self):
        """测试缓存键唯一性"""
        cache = RetrievalCache()

        key1 = cache._generate_key("北京", "北京", None)
        key2 = cache._generate_key("北京", None, None)
        key3 = cache._generate_key("成都", "成都", None)

        assert key1 != key2
        assert key2 != key3

    def test_cache_key_similarity(self):
        """测试相似查询生成不同键"""
        cache = RetrievalCache()

        key1 = cache._generate_key("北京三天行程", "北京", "itinerary")
        key2 = cache._generate_key("北京三天行程安排", "北京", "itinerary")

        assert key1 != key2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
