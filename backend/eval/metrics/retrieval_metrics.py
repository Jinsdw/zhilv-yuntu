"""
检索质量指标计算模块
提供 Recall、Precision、MRR、NDCG 等指标的完整实现
"""

from typing import List, Dict, Optional
import math


class RetrievalMetrics:
    """检索质量指标计算器"""

    @staticmethod
    def recall_at_k(
        retrieved_ids: List[str],
        relevant_ids: List[str],
        k: int
    ) -> float:
        """
        计算 Recall@K

        Args:
            retrieved_ids: 检索返回的文档ID列表
            relevant_ids: 相关文档ID列表
            k: 截取位置

        Returns:
            Recall@K 值 [0, 1]
        """
        if not relevant_ids:
            return 0.0

        retrieved_at_k = set(retrieved_ids[:k])
        relevant_set = set(relevant_ids)

        recall = len(retrieved_at_k & relevant_set) / len(relevant_set)
        return round(recall, 4)

    @staticmethod
    def precision_at_k(
        retrieved_ids: List[str],
        relevant_ids: List[str],
        k: int
    ) -> float:
        """
        计算 Precision@K

        Args:
            retrieved_ids: 检索返回的文档ID列表
            relevant_ids: 相关文档ID列表
            k: 截取位置

        Returns:
            Precision@K 值 [0, 1]
        """
        if not retrieved_ids or k <= 0:
            return 0.0

        retrieved_at_k = retrieved_ids[:k]
        relevant_set = set(relevant_ids)

        relevant_count = sum(1 for doc_id in retrieved_at_k if doc_id in relevant_set)
        precision = relevant_count / min(k, len(retrieved_at_k))
        return round(precision, 4)

    @staticmethod
    def f1_at_k(
        retrieved_ids: List[str],
        relevant_ids: List[str],
        k: int
    ) -> float:
        """
        计算 F1@K

        Args:
            retrieved_ids: 检索返回的文档ID列表
            relevant_ids: 相关文档ID列表
            k: 截取位置

        Returns:
            F1@K 值 [0, 1]
        """
        precision = RetrievalMetrics.precision_at_k(retrieved_ids, relevant_ids, k)
        recall = RetrievalMetrics.recall_at_k(retrieved_ids, relevant_ids, k)

        if precision + recall == 0:
            return 0.0

        f1 = 2 * (precision * recall) / (precision + recall)
        return round(f1, 4)

    @staticmethod
    def mean_reciprocal_rank(
        retrieved_ids: List[str],
        relevant_ids: List[str]
    ) -> float:
        """
        计算 MRR (Mean Reciprocal Rank)

        Args:
            retrieved_ids: 检索返回的文档ID列表
            relevant_ids: 相关文档ID列表

        Returns:
            MRR 值 [0, 1]
        """
        if not retrieved_ids or not relevant_ids:
            return 0.0

        relevant_set = set(relevant_ids)

        for i, doc_id in enumerate(retrieved_ids, 1):
            if doc_id in relevant_set:
                return round(1.0 / i, 4)

        return 0.0

    @staticmethod
    def dcg_at_k(
        relevance_scores: List[float],
        k: int
    ) -> float:
        """
        计算 DCG@K (Discounted Cumulative Gain)

        Args:
            relevance_scores: 每篇文档的相关性分数列表
            k: 截取位置

        Returns:
            DCG@K 值
        """
        dcg = 0.0
        for i, score in enumerate(relevance_scores[:k], 1):
            dcg += score / math.log2(i + 1) if i > 1 else score
        return round(dcg, 4)

    @staticmethod
    def ndcg_at_k(
        retrieved_ids: List[str],
        relevance_scores: Dict[str, float],
        k: int
    ) -> float:
        """
        计算 NDCG@K (Normalized Discounted Cumulative Gain)

        Args:
            retrieved_ids: 检索返回的文档ID列表
            relevance_scores: 文档ID到相关性分数的映射
            k: 截取位置

        Returns:
            NDCG@K 值 [0, 1]
        """
        if not retrieved_ids:
            return 0.0

        # 计算 DCG
        retrieved_scores = []
        for doc_id in retrieved_ids[:k]:
            score = relevance_scores.get(doc_id, 0.0)
            retrieved_scores.append(score)

        dcg = RetrievalMetrics.dcg_at_k(retrieved_scores, k)

        # 计算 IDCG（理想情况）
        ideal_scores = sorted(relevance_scores.values(), reverse=True)[:k]
        idcg = RetrievalMetrics.dcg_at_k(ideal_scores, k)

        if idcg == 0:
            return 0.0

        ndcg = dcg / idcg
        return round(ndcg, 4)

    @staticmethod
    def average_precision(
        retrieved_ids: List[str],
        relevant_ids: List[str]
    ) -> float:
        """
        计算 Average Precision (AP)

        Args:
            retrieved_ids: 检索返回的文档ID列表
            relevant_ids: 相关文档ID列表

        Returns:
            AP 值 [0, 1]
        """
        if not retrieved_ids or not relevant_ids:
            return 0.0

        relevant_set = set(relevant_ids)
        num_relevant = len(relevant_set)
        num_retrieved = len(retrieved_ids)

        if num_relevant == 0 or num_relevant == 0:
            return 0.0

        hits = 0
        sum_precision = 0.0

        for i, doc_id in enumerate(retrieved_ids, 1):
            if doc_id in relevant_set:
                hits += 1
                sum_precision += hits / i

        if hits == 0:
            return 0.0

        ap = sum_precision / num_relevant
        return round(ap, 4)

    @staticmethod
    def mean_average_precision(
        all_retrieved: List[List[str]],
        all_relevant: List[List[str]]
    ) -> float:
        """
        计算 MAP (Mean Average Precision)

        Args:
            all_retrieved: 所有查询的检索结果列表
            all_relevant: 所有查询的相关文档列表

        Returns:
            MAP 值 [0, 1]
        """
        if not all_retrieved or not all_relevant:
            return 0.0

        aps = []
        for retrieved, relevant in zip(all_retrieved, all_relevant):
            ap = RetrievalMetrics.average_precision(retrieved, relevant)
            aps.append(ap)

        map_score = sum(aps) / len(aps) if aps else 0.0
        return round(map_score, 4)

    @staticmethod
    def coverage(
        retrieved_ids: List[str],
        all_doc_ids: List[str]
    ) -> float:
        """
        计算覆盖率（检索结果在文档库中的覆盖率）

        Args:
            retrieved_ids: 检索返回的文档ID列表
            all_doc_ids: 文档库中所有文档ID列表

        Returns:
            覆盖率 [0, 1]
        """
        if not all_doc_ids:
            return 0.0

        retrieved_set = set(retrieved_ids)
        all_set = set(all_doc_ids)

        coverage = len(retrieved_set & all_set) / len(retrieved_set) if retrieved_set else 0.0
        return round(coverage, 4)

    @staticmethod
    def diversity(
        retrieved_ids: List[str],
        doc_categories: Dict[str, str]
    ) -> float:
        """
        计算结果多样性（不同类别的分布）

        Args:
            retrieved_ids: 检索返回的文档ID列表
            doc_categories: 文档ID到类别的映射

        Returns:
            多样性分数 [0, 1]，越高表示越多样
        """
        if not retrieved_ids:
            return 0.0

        categories = []
        for doc_id in retrieved_ids:
            if doc_id in doc_categories:
                categories.append(doc_categories[doc_id])

        if not categories:
            return 0.0

        unique_categories = len(set(categories))
        total_categories = len(categories)

        diversity = unique_categories / total_categories
        return round(diversity, 4)
