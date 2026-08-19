"""
RAG 评估引擎
提供完整的检索系统评估能力
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import time
import math
from loguru import logger


class EvaluationLevel(Enum):
    """评估级别"""
    QUICK = "quick"  # 快速评估（10个用例）
    STANDARD = "standard"  # 标准评估（50个用例）
    FULL = "full"  # 完整评估（全部用例）


@dataclass
class EvaluationCase:
    """评估用例"""
    case_id: str
    query: str
    expected_intent: Optional[str] = None
    expected_city: Optional[str] = None
    expected_days: Optional[int] = None
    relevant_doc_ids: List[str] = field(default_factory=list)
    expected_keywords: List[str] = field(default_factory=list)
    category: str = "general"
    difficulty: str = "medium"
    priority: str = "P1"


@dataclass
class RetrievalResult:
    """单次检索结果"""
    case_id: str
    query: str

    # 意图识别结果
    detected_intent: Optional[str] = None
    intent_correct: bool = False

    # 城市提取结果
    detected_city: Optional[str] = None
    city_correct: bool = False

    # 天数提取结果
    detected_days: Optional[int] = None
    days_correct: bool = False

    # 检索结果
    retrieved_docs: List[dict] = field(default_factory=list)
    retrieved_doc_ids: List[str] = field(default_factory=list)

    # 召回指标
    recall_at_k: Dict[int, float] = field(default_factory=dict)
    precision_at_k: Dict[int, float] = field(default_factory=dict)
    mrr: float = 0.0
    ndcg_at_k: Dict[int, float] = field(default_factory=dict)

    # 质量指标
    relevance_scores: List[float] = field(default_factory=list)
    avg_relevance: float = 0.0

    # 性能指标
    latency_ms: float = 0.0
    stages_timing: Dict[str, float] = field(default_factory=dict)

    # 总体评分
    success: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "case_id": self.case_id,
            "query": self.query,
            "detected_intent": self.detected_intent,
            "intent_correct": self.intent_correct,
            "detected_city": self.detected_city,
            "city_correct": self.city_correct,
            "detected_days": self.detected_days,
            "days_correct": self.days_correct,
            "num_retrieved": len(self.retrieved_docs),
            "mrr": self.mrr,
            "avg_relevance": self.avg_relevance,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error_message": self.error_message,
        }


@dataclass
class EvaluationReport:
    """评估报告"""
    timestamp: str
    level: EvaluationLevel

    # 总体统计
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases_count: int = 0
    pass_rate: float = 0.0

    # 意图识别指标
    intent_accuracy: float = 0.0
    intent_confusion_matrix: Dict[str, Dict[str, int]] = field(default_factory=dict)

    # 城市提取指标
    city_extraction_accuracy: float = 0.0

    # 天数提取指标
    days_extraction_accuracy: float = 0.0

    # 检索质量指标
    mean_recall_at_k: Dict[int, float] = field(default_factory=dict)
    mean_precision_at_k: Dict[int, float] = field(default_factory=dict)
    mean_mrr: float = 0.0
    mean_ndcg_at_k: Dict[int, float] = field(default_factory=dict)

    # 性能指标
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0

    # 阶段耗时
    stages_breakdown: Dict[str, float] = field(default_factory=dict)

    # 分类统计
    by_category: Dict[str, dict] = field(default_factory=dict)
    by_difficulty: Dict[str, dict] = field(default_factory=dict)
    by_priority: Dict[str, dict] = field(default_factory=dict)

    # 详细结果
    case_results: List[RetrievalResult] = field(default_factory=list)

    # 失败用例
    failed_cases: List[RetrievalResult] = field(default_factory=list)

    # 建议
    recommendations: List[str] = field(default_factory=list)

    # 错误统计
    error_count: int = 0

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "timestamp": self.timestamp,
            "level": self.level.value,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases_count,
            "pass_rate": self.pass_rate,
            "intent_accuracy": self.intent_accuracy,
            "city_extraction_accuracy": self.city_extraction_accuracy,
            "days_extraction_accuracy": self.days_extraction_accuracy,
            "mean_mrr": self.mean_mrr,
            "avg_latency_ms": self.avg_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "recommendations": self.recommendations,
            "by_category": self.by_category,
        }


class RAGEvaluator:
    """RAG 评估器"""

    def __init__(
        self,
        retriever_instance=None,
        k_values: List[int] = None
    ):
        self.retriever = retriever_instance
        self.k_values = k_values or [1, 3, 5, 10]

        # 延迟导入避免循环依赖
        self._retriever_module = None

    def _get_retriever(self):
        """获取检索器实例"""
        if self.retriever is None:
            if self._retriever_module is None:
                import sys
                from pathlib import Path
                # 获取 backend 目录
                run_eval_path = Path(__file__).resolve()
                backend_dir = run_eval_path.parent.parent
                if str(backend_dir) not in sys.path:
                    sys.path.insert(0, str(backend_dir))
                from app.rag.retriever import retriever
                self.retriever = retriever
        return self.retriever

    def evaluate_case(
        self,
        case: EvaluationCase,
        use_cache: bool = False
    ) -> RetrievalResult:
        """评估单个用例"""
        result = RetrievalResult(case_id=case.case_id, query=case.query)

        start_time = time.time()

        try:
            # 执行检索
            retriever = self._get_retriever()
            retrieval_result = retriever.retrieve(
                query=case.query,
                use_cache=use_cache,
                use_rerank=True,
                top_k=10
            )

            result.latency_ms = (time.time() - start_time) * 1000
            result.stages_timing = retrieval_result.get("stages", {})

            # 解析意图识别结果
            query_info = retrieval_result.get("query_info", {})
            result.detected_intent = query_info.get("intent")
            result.detected_city = query_info.get("city")
            result.detected_days = query_info.get("days")

            # 意图正确性
            if case.expected_intent:
                result.intent_correct = result.detected_intent == case.expected_intent

            # 城市正确性
            if case.expected_city:
                result.city_correct = result.detected_city == case.expected_city

            # 天数正确性
            if case.expected_days:
                result.days_correct = result.detected_days == case.expected_days

            # 检索结果处理
            docs = retrieval_result.get("results", [])
            result.retrieved_docs = docs
            result.retrieved_doc_ids = [doc.get("id") for doc in docs]

            # 计算召回指标
            self._calculate_recall_metrics(result, case, docs)

            # 计算精确度指标
            self._calculate_precision_metrics(result, case, docs)

            # 计算 MRR
            self._calculate_mrr(result, case, docs)

            # 计算 NDCG
            self._calculate_ndcg(result, case, docs)

            # 计算相关性分数
            self._calculate_relevance(result, docs)

            # 判断是否通过
            result.success = self._is_case_passed(case, result)

        except Exception as e:
            logger.error(f"评估用例 {case.case_id} 失败: {e}")
            result.error_message = str(e)
            result.success = False

        return result

    def _calculate_recall_metrics(
        self,
        result: RetrievalResult,
        case: EvaluationCase,
        docs: List[dict]
    ):
        """计算召回率"""
        if not case.relevant_doc_ids:
            # 如果没有相关文档ID，使用关键词判断
            for k in self.k_values:
                result.recall_at_k[k] = self._keyword_recall_at_k(docs, case.expected_keywords, k)
            return

        relevant_set = set(case.relevant_doc_ids)

        for k in self.k_values:
            retrieved_at_k = set(result.retrieved_doc_ids[:k])
            recall = len(retrieved_at_k & relevant_set) / len(relevant_set)
            result.recall_at_k[k] = round(recall, 4)

    def _keyword_recall_at_k(
        self,
        docs: List[dict],
        keywords: List[str],
        k: int
    ) -> float:
        """基于关键词计算召回率"""
        if not keywords:
            return 1.0  # 没有关键词要求，假设通过

        matched_docs = 0
        for doc in docs[:k]:
            doc_text = doc.get("document", "").lower()
            for keyword in keywords:
                if keyword.lower() in doc_text:
                    matched_docs += 1
                    break

        return round(matched_docs / min(k, len(docs)), 4) if docs else 0.0

    def _calculate_precision_metrics(
        self,
        result: RetrievalResult,
        case: EvaluationCase,
        docs: List[dict]
    ):
        """计算精确率"""
        for k in self.k_values:
            if not docs or k <= 0:
                result.precision_at_k[k] = 0.0
                continue

            # 基于关键词判断相关性
            relevant_count = 0
            for doc in docs[:k]:
                doc_text = doc.get("document", "").lower()
                for keyword in case.expected_keywords:
                    if keyword.lower() in doc_text:
                        relevant_count += 1
                        break

            precision = relevant_count / min(k, len(docs[:k]))
            result.precision_at_k[k] = round(precision, 4)

    def _calculate_mrr(
        self,
        result: RetrievalResult,
        case: EvaluationCase,
        docs: List[dict]
    ):
        """计算 MRR (Mean Reciprocal Rank)"""
        # 如果有相关文档ID
        if case.relevant_doc_ids:
            relevant_set = set(case.relevant_doc_ids)
            for i, doc in enumerate(docs, 1):
                doc_id = doc.get("id")
                if doc_id in relevant_set:
                    result.mrr = round(1.0 / i, 4)
                    return
        else:
            # 使用关键词判断
            for i, doc in enumerate(docs, 1):
                doc_text = doc.get("document", "").lower()
                for keyword in case.expected_keywords:
                    if keyword.lower() in doc_text:
                        result.mrr = round(1.0 / i, 4)
                        return

        result.mrr = 0.0

    def _calculate_ndcg(
        self,
        result: RetrievalResult,
        case: EvaluationCase,
        docs: List[dict]
    ):
        """计算 NDCG"""
        for k in self.k_values:
            # DCG@k
            dcg = 0.0
            for i, doc in enumerate(docs[:k], 1):
                doc_text = doc.get("document", "").lower()
                # 相关性等级
                relevance = 0
                for keyword in case.expected_keywords:
                    if keyword.lower() in doc_text:
                        relevance = 2
                        break
                # 如果有 rerank 分数，使用分数作为相关性
                rerank_score = doc.get("rerank_score")
                if rerank_score is not None:
                    relevance = max(relevance, int(rerank_score * 2))

                dcg += relevance / (math.log2(i + 1) if i > 1 else 1)

            # IDCG@k
            ideal_k = min(k, len(case.relevant_doc_ids) if case.relevant_doc_ids else len(docs))
            idcg = sum([2 / (math.log2(i + 1) if i > 1 else 1) for i in range(1, ideal_k + 1)])

            result.ndcg_at_k[k] = round(dcg / idcg, 4) if idcg > 0 else 0.0

    def _calculate_relevance(
        self,
        result: RetrievalResult,
        docs: List[dict]
    ):
        """计算相关性分数"""
        for doc in docs:
            # 基于 Rerank 分数
            rerank_score = doc.get("rerank_score")
            if rerank_score is not None:
                result.relevance_scores.append(round(rerank_score, 4))
            else:
                # 使用 similarity 分数
                similarity = doc.get("similarity")
                if similarity is not None:
                    result.relevance_scores.append(round(similarity, 4))
                else:
                    result.relevance_scores.append(0.5)

        if result.relevance_scores:
            result.avg_relevance = round(
                sum(result.relevance_scores) / len(result.relevance_scores),
                4
            )

    def _is_case_passed(self, case: EvaluationCase, result: RetrievalResult) -> bool:
        """判断用例是否通过"""
        # 如果有错误，直接失败
        if result.error_message:
            return False

        # 意图必须正确（如果指定了期望意图）
        if case.expected_intent and not result.intent_correct:
            return False

        # 城市必须正确（如果指定了期望城市）
        if case.expected_city and not result.city_correct:
            return False

        # 延迟必须在阈值内（默认5秒）
        if result.latency_ms > 5000:
            return False

        # 至少要有检索结果
        if not result.retrieved_docs:
            return False

        # MRR 必须大于 0（如果有关键词或相关文档）
        if case.expected_keywords or case.relevant_doc_ids:
            if result.mrr == 0:
                return False

        return True

    def evaluate_all(
        self,
        cases: List[EvaluationCase],
        level: EvaluationLevel = EvaluationLevel.STANDARD
    ) -> EvaluationReport:
        """评估所有用例"""
        logger.info(f"开始 {level.value} 级别评估，共 {len(cases)} 个用例")

        report = EvaluationReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            level=level,
            total_cases=len(cases)
        )

        case_results = []

        for case in cases:
            result = self.evaluate_case(case)
            case_results.append(result)

            if not result.success:
                report.failed_cases.append(result)

            # 实时日志
            status = "✓" if result.success else "✗"
            logger.debug(f"[{status}] {case.case_id}: {case.query[:30]}...")

        report.case_results = case_results

        # 计算总体指标
        self._compute_summary_metrics(report)

        # 分类统计
        self._compute_category_stats(report)

        # 生成建议
        self._generate_recommendations(report)

        return report

    def _compute_summary_metrics(self, report: EvaluationReport):
        """计算汇总指标"""
        results = report.case_results

        if not results:
            return

        # 通过率
        report.passed_cases = sum(1 for r in results if r.success)
        report.failed_cases_count = len(results) - report.passed_cases
        report.pass_rate = round(report.passed_cases / len(results), 4)

        # 错误数量
        report.error_count = sum(1 for r in results if r.error_message)

        # 意图识别准确率
        intent_cases = [
            r for r in results
            if r.detected_intent is not None
        ]
        if intent_cases:
            correct = sum(1 for r in intent_cases if r.intent_correct)
            report.intent_accuracy = round(correct / len(intent_cases), 4)

            # 混淆矩阵
            for r in intent_cases:
                expected = None
                for case in self._last_cases or []:
                    if case.case_id == r.case_id:
                        expected = case.expected_intent
                        break

        # 城市提取准确率
        city_cases = [
            r for r in results
            if r.detected_city is not None
        ]
        if city_cases:
            correct = sum(1 for r in city_cases if r.city_correct)
            report.city_extraction_accuracy = round(correct / len(city_cases), 4)

        # 天数提取准确率
        days_cases = [
            r for r in results
            if r.detected_days is not None
        ]
        if days_cases:
            correct = sum(1 for r in days_cases if r.days_correct)
            report.days_extraction_accuracy = round(correct / len(days_cases), 4)

        # 检索质量指标
        for k in self.k_values:
            recalls = [r.recall_at_k.get(k, 0) for r in results]
            report.mean_recall_at_k[k] = round(sum(recalls) / len(recalls), 4)

            precisions = [r.precision_at_k.get(k, 0) for r in results]
            report.mean_precision_at_k[k] = round(sum(precisions) / len(precisions), 4)

        # MRR
        mrrs = [r.mrr for r in results]
        report.mean_mrr = round(sum(mrrs) / len(mrrs), 4)

        # NDCG
        for k in self.k_values:
            ndcgs = [r.ndcg_at_k.get(k, 0) for r in results]
            report.mean_ndcg_at_k[k] = round(sum(ndcgs) / len(ndcgs), 4)

        # 性能指标
        latencies = [r.latency_ms for r in results]
        report.avg_latency_ms = round(sum(latencies) / len(latencies), 2)

        sorted_latencies = sorted(latencies)
        p50_idx = int(len(sorted_latencies) * 0.50)
        p95_idx = int(len(sorted_latencies) * 0.95)
        p99_idx = int(len(sorted_latencies) * 0.99)

        report.p50_latency_ms = round(sorted_latencies[p50_idx], 2)
        report.p95_latency_ms = round(sorted_latencies[p95_idx], 2)
        report.p99_latency_ms = round(sorted_latencies[p99_idx], 2)
        report.min_latency_ms = round(min(latencies), 2)
        report.max_latency_ms = round(max(latencies), 2)

        # 阶段耗时分析
        all_stages = {}
        for r in results:
            for stage, timing in r.stages_timing.items():
                if stage not in all_stages:
                    all_stages[stage] = []
                all_stages[stage].append(timing)

        for stage, timings in all_stages.items():
            report.stages_breakdown[stage] = round(sum(timings) / len(timings), 2)

    # 临时存储cases用于混淆矩阵计算
    _last_cases: List[EvaluationCase] = None

    def _compute_category_stats(self, report: EvaluationReport):
        """计算分类统计"""
        results_by_category = {}
        results_by_difficulty = {}
        results_by_priority = {}

        for result in report.case_results:
            # 从case中获取分类信息（需要临时存储）
            category = "其他"
            difficulty = "medium"
            priority = "P1"

            # 尝试从case_id推断
            case_id = result.case_id

            if "spot" in case_id:
                category = "景点推荐"
            elif "dining" in case_id:
                category = "餐饮推荐"
            elif "hotel" in case_id or "accommodation" in case_id:
                category = "住宿推荐"
            elif "itin" in case_id or "行程" in case_id:
                category = "行程规划"
            elif "reg" in case_id:
                category = "回归测试"
            else:
                category = "通用查询"

            if "hard" in case_id or "模糊" in case_id:
                difficulty = "hard"
            elif "easy" in case_id:
                difficulty = "easy"
            else:
                difficulty = "medium"

            if "_p0" in case_id:
                priority = "P0"
            elif "_p1" in case_id:
                priority = "P1"
            elif "_p2" in case_id:
                priority = "P2"

            # 统计分类
            if category not in results_by_category:
                results_by_category[category] = {"total": 0, "passed": 0, "failed": 0}
            results_by_category[category]["total"] += 1
            if result.success:
                results_by_category[category]["passed"] += 1
            else:
                results_by_category[category]["failed"] += 1

            # 统计难度
            if difficulty not in results_by_difficulty:
                results_by_difficulty[difficulty] = {"total": 0, "passed": 0, "failed": 0}
            results_by_difficulty[difficulty]["total"] += 1
            if result.success:
                results_by_difficulty[difficulty]["passed"] += 1
            else:
                results_by_difficulty[difficulty]["failed"] += 1

            # 统计优先级
            if priority not in results_by_priority:
                results_by_priority[priority] = {"total": 0, "passed": 0, "failed": 0}
            results_by_priority[priority]["total"] += 1
            if result.success:
                results_by_priority[priority]["passed"] += 1
            else:
                results_by_priority[priority]["failed"] += 1

        report.by_category = results_by_category
        report.by_difficulty = results_by_difficulty
        report.by_priority = results_by_priority

    def _generate_recommendations(self, report: EvaluationReport):
        """生成改进建议"""
        recommendations = []

        # 意图识别问题
        if report.intent_accuracy < 0.8:
            recommendations.append(
                f"意图识别准确率较低 ({report.intent_accuracy:.1%})，"
                "建议优化 IntentDetector 的 prompt 或增加训练数据"
            )

        # 城市提取问题
        if report.city_extraction_accuracy < 0.85:
            recommendations.append(
                f"城市提取准确率较低 ({report.city_extraction_accuracy:.1%})，"
                "建议扩充城市名称词库"
            )

        # 延迟问题
        if report.p95_latency_ms > 3000:
            recommendations.append(
                f"P95 延迟较高 ({report.p95_latency_ms:.0f}ms)，"
                "建议开启缓存或优化检索流程"
            )

        # 召回问题
        recall_5 = report.mean_recall_at_k.get(5, 0)
        if recall_5 < 0.6:
            recommendations.append(
                f"Recall@5 较低 ({recall_5:.1%})，"
                "建议优化向量检索参数或调整分块策略"
            )

        # MRR 问题
        if report.mean_mrr < 0.5:
            recommendations.append(
                f"MRR 较低 ({report.mean_mrr:.1%})，"
                "建议优化 Rerank 模型或调整融合权重"
            )

        # 失败用例分析
        if report.failed_cases_count > 0:
            error_count = sum(1 for r in report.failed_cases if r.error_message)
            intent_fails = sum(
                1 for r in report.failed_cases
                if not r.intent_correct and not r.error_message
            )
            city_fails = sum(
                1 for r in report.failed_cases
                if not r.city_correct and not r.error_message and not r.intent_correct
            )

            if error_count > 0:
                recommendations.append(
                    f"有 {error_count} 个用例执行出错，"
                    "建议检查系统稳定性和错误处理"
                )

            if intent_fails > 0:
                recommendations.append(
                    f"有 {intent_fails} 个用例意图识别错误，"
                    "建议检查意图检测逻辑"
                )

            if city_fails > 0:
                recommendations.append(
                    f"有 {city_fails} 个用例城市提取错误，"
                    "建议扩充城市识别词库"
                )

        # 难度分析
        if "hard" in report.by_difficulty:
            hard_stats = report.by_difficulty["hard"]
            hard_pass_rate = hard_stats["passed"] / hard_stats["total"] if hard_stats["total"] > 0 else 0
            if hard_pass_rate < 0.5:
                recommendations.append(
                    f"困难用例通过率较低 ({hard_pass_rate:.1%})，"
                    "建议优化查询扩展和模糊匹配能力"
                )

        # P0 用例检查
        if "P0" in report.by_priority:
            p0_stats = report.by_priority["P0"]
            if p0_stats["failed"] > 0:
                recommendations.append(
                    f"⚠️ 有 {p0_stats['failed']} 个 P0 核心用例失败，"
                    "必须优先修复！"
                )

        report.recommendations = recommendations
