"""
RAG 评估器单元测试
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from eval.evaluator import (
    RAGEvaluator,
    EvaluationCase,
    EvaluationLevel,
    RetrievalResult,
    EvaluationReport,
)
from eval.metrics.retrieval_metrics import RetrievalMetrics
from eval.metrics.latency_metrics import LatencyMetrics
from eval.metrics.quality_metrics import QualityMetrics


class TestRetrievalMetrics:
    """测试检索指标计算"""

    def test_recall_at_k(self):
        """测试召回率计算"""
        retrieved = ["doc1", "doc2", "doc3", "doc4", "doc5"]
        relevant = ["doc1", "doc3", "doc5"]

        # Recall@3
        recall_3 = RetrievalMetrics.recall_at_k(retrieved, relevant, 3)
        assert recall_3 == pytest.approx(2/3, rel=0.01)

        # Recall@5
        recall_5 = RetrievalMetrics.recall_at_k(retrieved, relevant, 5)
        assert recall_5 == 1.0

    def test_precision_at_k(self):
        """测试精确率计算"""
        retrieved = ["doc1", "doc2", "doc3"]
        relevant = ["doc1", "doc3"]

        precision = RetrievalMetrics.precision_at_k(retrieved, relevant, 3)
        assert precision == pytest.approx(2/3, rel=0.01)

    def test_mrr(self):
        """测试 MRR 计算"""
        retrieved = ["doc2", "doc1", "doc3"]
        relevant = ["doc1", "doc3"]

        mrr = RetrievalMetrics.mean_reciprocal_rank(retrieved, relevant)
        assert mrr == pytest.approx(0.5, rel=0.01)

        # 命中最前面
        retrieved_top = ["doc1", "doc2", "doc3"]
        mrr_top = RetrievalMetrics.mean_reciprocal_rank(retrieved_top, relevant)
        assert mrr_top == 1.0

    def test_ndcg_at_k(self):
        """测试 NDCG 计算"""
        retrieved = ["doc1", "doc2", "doc3"]
        relevance = {"doc1": 3.0, "doc2": 2.0, "doc3": 1.0}

        ndcg = RetrievalMetrics.ndcg_at_k(retrieved, relevance, 3)
        assert 0 < ndcg <= 1.0

    def test_average_precision(self):
        """测试 AP 计算"""
        retrieved = ["doc1", "doc3", "doc2", "doc4"]
        relevant = ["doc1", "doc2", "doc3"]

        ap = RetrievalMetrics.average_precision(retrieved, relevant)
        # 三个相关文档分别位于第 1/2/3 位：AP = (1/1 + 2/2 + 3/3) / 3 = 1.0
        assert ap == 1.0


class TestLatencyMetrics:
    """测试延迟指标计算"""

    def test_mean(self):
        """测试平均延迟"""
        latencies = [100, 200, 300, 400, 500]
        assert LatencyMetrics.mean(latencies) == 300.0

    def test_median(self):
        """测试中位数延迟"""
        latencies = [100, 200, 300, 400, 500]
        assert LatencyMetrics.median(latencies) == 300.0

        # 偶数个
        latencies2 = [100, 200, 300, 400]
        assert LatencyMetrics.median(latencies2) == 250.0

    def test_p95(self):
        """测试 P95 延迟"""
        latencies = list(range(1, 101))  # 1-100
        p95 = LatencyMetrics.p95(latencies)
        assert 94 <= p95 <= 96

    def test_percentile_list(self):
        """测试多个百分位数"""
        latencies = list(range(1, 101))
        percentiles = LatencyMetrics.percentile_list(latencies, [50, 90, 99])

        assert "p50" in percentiles
        assert "p90" in percentiles
        assert "p99" in percentiles

    def test_summary(self):
        """测试延迟汇总"""
        latencies = [100, 200, 300, 400, 500]
        summary = LatencyMetrics.summary(latencies)

        assert "mean_ms" in summary
        assert "p95_ms" in summary
        assert "min_ms" in summary
        assert "max_ms" in summary


class TestQualityMetrics:
    """测试质量指标计算"""

    def test_intent_accuracy(self):
        """测试意图准确率"""
        detected = ["itinerary", "scenic_spot", "dining", "scenic_spot"]
        expected = ["itinerary", "scenic_spot", "dining", "dining"]

        accuracy = QualityMetrics.intent_accuracy(detected, expected)
        assert accuracy == 0.75  # 3/4

    def test_city_accuracy(self):
        """测试城市准确率"""
        detected = ["北京", "大理", None, "成都"]
        expected = ["北京", "大理", "成都", "厦门"]

        accuracy = QualityMetrics.city_accuracy(detected, expected)
        # 4 组均有期望城市，匹配 2 组（北京、大理）
        assert accuracy == 0.5

    def test_pass_rate(self):
        """测试通过率"""
        assert QualityMetrics.pass_rate(85, 100) == 0.85
        assert QualityMetrics.pass_rate(0, 100) == 0.0
        assert QualityMetrics.pass_rate(100, 100) == 1.0

    def test_category_breakdown(self):
        """测试分类统计"""
        results = [
            {"category": "景点", "success": True},
            {"category": "景点", "success": True},
            {"category": "景点", "success": False},
            {"category": "餐饮", "success": True},
        ]

        breakdown = QualityMetrics.category_breakdown(results)

        assert breakdown["景点"]["total"] == 3
        assert breakdown["景点"]["passed"] == 2
        assert breakdown["餐饮"]["total"] == 1
        assert breakdown["餐饮"]["passed"] == 1


class TestEvaluationCase:
    """测试评估用例"""

    def test_case_creation(self):
        """测试用例创建"""
        case = EvaluationCase(
            case_id="test_001",
            query="北京三天怎么玩",
            expected_intent="itinerary",
            expected_city="北京",
            expected_days=3,
        )

        assert case.case_id == "test_001"
        assert case.query == "北京三天怎么玩"
        assert case.expected_intent == "itinerary"
        assert case.expected_city == "北京"
        assert case.expected_days == 3

    def test_case_defaults(self):
        """测试用例默认值"""
        case = EvaluationCase(
            case_id="test_002",
            query="随便逛逛",
        )

        assert case.expected_intent is None
        assert case.expected_city is None
        assert case.category == "general"
        assert case.difficulty == "medium"


class TestRetrievalResult:
    """测试检索结果"""

    def test_result_creation(self):
        """测试结果创建"""
        result = RetrievalResult(
            case_id="test_001",
            query="北京景点",
            detected_intent="scenic_spot",
            detected_city="北京",
            latency_ms=150.5,
        )

        assert result.case_id == "test_001"
        assert result.detected_intent == "scenic_spot"
        assert result.latency_ms == 150.5

    def test_result_to_dict(self):
        """测试结果转字典"""
        result = RetrievalResult(
            case_id="test_001",
            query="北京景点",
            detected_intent="scenic_spot",
            success=True,
        )

        d = result.to_dict()
        assert d["case_id"] == "test_001"
        assert d["success"] is True


class TestRAGEvaluator:
    """测试 RAG 评估器"""

    def test_evaluator_creation(self):
        """测试评估器创建"""
        evaluator = RAGEvaluator()
        assert evaluator.k_values == [1, 3, 5, 10]

    def test_evaluator_custom_k(self):
        """测试自定义 K 值"""
        evaluator = RAGEvaluator(k_values=[1, 5, 10])
        assert evaluator.k_values == [1, 5, 10]

    def test_keyword_recall(self):
        """测试关键词召回率计算"""
        evaluator = RAGEvaluator()

        docs = [
            {"document": "北京是中国的首都，有天安门广场"},
            {"document": "成都是四川省的省会"},
            {"document": "大理在云南省"},
        ]

        keywords = ["北京", "天安门"]
        recall = evaluator._keyword_recall_at_k(docs, keywords, 3)
        # 文档级召回：3 篇文档中仅第 1 篇包含关键词
        assert recall == pytest.approx(1 / 3, rel=1e-2)

    def test_is_case_passed_intent(self):
        """测试用例通过判断 - 意图"""
        evaluator = RAGEvaluator()

        case = EvaluationCase(
            case_id="test",
            query="测试",
            expected_intent="itinerary",
        )

        # 意图正确
        result = RetrievalResult(
            case_id="test",
            query="测试",
            detected_intent="itinerary",
            intent_correct=True,
            retrieved_docs=[{"id": "1"}],
            latency_ms=100,
            mrr=0.5,
        )
        assert evaluator._is_case_passed(case, result) is True

        # 意图错误
        result.intent_correct = False
        result.detected_intent = "scenic_spot"
        assert evaluator._is_case_passed(case, result) is False

    def test_is_case_passed_latency(self):
        """测试用例通过判断 - 延迟"""
        evaluator = RAGEvaluator()

        case = EvaluationCase(
            case_id="test",
            query="测试",
        )

        result = RetrievalResult(
            case_id="test",
            query="测试",
            retrieved_docs=[{"id": "1"}],
            latency_ms=6000,  # 超过5秒
            mrr=1.0,
        )
        assert evaluator._is_case_passed(case, result) is False

    def test_is_case_passed_no_results(self):
        """测试用例通过判断 - 无结果"""
        evaluator = RAGEvaluator()

        case = EvaluationCase(
            case_id="test",
            query="测试",
        )

        result = RetrievalResult(
            case_id="test",
            query="测试",
            retrieved_docs=[],  # 无结果
            latency_ms=100,
        )
        assert evaluator._is_case_passed(case, result) is False


class TestEvaluationLevel:
    """测试评估级别"""

    def test_level_values(self):
        """测试级别枚举值"""
        assert EvaluationLevel.QUICK.value == "quick"
        assert EvaluationLevel.STANDARD.value == "standard"
        assert EvaluationLevel.FULL.value == "full"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


