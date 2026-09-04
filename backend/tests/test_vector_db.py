"""
智旅云图 - RAG 向量数据库与混合检索引擎测试

全部 mock ChromaDB 集合，不打真实向量库 / LLM / 网络。
"""

import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.rag.vector_db import (
    HybridSearchEngine,
    VectorDBManager,
    VectorDBService,
)


def _make_collection_mock():
    """构造 mock ChromaDB 集合"""
    collection = MagicMock()
    collection.name = "travel_guides"
    collection.count.return_value = 0
    collection.metadata = {"description": "智旅云图旅行攻略向量库"}
    return collection


def _make_vector_db(collection=None):
    """构造不连接真实 ChromaDB 的 VectorDBService"""
    service = VectorDBService(persist_directory=":memory:")
    service._client = MagicMock()
    service._collection = collection or _make_collection_mock()
    return service


class TestNormalizeWhere:
    """测试 where 过滤条件归一化"""

    def test_none_returns_none(self):
        assert VectorDBService._normalize_where(None) is None

    def test_empty_dict_returns_none(self):
        assert VectorDBService._normalize_where({}) is None

    def test_single_field(self):
        assert VectorDBService._normalize_where({"city": "北京"}) == {"city": {"$eq": "北京"}}

    def test_multiple_fields_use_and(self):
        result = VectorDBService._normalize_where({"city": "北京", "category": "景点"})
        assert result == {
            "$and": [
                {"city": {"$eq": "北京"}},
                {"category": {"$eq": "景点"}},
            ]
        }

    def test_operator_expression_passthrough(self):
        assert VectorDBService._normalize_where({"score": {"$gte": 0.5}}) == {
            "score": {"$gte": 0.5}
        }

    def test_mixed_simple_and_operator(self):
        result = VectorDBService._normalize_where({"city": "北京", "score": {"$gte": 0.5}})
        assert result == {
            "$and": [
                {"city": {"$eq": "北京"}},
                {"score": {"$gte": 0.5}},
            ]
        }


class TestGenerateDocId:
    """测试文档 ID 生成"""

    def test_deterministic(self):
        service = _make_vector_db()
        assert service._generate_doc_id("同一内容") == service._generate_doc_id("同一内容")

    def test_different_content_different_id(self):
        service = _make_vector_db()
        assert service._generate_doc_id("内容A") != service._generate_doc_id("内容B")

    def test_id_format(self):
        service = _make_vector_db()
        doc_id = service._generate_doc_id("测试")
        assert len(doc_id) == 16
        assert all(c in "0123456789abcdef" for c in doc_id)


class TestFormatQueryResults:
    """测试查询结果格式化"""

    def test_flattens_nested_lists(self):
        service = _make_vector_db()
        raw = {
            "ids": [["doc1", "doc2"]],
            "documents": [["文档一", "文档二"]],
            "metadatas": [[{"city": "北京"}, {"city": "成都"}]],
            "distances": [[0.1, 0.2]],
        }
        result = service._format_query_results(raw)
        assert result["ids"] == ["doc1", "doc2"]
        assert result["documents"] == ["文档一", "文档二"]
        assert result["metadatas"] == [{"city": "北京"}, {"city": "成都"}]
        assert result["distances"] == [0.1, 0.2]

    def test_empty_results(self):
        service = _make_vector_db()
        result = service._format_query_results({})
        assert result == {"ids": [], "documents": [], "metadatas": [], "distances": []}


