"""
延迟性能指标计算模块
"""

from typing import List, Dict, Optional
import statistics


class LatencyMetrics:
    """延迟性能指标计算器"""

    @staticmethod
    def mean(latencies: List[float]) -> float:
        """
        计算平均延迟

        Args:
            latencies: 延迟列表（毫秒）

        Returns:
            平均延迟
        """
        if not latencies:
            return 0.0
        return round(statistics.mean(latencies), 2)

    @staticmethod
    def median(latencies: List[float]) -> float:
        """
        计算中位数延迟

        Args:
            latencies: 延迟列表（毫秒）

        Returns:
            中位数延迟
        """
        if not latencies:
            return 0.0
        return round(statistics.median(latencies), 2)

    @staticmethod
    def p95(latencies: List[float]) -> float:
        """
        计算 P95 延迟

        Args:
            latencies: 延迟列表（毫秒）

        Returns:
            P95 延迟
        """
        if not latencies:
            return 0.0

        sorted_latencies = sorted(latencies)
        index = int(len(sorted_latencies) * 0.95)
        return round(sorted_latencies[min(index, len(sorted_latencies) - 1)], 2)

    @staticmethod
    def p99(latencies: List[float]) -> float:
        """
        计算 P99 延迟

        Args:
            latencies: 延迟列表（毫秒）

        Returns:
            P99 延迟
        """
        if not latencies:
            return 0.0

        sorted_latencies = sorted(latencies)
        index = int(len(sorted_latencies) * 0.99)
        return round(sorted_latencies[min(index, len(sorted_latencies) - 1)], 2)

    @staticmethod
    def min_max(latencies: List[float]) -> Dict[str, float]:
        """
        计算最小和最大延迟

        Args:
            latencies: 延迟列表（毫秒）

        Returns:
            {"min": 最小值, "max": 最大值}
        """
        if not latencies:
            return {"min": 0.0, "max": 0.0}

        return {
            "min": round(min(latencies), 2),
            "max": round(max(latencies), 2)
        }

    @staticmethod
    def std_dev(latencies: List[float]) -> float:
        """
        计算标准差

        Args:
            latencies: 延迟列表（毫秒）

        Returns:
            标准差
        """
        if len(latencies) < 2:
            return 0.0
        return round(statistics.stdev(latencies), 2)

    @staticmethod
    def percentile_list(
        latencies: List[float],
        percentiles: List[int] = None
    ) -> Dict[str, float]:
        """
        计算多个百分位数

        Args:
            latencies: 延迟列表（毫秒）
            percentiles: 百分位数列表，如 [50, 75, 90, 95, 99]

        Returns:
            百分位数字典，如 {"p50": 100.0, "p95": 300.0, ...}
        """
        if not latencies:
            return {f"p{p}": 0.0 for p in (percentiles or [50, 75, 90, 95, 99])}

        if percentiles is None:
            percentiles = [50, 75, 90, 95, 99]

        sorted_latencies = sorted(latencies)
        result = {}

        for p in percentiles:
            index = int(len(sorted_latencies) * (p / 100))
            result[f"p{p}"] = round(
                sorted_latencies[min(index, len(sorted_latencies) - 1)], 2
            )

        return result

    @staticmethod
    def throughput(requests: int, total_time_ms: float) -> float:
        """
        计算吞吐量（QPS）

        Args:
            requests: 请求数量
            total_time_ms: 总耗时（毫秒）

        Returns:
            QPS
        """
        if total_time_ms <= 0:
            return 0.0

        total_seconds = total_time_ms / 1000
        return round(requests / total_seconds, 2)

    @staticmethod
    def latency_breakdown(stages_timings: List[Dict[str, float]]) -> Dict[str, float]:
        """
        分析各阶段耗时分布

        Args:
            stages_timings: 各用例的阶段耗时列表

        Returns:
            各阶段平均耗时
        """
        if not stages_timings:
            return {}

        all_stages = set()
        for timing in stages_timings:
            all_stages.update(timing.keys())

        breakdown = {}
        for stage in all_stages:
            values = [t.get(stage, 0) for t in stages_timings]
            breakdown[stage] = round(statistics.mean(values), 2)

        return breakdown

    @staticmethod
    def summary(latencies: List[float]) -> Dict[str, float]:
        """
        生成延迟汇总指标

        Args:
            latencies: 延迟列表（毫秒）

        Returns:
            完整的延迟统计摘要
        """
        if not latencies:
            return {
                "mean_ms": 0.0,
                "median_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "std_dev_ms": 0.0,
            }

        return {
            "mean_ms": LatencyMetrics.mean(latencies),
            "median_ms": LatencyMetrics.median(latencies),
            "p50_ms": LatencyMetrics.percentile_list(latencies, [50])["p50"],
            "p75_ms": LatencyMetrics.percentile_list(latencies, [75])["p75"],
            "p90_ms": LatencyMetrics.percentile_list(latencies, [90])["p90"],
            "p95_ms": LatencyMetrics.p95(latencies),
            "p99_ms": LatencyMetrics.p99(latencies),
            "min_ms": round(min(latencies), 2),
            "max_ms": round(max(latencies), 2),
            "std_dev_ms": LatencyMetrics.std_dev(latencies),
            "count": len(latencies),
        }
