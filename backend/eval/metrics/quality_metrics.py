"""
质量指标计算模块
"""

from typing import List, Dict, Optional, Tuple
from collections import Counter


class QualityMetrics:
    """质量指标计算器"""

    @staticmethod
    def intent_accuracy(
        detected_intents: List[str],
        expected_intents: List[str]
    ) -> float:
        """
        计算意图识别准确率

        Args:
            detected_intents: 检测到的意图列表
            expected_intents: 期望的意图列表

        Returns:
            准确率 [0, 1]
        """
        if not detected_intents or not expected_intents:
            return 0.0

        correct = sum(
            1 for d, e in zip(detected_intents, expected_intents)
            if d == e
        )
        accuracy = correct / len(expected_intents)
        return round(accuracy, 4)

    @staticmethod
    def intent_confusion_matrix(
        detected_intents: List[str],
        expected_intents: List[str]
    ) -> Dict[str, Dict[str, int]]:
        """
        计算意图混淆矩阵

        Args:
            detected_intents: 检测到的意图列表
            expected_intents: 期望的意图列表

        Returns:
            混淆矩阵 {"expected": {"detected": count}}
        """
        matrix: Dict[str, Dict[str, int]] = {}

        for expected, detected in zip(expected_intents, detected_intents):
            if expected not in matrix:
                matrix[expected] = Counter()

            matrix[expected][detected] += 1

        return dict(matrix)

    @staticmethod
    def city_accuracy(
        detected_cities: List[Optional[str]],
        expected_cities: List[Optional[str]]
    ) -> float:
        """
        计算城市提取准确率

        Args:
            detected_cities: 检测到的城市列表
            expected_cities: 期望的城市列表

        Returns:
            准确率 [0, 1]
        """
        if not detected_cities or not expected_cities:
            return 0.0

        # 只统计有期望城市的情况
        valid_pairs = [
            (d, e) for d, e in zip(detected_cities, expected_cities)
            if e is not None
        ]

        if not valid_pairs:
            return 1.0  # 没有需要验证的城市

        correct = sum(1 for d, e in valid_pairs if d == e)
        accuracy = correct / len(valid_pairs)
        return round(accuracy, 4)

    @staticmethod
    def days_accuracy(
        detected_days: List[Optional[int]],
        expected_days: List[Optional[int]],
        tolerance: int = 0
    ) -> float:
        """
        计算天数提取准确率

        Args:
            detected_days: 检测到的天数列表
            expected_days: 期望的天数列表
            tolerance: 允许的误差（天）

        Returns:
            准确率 [0, 1]
        """
        if not detected_days or not expected_days:
            return 0.0

        # 只统计有期望天数的情况
        valid_pairs = [
            (d, e) for d, e in zip(detected_days, expected_days)
            if e is not None
        ]

        if not valid_pairs:
            return 1.0  # 没有需要验证的天数

        correct = sum(
            1 for d, e in valid_pairs
            if d is not None and abs(d - e) <= tolerance
        )
        accuracy = correct / len(valid_pairs)
        return round(accuracy, 4)

    @staticmethod
    def pass_rate(passed: int, total: int) -> float:
        """
        计算通过率

        Args:
            passed: 通过数量
            total: 总数量

        Returns:
            通过率 [0, 1]
        """
        if total == 0:
            return 0.0
        return round(passed / total, 4)

    @staticmethod
    def success_rate(successes: int, total: int) -> float:
        """
        计算成功率（与通过率相同，但语义不同）

        Args:
            successes: 成功数量
            total: 总数量

        Returns:
            成功率 [0, 1]
        """
        return QualityMetrics.pass_rate(successes, total)

    @staticmethod
    def error_rate(errors: int, total: int) -> float:
        """
        计算错误率

        Args:
            errors: 错误数量
            total: 总数量

        Returns:
            错误率 [0, 1]
        """
        return 1.0 - QualityMetrics.pass_rate(total - errors, total)

    @staticmethod
    def relevance_distribution(
        relevance_scores: List[float],
        bins: int = 5
    ) -> Dict[str, int]:
        """
        计算相关性分数分布

        Args:
            relevance_scores: 相关性分数列表
            bins: 分箱数量

        Returns:
            各区间的数量分布
        """
        if not relevance_scores:
            return {}

        min_score = min(relevance_scores)
        max_score = max(relevance_scores)

        if min_score == max_score:
            return {f"{min_score:.2f}": len(relevance_scores)}

        bin_width = (max_score - min_score) / bins
        distribution = {}

        for score in relevance_scores:
            bin_index = min(int((score - min_score) / bin_width), bins - 1)
            bin_start = min_score + bin_index * bin_width
            bin_label = f"{bin_start:.2f}-{bin_start + bin_width:.2f}"

            distribution[bin_label] = distribution.get(bin_label, 0) + 1

        return distribution

    @staticmethod
    def mean_relevance(relevance_scores: List[float]) -> float:
        """
        计算平均相关性

        Args:
            relevance_scores: 相关性分数列表

        Returns:
            平均相关性
        """
        if not relevance_scores:
            return 0.0
        return round(sum(relevance_scores) / len(relevance_scores), 4)

    @staticmethod
    def category_breakdown(
        results: List[Dict]
    ) -> Dict[str, Dict[str, int]]:
        """
        按分类统计结果

        Args:
            results: 结果列表，每个包含 category 和 success 字段

        Returns:
            分类统计 {"category": {"total": n, "passed": m}}
        """
        breakdown: Dict[str, Dict[str, int]] = {}

        for result in results:
            category = result.get("category", "unknown")
            success = result.get("success", False)

            if category not in breakdown:
                breakdown[category] = {"total": 0, "passed": 0}

            breakdown[category]["total"] += 1
            if success:
                breakdown[category]["passed"] += 1

        return breakdown

    @staticmethod
    def difficulty_analysis(
        results: List[Dict]
    ) -> Dict[str, Dict[str, float]]:
        """
        按难度等级分析结果

        Args:
            results: 结果列表，每个包含 difficulty 和相关指标

        Returns:
            难度分析 {"easy": {"pass_rate": 0.9, "avg_latency": 100}, ...}
        """
        by_difficulty: Dict[str, List[Dict]] = {}

        for result in results:
            difficulty = result.get("difficulty", "medium")
            if difficulty not in by_difficulty:
                by_difficulty[difficulty] = []
            by_difficulty[difficulty].append(result)

        analysis = {}
        for difficulty, items in by_difficulty.items():
            total = len(items)
            passed = sum(1 for item in items if item.get("success", False))
            latencies = [item.get("latency_ms", 0) for item in items]

            analysis[difficulty] = {
                "total": total,
                "passed": passed,
                "pass_rate": round(passed / total, 4) if total > 0 else 0.0,
                "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            }

        return analysis

    @staticmethod
    def trend_indicators(
        current: Dict[str, float],
        baseline: Dict[str, float]
    ) -> Dict[str, Tuple[str, float]]:
        """
        计算趋势指标（相对于基线的变化）

        Args:
            current: 当前指标
            baseline: 基线指标

        Returns:
            趋势 {"metric_name": ("improved/declined/stable", change_ratio)}
        """
        indicators = {}

        for metric, value in current.items():
            if metric not in baseline:
                continue

            base = baseline[metric]
            if base == 0:
                continue

            change = (value - base) / base

            if change > 0.05:
                status = "improved"
            elif change < -0.05:
                status = "declined"
            else:
                status = "stable"

            indicators[metric] = (status, round(change, 4))

        return indicators