class TestAddDocuments:
    """测试文档入库"""

    def test_add_with_explicit_ids(self):
        service = _make_vector_db()
        ids = service.add_documents(
            documents=["文档A"],
            embeddings=[[0.1] * 256],
            metadatas=[{"city": "北京"}],
            ids=["custom-id"],
        )
        assert ids == ["custom-id"]
        service.collection.add.assert_called_once_with(
            documents=["文档A"],
            embeddings=[[0.1] * 256],
            metadatas=[{"city": "北京"}],
            ids=["custom-id"],
        )

    def test_add_generates_ids_and_default_metadata(self):
        service = _make_vector_db()
        ids = service.add_documents(
            documents=["文档A", "文档B"],
            embeddings=[[0.1] * 256, [0.2] * 256],
        )
        assert len(ids) == 2
        assert ids == [service._generate_doc_id("文档A"), service._generate_doc_id("文档B")]
        service.collection.add.assert_called_once()
        assert service.collection.add.call_args.kwargs["metadatas"] == [{}, {}]

    def test_add_raises_on_error(self):
        service = _make_vector_db()
        service.collection.add.side_effect = RuntimeError("写入失败")
        with pytest.raises(RuntimeError):
            service.add_documents(documents=["文档A"], embeddings=[[0.1] * 256])


class TestQueryByVector:
    """测试向量查询"""

    def test_query_success(self):
        service = _make_vector_db()
        service.collection.query.return_value = {
            "ids": [["doc1"]],
            "documents": [["匹配文档"]],
            "metadatas": [[{"city": "北京"}]],
            "distances": [[0.05]],
        }
        result = service.query_by_vector(
            query_embedding=[0.1] * 256,
            n_results=5,
            where={"city": "北京"},
        )
        assert result["ids"] == ["doc1"]
        assert result["documents"] == ["匹配文档"]
        service.collection.query.assert_called_once()
        kwargs = service.collection.query.call_args.kwargs
        assert kwargs["where"] == {"city": {"$eq": "北京"}}
        assert kwargs["n_results"] == 5
        assert kwargs["include"] == ["documents", "metadatas", "distances"]

    def test_query_error_returns_empty(self):
        service = _make_vector_db()
        service.collection.query.side_effect = RuntimeError("查询失败")
        result = service.query_by_vector(query_embedding=[0.1] * 256)
        assert result == {"ids": [], "documents": [], "metadatas": [], "distances": []}


class TestQueryByText:
    """测试文本查询"""

    def test_query_success(self):
        service = _make_vector_db()
        service.collection.query.return_value = {
            "ids": [["doc1"]],
            "documents": [["匹配文档"]],
            "metadatas": [[{"city": "成都"}]],
            "distances": [[0.2]],
        }
        result = service.query_by_text(query_texts=["成都美食"])
        assert result["ids"] == ["doc1"]
        assert result["documents"] == ["匹配文档"]

    def test_query_error_returns_empty(self):
        service = _make_vector_db()
        service.collection.query.side_effect = RuntimeError("查询失败")
        result = service.query_by_text(query_texts=["测试"])
        assert result == {"ids": [], "documents": [], "metadatas": [], "distances": []}


class TestGetDocument:
    """测试按 ID 获取文档"""

    def test_found(self):
        service = _make_vector_db()
        service.collection.get.return_value = {
            "ids": ["doc1"],
            "documents": ["文档内容"],
            "metadatas": [{"city": "北京"}],
        }
        doc = service.get_document("doc1")
        assert doc == {"id": "doc1", "document": "文档内容", "metadata": {"city": "北京"}}

    def test_not_found(self):
        service = _make_vector_db()
        service.collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        assert service.get_document("missing") is None

    def test_error_returns_none(self):
        service = _make_vector_db()
        service.collection.get.side_effect = RuntimeError("读取失败")
        assert service.get_document("doc1") is None


class TestCount:
    """测试文档计数"""

    def test_count(self):
        service = _make_vector_db()
        service.collection.count.return_value = 42
        assert service.count() == 42


class TestResetCollection:
    """测试重置集合"""

    def test_reset_success(self):
        service = _make_vector_db()
        service.client.delete_collection.return_value = None
        assert service.reset_collection() is True
        service.client.delete_collection.assert_called_once_with(name="travel_guides")
        assert service._collection is None

    def test_reset_error_returns_false(self):
        service = _make_vector_db()
        service.client.delete_collection.side_effect = RuntimeError("删除失败")
        assert service.reset_collection() is False


