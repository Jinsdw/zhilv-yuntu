"""
RAG 系统持续监控与告警
"""

import json
import time
from pathlib import Path
from typing import Optional, List, Callable, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from loguru import logger


@dataclass
class MonitorConfig:
    """监控配置"""
    # 评估触发条件
    auto_eval_interval_hours: int = 24  # 自动评估间隔（小时）
    regression_threshold: float = 0.05  # 回归阈值（指标下降超过此值触发告警）
    latency_threshold_ms: int = 3000  # 延迟告警阈值
    pass_rate_threshold: float = 0.85  # 通过率告警阈值

    # 告警配置
    alert_enabled: bool = True
    alert_webhook: Optional[str] = None  # Webhook URL
    alert_email: Optional[str] = None  # 邮箱地址

    # 数据持久化
    history_dir: str = "backend/eval/history"
    keep_history_days: int = 30  # 保留历史数据天数


@dataclass
class HealthStatus:
    """健康状态"""
    timestamp: str
    status: str  # healthy/degraded/unhealthy
    metrics: Dict[str, Any] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    compared_to_baseline: Dict[str, Any] = field(default_factory=dict)


class RAGMonitor:
    """RAG 系统监控器"""

    def __init__(self, config: Optional[MonitorConfig] = None):
        self.config = config or MonitorConfig()
        self.history_dir = Path(self.config.history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)

        self._last_eval_time: Optional[datetime] = None
        self._last_eval_result: Optional[Dict] = None
        self._baseline: Optional[Dict] = None

    def check_health(self) -> HealthStatus:
        """执行健康检查"""
        status = HealthStatus(
            timestamp=datetime.now().isoformat(),
            status="healthy",
            metrics={},
            alerts=[],
            recommendations=[]
        )

        # 加载历史评估数据
        history = self._load_recent_history()

        if not history:
            status.metrics["has_baseline"] = False
            status.recommendations.append("首次部署，建议运行完整评估建立基线")
            return status

        status.metrics["has_baseline"] = True
        status.metrics["history_points"] = len(history)

        # 设置基线（最早的记录）
        self._baseline = history[0]

        # 分析趋势
        trends = self._analyze_trends(history)
        status.metrics["trends"] = trends

        # 获取最新指标
        latest = history[-1]
        status.metrics["latest"] = {
            "pass_rate": latest.get("summary", {}).get("pass_rate", "0%"),
            "latency": latest.get("metrics", {}).get("latency", {}).get("avg_ms", "0ms"),
            "mrr": latest.get("metrics", {}).get("mean_mrr", "0%"),
        }

        # 检查各项指标
        self._check_pass_rate(status, trends, history)
        self._check_latency(status, trends, history)
        self._check_recall(status, trends, history)
        self._check_intent_accuracy(status, trends, history)

        # 计算相对于基线的变化
        status.compared_to_baseline = self._compare_to_baseline(history[-1], history[0])

        # 更新状态
        if status.alerts:
            critical_count = sum(1 for a in status.alerts if "P0" in a or "必须" in a)
            if critical_count > 0:
                status.status = "unhealthy"
            elif len(status.alerts) >= 3:
                status.status = "degraded"
            else:
                status.status = "degraded"

        return status

    def _load_recent_history(self, days: int = 7) -> List[Dict]:
        """加载最近的历史数据"""
        history = []
        cutoff_date = datetime.now() - timedelta(days=days)

        for file_path in sorted(self.history_dir.glob("*.json")):
            try:
                # 从文件名解析日期
                parts = file_path.stem.split("_")
                if len(parts) >= 2:
                    file_time = datetime.strptime(parts[-1], "%Y%m%d_%H%M%S")
                    if file_time >= cutoff_date:
                        with open(file_path, "r", encoding="utf-8") as f:
                            history.append(json.load(f))
            except Exception:
                continue

        return history

    def _analyze_trends(self, history: List[Dict]) -> Dict[str, Any]:
        """分析指标趋势"""
        if len(history) < 2:
            return {"data_points": len(history), "trend": "insufficient_data"}

        trends = {}

        # 提取各项指标
        pass_rates = []
        latencies = []
        mrrs = []

        for record in history:
            summary = record.get("summary", {})
            metrics = record.get("metrics", {})

            # 解析 pass_rate
            pr = summary.get("pass_rate", "0%")
            if isinstance(pr, str):
                pr = float(pr.rstrip("%")) / 100
            pass_rates.append(pr)

            # 解析 latency
            lat = metrics.get("latency", {}).get("avg_ms", "0ms")
            if isinstance(lat, str):
                lat = float(lat.rstrip("ms"))
            latencies.append(lat)

            # 解析 MRR
            mrr = metrics.get("mean_mrr", "0%")
            if isinstance(mrr, str):
                mrr = float(mrr.rstrip("%")) / 100
            mrrs.append(mrr)

        # 计算趋势（简单线性回归斜率）
        def calc_slope(values: List[float]) -> float:
            if len(values) < 2:
                return 0.0
            n = len(values)
            x_mean = (n - 1) / 2.0
            y_mean = sum(values) / n
            numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            return numerator / (denominator + 1e-8)

        trends["pass_rate_trend"] = round(calc_slope(pass_rates), 6)
        trends["latency_trend"] = round(calc_slope(latencies), 2)
        trends["mrr_trend"] = round(calc_slope(mrrs), 6)
        trends["data_points"] = len(history)

        # 相对于基线的变化
        if len(history) >= 2:
            baseline = history[0]
            latest = history[-1]

            baseline_pr = self._parse_percentage(baseline.get("summary", {}).get("pass_rate", "0%"))
            latest_pr = self._parse_percentage(latest.get("summary", {}).get("pass_rate", "0%"))
            trends["pass_rate_change"] = round(latest_pr - baseline_pr, 4)

            baseline_lat = self._parse_latency(baseline.get("metrics", {}).get("latency", {}).get("avg_ms", "0ms"))
            latest_lat = self._parse_latency(latest.get("metrics", {}).get("latency", {}).get("avg_ms", "0ms"))
            trends["latency_change"] = round(latest_lat - baseline_lat, 2)

        return trends

    def _parse_percentage(self, value: Any) -> float:
        """解析百分比值"""
        if isinstance(value, float):
            return value
        if isinstance(value, int):
            return float(value)
        if isinstance(value, str):
            return float(value.rstrip("%")) / 100
        return 0.0

    def _parse_latency(self, value: Any) -> float:
        """解析延迟值"""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value.rstrip("ms"))
        return 0.0

    def _compare_to_baseline(self, latest: Dict, baseline: Dict) -> Dict[str, Any]:
        """计算相对于基线的变化"""
        comparison = {}

        # 通过率变化
        latest_pr = self._parse_percentage(latest.get("summary", {}).get("pass_rate", "0%"))
        baseline_pr = self._parse_percentage(baseline.get("summary", {}).get("pass_rate", "0%"))
        comparison["pass_rate"] = {
            "baseline": f"{baseline_pr:.1%}",
            "latest": f"{latest_pr:.1%}",
            "change": f"{latest_pr - baseline_pr:+.1%}",
            "status": "improved" if latest_pr > baseline_pr else "declined" if latest_pr < baseline_pr else "stable"
        }

        # 延迟变化
        latest_lat = self._parse_latency(latest.get("metrics", {}).get("latency", {}).get("avg_ms", "0ms"))
        baseline_lat = self._parse_latency(baseline.get("metrics", {}).get("latency", {}).get("avg_ms", "0ms"))
        comparison["latency"] = {
            "baseline": f"{baseline_lat:.0f}ms",
            "latest": f"{latest_lat:.0f}ms",
            "change": f"{latest_lat - baseline_lat:+.0f}ms",
            "status": "improved" if latest_lat < baseline_lat else "declined" if latest_lat > baseline_lat else "stable"
        }

        # MRR 变化
        latest_mrr = self._parse_percentage(latest.get("metrics", {}).get("mean_mrr", "0%"))
        baseline_mrr = self._parse_percentage(baseline.get("metrics", {}).get("mean_mrr", "0%"))
        comparison["mrr"] = {
            "baseline": f"{baseline_mrr:.1%}",
            "latest": f"{latest_mrr:.1%}",
            "change": f"{latest_mrr - baseline_mrr:+.1%}",
            "status": "improved" if latest_mrr > baseline_mrr else "declined" if latest_mrr < baseline_mrr else "stable"
        }

        return comparison

    def _check_pass_rate(self, status: HealthStatus, trends: Dict, history: List[Dict]):
        """检查通过率"""
        if not history:
            return

        latest = history[-1]
        latest_pr = self._parse_percentage(latest.get("summary", {}).get("pass_rate", "0%"))

        # 检查阈值
        if latest_pr < self.config.pass_rate_threshold:
            status.alerts.append(
                f"🚨 通过率 ({latest_pr:.1%}) 低于阈值 ({self.config.pass_rate_threshold:.1%})"
            )

        # 检查回归
        change = trends.get("pass_rate_change", 0)
        if change < -self.config.regression_threshold:
            status.alerts.append(
                f"⚠️ 通过率下降 {abs(change):.1%}，"
                f"超过回归阈值 {self.config.regression_threshold:.1%}"
            )

    def _check_latency(self, status: HealthStatus, trends: Dict, history: List[Dict]):
        """检查延迟"""
        if not history:
            return

        latest = history[-1]
        latest_lat = self._parse_latency(latest.get("metrics", {}).get("latency", {}).get("avg_ms", "0ms"))

        # 检查阈值
        if latest_lat > self.config.latency_threshold_ms:
            status.alerts.append(
                f"🚨 延迟 ({latest_lat:.0f}ms) 超过阈值 ({self.config.latency_threshold_ms}ms)"
            )

        # 检查趋势
        latency_trend = trends.get("latency_trend", 0)
        if latency_trend > 100:  # 每评估周期增加超过100ms
            status.alerts.append(
                f"⚠️ 延迟呈上升趋势 (+{latency_trend:.0f}ms/周期)"
            )

    def _check_recall(self, status: HealthStatus, trends: Dict, history: List[Dict]):
        """检查召回率"""
        if not history:
            return

        latest = history[-1]
        mrr_trend = trends.get("mrr_trend", 0)

        if mrr_trend < -0.02:  # MRR 持续下降
            status.alerts.append(
                f"⚠️ MRR 指标呈下降趋势 ({mrr_trend:.2%}/周期)"
            )

    def _check_intent_accuracy(self, status: HealthStatus, trends: Dict, history: List[Dict]):
        """检查意图识别准确率"""
        if not history:
            return

        latest = history[-1]
        intent_acc = self._parse_percentage(latest.get("metrics", {}).get("intent_accuracy", "0%"))

        if intent_acc < 0.75:
            status.alerts.append(
                f"⚠️ 意图识别准确率较低 ({intent_acc:.1%})"
            )

    def should_run_auto_eval(self) -> bool:
        """判断是否应该运行自动评估"""
        if self._last_eval_time is None:
            return True

        elapsed = datetime.now() - self._last_eval_time
        return elapsed.total_seconds() >= self.config.auto_eval_interval_hours * 3600

    def record_eval_result(self, result: Dict):
        """记录评估结果"""
        self._last_eval_time = datetime.now()
        self._last_eval_result = result

        # 保存到历史文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = self.history_dir / f"eval_result_{timestamp}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"评估结果已保存: {file_path}")

        # 清理过期文件
        self._cleanup_old_files()

    def _cleanup_old_files(self):
        """清理过期文件"""
        cutoff = datetime.now() - timedelta(days=self.config.keep_history_days)

        for file_path in self.history_dir.glob("*.json"):
            try:
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if mtime < cutoff:
                    file_path.unlink()
                    logger.debug(f"删除过期文件: {file_path}")
            except Exception:
                continue

    def send_alert(self, status: HealthStatus):
        """发送告警"""
        if not self.config.alert_enabled or not status.alerts:
            return

        alert_message = {
            "msgtype": "text",
            "text": {
                "content": f"🚨 RAG 系统告警\n\n状态: {status.status}\n时间: {status.timestamp}\n\n告警内容:\n" +
                           "\n".join(f"- {a}" for a in status.alerts)
            }
        }

        # Webhook 通知
        if self.config.alert_webhook:
            try:
                import requests
                requests.post(
                    self.config.alert_webhook,
                    json=alert_message,
                    timeout=5
                )
                logger.info("告警已发送至 Webhook")
            except ImportError:
                logger.warning("requests 库未安装，无法发送 Webhook 告警")
            except Exception as e:
                logger.error(f"Webhook 告警失败: {e}")

        # 邮箱通知
        if self.config.alert_email:
            logger.info(f"邮箱告警准备发送到: {self.config.alert_email}")
            # TODO: 实现邮件发送

    def run_scheduled_check(self, eval_callback: Callable) -> HealthStatus:
        """
        运行定时检查

        Args:
            eval_callback: 评估回调函数

        Returns:
            健康状态
        """
        # 检查是否需要自动评估
        if self.should_run_auto_eval():
            logger.info("触发自动评估...")
            try:
                result = eval_callback()

                # 保存结果
                if isinstance(result, dict):
                    self.record_eval_result(result)
                else:
                    # 可能是 EvaluationReport
                    self.record_eval_result(result.to_dict())

                self._last_eval_time = datetime.now()
            except Exception as e:
                logger.error(f"自动评估失败: {e}")

        # 执行健康检查
        health = self.check_health()

        # 发送告警
        if health.alerts:
            self.send_alert(health)

        return health

    def get_history_summary(self, days: int = 30) -> Dict[str, Any]:
        """获取历史摘要"""
        history = self._load_recent_history(days)

        if not history:
            return {"status": "no_data", "message": "没有历史数据"}

        # 计算统计
        pass_rates = [self._parse_percentage(h.get("summary", {}).get("pass_rate", "0%")) for h in history]
        latencies = [self._parse_latency(h.get("metrics", {}).get("latency", {}).get("avg_ms", "0ms")) for h in history]

        return {
            "status": "ok",
            "period_days": days,
            "data_points": len(history),
            "date_range": {
                "from": history[0].get("summary", {}).get("timestamp", ""),
                "to": history[-1].get("summary", {}).get("timestamp", "")
            },
            "pass_rate": {
                "avg": round(sum(pass_rates) / len(pass_rates), 4),
                "min": round(min(pass_rates), 4),
                "max": round(max(pass_rates), 4),
            },
            "latency": {
                "avg_ms": round(sum(latencies) / len(latencies), 2),
                "min_ms": round(min(latencies), 2),
                "max_ms": round(max(latencies), 2),
            },
            "baseline": {
                "pass_rate": f"{pass_rates[0]:.1%}",
                "latency_ms": f"{latencies[0]:.0f}",
            },
            "latest": {
                "pass_rate": f"{pass_rates[-1]:.1%}",
                "latency_ms": f"{latencies[-1]:.0f}",
            }
        }