class TestGetCollectionInfo:
    """测试集合信息"""

    def test_info_success(self):
        collection = _make_collection_mock()
        collection.count.return_value = 7
        service = _make_vector_db(collection=collection)
        service.get_or_create_collection = Mock(return_value=collection)
        info = service.get_collection_info()
        assert info["name"] == "travel_guides"
        assert info["count"] == 7
        assert info["dimension"] == 256

    def test_info_error_returns_empty(self):
        service = _make_vector_db()
        service.get_or_create_collection = Mock(side_effect=RuntimeError("初始化失败"))
        assert service.get_collection_info() == {}


class TestDeleteDocuments:
    """测试删除文档"""

    def test_delete_success(self):
        service = _make_vector_db()
        assert service.delete_documents(["doc1", "doc2"]) is True
        service.collection.delete.assert_called_once_with(ids=["doc1", "doc2"])

    def test_delete_error_returns_false(self):
        service = _make_vector_db()
        service.collection.delete.side_effect = RuntimeError("删除失败")
        assert service.delete_documents(["doc1"]) is False


class TestKeywordTokenize:
    """测试关键词分词"""

    def test_cjk_single_and_bigram(self):
        terms = HybridSearchEngine._keyword_tokenize("北京美食")
        assert {"北", "京", "美", "食"} <= terms
        assert {"北京", "京美", "美食"} <= terms

    def test_ascii_words(self):
        terms = HybridSearchEngine._keyword_tokenize("beijing food 3")
        assert {"beijing", "food", "3"} <= terms

    def test_empty_text(self):
        assert HybridSearchEngine._keyword_tokenize("") == set()


class TestKeywordScore:
    """测试关键词得分"""

    def test_identical_text_scores_one(self):
        score = HybridSearchEngine._keyword_score(
            HybridSearchEngine._keyword_tokenize("北京美食"),
            "北京美食",
        )
        assert score == pytest.approx(1.0)

    def test_no_overlap_scores_zero(self):
        score = HybridSearchEngine._keyword_score(
            HybridSearchEngine._keyword_tokenize("美食"),
            "北京景点",
        )
        assert score == 0.0

    def test_partial_overlap_between_zero_and_one(self):
        score = HybridSearchEngine._keyword_score(
            HybridSearchEngine._keyword_tokenize("北京美食"),
            "北京景点",
        )
        assert 0.0 < score < 1.0


class TestKeywordSearch:
    """测试关键词检索"""

    def test_search_filters_and_sorts(self):
        service = _make_vector_db()
        service.collection.get.return_value = {
            "ids": ["doc1", "doc2", "doc3"],
            "documents": ["北京美食推荐", "上海天气", "北京故宫景点"],
            "metadatas": [{"city": "北京"}, {"city": "上海"}, {"city": "北京"}],
        }
        engine = HybridSearchEngine(service)
        results = engine._keyword_search("北京", top_k=2, where_filter={"city": "北京"})
        assert len(results) == 2
        assert all(r["id"] in {"doc1", "doc3"} for r in results)
        assert results[0]["_kw_score"] >= results[1]["_kw_score"]

    def test_search_empty_documents(self):
        service = _make_vector_db()
        service.collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        engine = HybridSearchEngine(service)
        assert engine._keyword_search("北京", top_k=5) == []

    def test_search_error_returns_empty(self):
        service = _make_vector_db()
        service.collection.get.side_effect = RuntimeError("读取失败")
        engine = HybridSearchEngine(service)
        assert engine._keyword_search("北京", top_k=5) == []


class TestRRFFusion:
    """测试 RRF 融合"""

    def test_doc_in_both_lists_ranks_higher(self):
        engine = HybridSearchEngine(_make_vector_db())
        vector_results = [
            {"id": "both", "document": "双通道文档"},
            {"id": "vector-only", "document": "仅向量文档"},
        ]
        keyword_results = [
            {"id": "both", "document": "双通道文档"},
            {"id": "keyword-only", "document": "仅关键词文档"},
        ]
        fused = engine._rrf_fusion(vector_results, keyword_results)
        assert fused[0]["id"] == "both"
        assert fused[0]["vector_rank"] == 1
        assert fused[0]["keyword_rank"] == 1
        assert fused[0]["rrf_score"] > fused[1]["rrf_score"]

    def test_weights_affect_score(self):
        engine = HybridSearchEngine(_make_vector_db())
        vector_results = [{"id": "v1", "document": "向量文档"}]
        keyword_results = []
        fused = engine._rrf_fusion(
            vector_results, keyword_results, k=60, weights={"vector": 0.7, "keyword": 0.3}
        )
        assert fused[0]["rrf_score"] == pytest.approx(0.7 / 61)


class TestWeightedFusion:
    """测试加权融合"""

    def test_doc_in_both_lists_ranks_higher(self):
        engine = HybridSearchEngine(_make_vector_db())
        vector_results = [
            {"id": "both", "document": "双通道文档"},
            {"id": "vector-only", "document": "仅向量文档"},
        ]
        keyword_results = [
            {"id": "both", "document": "双通道文档"},
            {"id": "keyword-only", "document": "仅关键词文档"},
        ]
        fused = engine._weighted_fusion(
            vector_results,
            keyword_results,
            weights={"vector": 0.7, "keyword": 0.3},
        )
        assert fused[0]["id"] == "both"
        assert fused[0]["weighted_score"] == pytest.approx(0.7 * 1.0 + 0.3 * 1.0)

    def test_single_list_score(self):
        engine = HybridSearchEngine(_make_vector_db())
        fused = engine._weighted_fusion(
            [{"id": "v1", "document": "向量文档"}],
            [],
            weights={"vector": 0.7, "keyword": 0.3},
        )
        assert fused[0]["weighted_score"] == pytest.approx(0.7)


class TestResultsToList:
    """测试查询结果转列表"""

    def test_converts_with_similarity(self):
        engine = HybridSearchEngine(_make_vector_db())
        results = {
            "ids": ["doc1"],
            "documents": ["文档"],
            "metadatas": [{"city": "北京"}],
            "distances": [0.2],
        }
        items = engine._results_to_list(results)
        assert items[0]["id"] == "doc1"
        assert items[0]["similarity"] == pytest.approx(0.8)
        assert items[0]["distance"] == 0.2

    def test_empty(self):
        engine = HybridSearchEngine(_make_vector_db())
        assert engine._results_to_list(
            {"ids": [], "documents": [], "metadatas": [], "distances": []}
        ) == []


class TestHybridSearch:
    """测试混合检索完整流程"""

    def _make_engine(self, vector_db):
        engine = HybridSearchEngine(vector_db)
        engine.retrieval_rules = {
            "retrieval": {
                "fusion": {
                    "method": "rrf",
                    "k": 60,
                    "weights": {"vector": 0.7, "keyword": 0.3},
                }
            }
        }
        return engine

    def test_search_fuses_results_and_limits_top_k(self):
        vector_db = _make_vector_db()
        vector_db.query_by_vector = Mock(return_value={
            "ids": ["v1", "v2", "v3"],
            "documents": ["向量文档1", "向量文档2", "向量文档3"],
            "metadatas": [{"city": "北京"}] * 3,
            "distances": [0.1, 0.2, 0.3],
        })
        vector_db.collection.get.return_value = {
            "ids": ["k1"],
            "documents": ["北京美食关键词文档"],
            "metadatas": [{"city": "北京"}],
        }
        engine = self._make_engine(vector_db)
        results = engine.search(
            query="北京美食",
            query_embedding=[0.1] * 256,
            city="北京",
            category="餐饮",
            top_k=2,
        )
        assert len(results) == 2
        assert all("rrf_score" in r for r in results)
        vector_db.query_by_vector.assert_called_once()
        kwargs = vector_db.query_by_vector.call_args.kwargs
        assert kwargs["where"] == {"city": "北京", "category": "餐饮"}

    def test_search_without_filter(self):
        vector_db = _make_vector_db()
        vector_db.query_by_vector = Mock(return_value={
            "ids": [],
            "documents": [],
            "metadatas": [],
            "distances": [],
        })
        vector_db.collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        engine = self._make_engine(vector_db)
        results = engine.search(query="随便逛逛", query_embedding=[0.1] * 256)
        assert results == []
        vector_db.query_by_vector.assert_called_once()
        assert vector_db.query_by_vector.call_args.kwargs["where"] is None

    def test_search_weighted_method(self):
        vector_db = _make_vector_db()
        vector_db.query_by_vector = Mock(return_value={
            "ids": ["v1"],
            "documents": ["向量文档"],
            "metadatas": [{"city": "北京"}],
            "distances": [0.1],
        })
        vector_db.collection.get.return_value = {
            "ids": ["k1"],
            "documents": ["北京美食关键词文档"],
            "metadatas": [{"city": "北京"}],
        }
        engine = self._make_engine(vector_db)
        engine.retrieval_rules["retrieval"]["fusion"]["method"] = "weighted"
        results = engine.search(query="北京美食", query_embedding=[0.1] * 256, top_k=5)
        assert len(results) == 2
        assert all("weighted_score" in r for r in results)

    def test_search_vector_error_falls_back_to_keyword(self):
        vector_db = _make_vector_db()
        vector_db.query_by_vector = Mock(side_effect=RuntimeError("向量检索失败"))
        vector_db.collection.get.return_value = {
            "ids": ["k1"],
            "documents": ["北京美食关键词文档"],
            "metadatas": [{"city": "北京"}],
        }
        engine = self._make_engine(vector_db)
        results = engine.search(query="北京美食", query_embedding=[0.1] * 256, top_k=5)
        assert len(results) == 1
        assert results[0]["id"] == "k1"


class TestVectorDBManager:
    """测试向量数据库管理器"""

    def test_health_check_healthy(self, tmp_path):
        service = _make_vector_db()
        service.persist_directory = str(tmp_path)
        service.get_collection_info = Mock(
            return_value={"name": "travel_guides", "count": 10}
        )
        manager = VectorDBManager(service)
        status = manager.health_check()
        assert status["status"] == "healthy"
        assert status["checks"]["collection"]["document_count"] == 10
        assert status["checks"]["storage"]["status"] == "ok"

    def test_health_check_degraded_on_collection_error(self, tmp_path):
        service = _make_vector_db()
        service.persist_directory = str(tmp_path)
        service.get_collection_info = Mock(side_effect=RuntimeError("集合不可用"))
        manager = VectorDBManager(service)
        status = manager.health_check()
        assert status["status"] == "degraded"
        assert status["checks"]["collection"]["status"] == "error"

    def test_backup_copies_directory(self, tmp_path):
        persist = tmp_path / "chroma"
        persist.mkdir()
        (persist / "data.sqlite3").write_text("fake-data")
        service = _make_vector_db()
        service.persist_directory = str(persist)
        manager = VectorDBManager(service)
        backup_path = manager.backup(str(tmp_path / "backup"))
        assert os.path.exists(os.path.join(backup_path, "data.sqlite3"))

    def test_restore_requires_existing_backup(self, tmp_path):
        service = _make_vector_db()
        service.persist_directory = str(tmp_path / "chroma")
        manager = VectorDBManager(service)
        assert manager.restore(str(tmp_path / "missing_backup")) is False

    def test_get_stats(self):
        service = _make_vector_db()
        service.get_collection_info = Mock(return_value={"count": 3})
        service.collection.get.return_value = {
            "metadatas": [
                {"city": "北京", "category": "景点"},
                {"city": "北京", "category": "餐饮"},
                {"city": "成都", "category": "景点"},
            ]
        }
        manager = VectorDBManager(service)
        stats = manager.get_stats()
        assert stats["total_documents"] == 3
        assert stats["by_city"] == {"北京": 2, "成都": 1}
        assert stats["by_category"] == {"景点": 2, "餐饮": 1}

    def test_get_stats_error_returns_empty(self):
        service = _make_vector_db()
        service.get_collection_info = Mock(side_effect=RuntimeError("不可用"))
        manager = VectorDBManager(service)
        assert manager.get_stats() == {}
