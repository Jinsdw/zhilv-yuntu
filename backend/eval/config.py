"""
评估模块配置
"""

# 评估级别配置
EVALUATION_LEVELS = {
    "quick": {
        "description": "快速评估（核心用例）",
        "max_cases": 10,
        "timeout_per_case_ms": 5000,
        "description_zh": "仅测试 P0 核心用例"
    },
    "standard": {
        "description": "标准评估（日常使用）",
        "max_cases": 50,
        "timeout_per_case_ms": 3000,
        "description_zh": "包含基础用例和意图识别用例"
    },
    "full": {
        "description": "完整评估（版本发布前）",
        "max_cases": 200,
        "timeout_per_case_ms": 3000,
        "description_zh": "包含所有用例类型"
    }
}

# 指标阈值配置
THRESHOLDS = {
    # 意图识别
    "intent_accuracy": {
        "good": 0.90,
        "acceptable": 0.85,
        "poor": 0.75,
        "description": "意图识别准确率"
    },

    # 城市提取
    "city_accuracy": {
        "good": 0.95,
        "acceptable": 0.90,
        "poor": 0.80,
        "description": "城市提取准确率"
    },

    # 天数提取
    "days_accuracy": {
        "good": 0.95,
        "acceptable": 0.90,
        "poor": 0.80,
        "description": "天数提取准确率"
    },

    # 召回指标
    "recall_at_5": {
        "good": 0.70,
        "acceptable": 0.60,
        "poor": 0.50,
        "description": "Recall@5"
    },

    # MRR
    "mrr": {
        "good": 0.60,
        "acceptable": 0.50,
        "poor": 0.40,
        "description": "平均倒数排名"
    },

    # NDCG
    "ndcg_at_5": {
        "good": 0.65,
        "acceptable": 0.55,
        "poor": 0.45,
        "description": "NDCG@5"
    },

    # 性能
    "latency_p50_ms": {
        "good": 1000,
        "acceptable": 2000,
        "poor": 3000,
        "description": "P50 延迟"
    },
    "latency_p95_ms": {
        "good": 2000,
        "acceptable": 3000,
        "poor": 5000,
        "description": "P95 延迟"
    },
    "latency_p99_ms": {
        "good": 3000,
        "acceptable": 5000,
        "poor": 8000,
        "description": "P99 延迟"
    },

    # 通过率
    "pass_rate": {
        "good": 0.90,
        "acceptable": 0.85,
        "poor": 0.75,
        "description": "用例通过率"
    }
}

# 告警配置
ALERT_CONFIG = {
    "enabled": True,
    "regression_threshold": 0.05,  # 指标下降超过 5% 触发告警
    "critical_regression_threshold": 0.10,  # 指标下降超过 10% 为严重告警
    "cooldown_minutes": 60,  # 告警冷却时间（分钟）
    "webhook": {
        "enabled": False,
        "url": None,  # 例如 "https://oapi.dingtalk.com/robot/send?access_token=xxx"
        "timeout": 5
    },
    "email": {
        "enabled": False,
        "smtp_host": None,
        "smtp_port": 587,
        "from_addr": None,
        "to_addrs": []
    }
}

# 监控配置
MONITOR_CONFIG = {
    "auto_eval_interval_hours": 24,  # 自动评估间隔
    "health_check_interval_minutes": 60,  # 健康检查间隔
    "keep_history_days": 30,  # 保留历史数据天数
    "trend_window_days": 7  # 趋势分析窗口
}

# 报告配置
REPORT_CONFIG = {
    "output_dir": "backend/eval/reports",
    "history_dir": "backend/eval/history",
    "formats": ["json", "markdown", "html"],
    "auto_open": False  # 生成后自动打开报告
}

# 检索评估 K 值配置
RETRIEVAL_K_VALUES = [1, 3, 5, 10, 20]


def get_threshold_status(metric_name: str, value: float) -> str:
    """
    根据阈值判断指标状态

    Args:
        metric_name: 指标名称
        value: 指标值

    Returns:
        good/acceptable/poor
    """
    if metric_name not in THRESHOLDS:
        return "unknown"

    thresholds = THRESHOLDS[metric_name]

    if value >= thresholds["good"]:
        return "good"
    elif value >= thresholds["acceptable"]:
        return "acceptable"
    else:
        return "poor"


def format_threshold(value: float, metric_name: str) -> str:
    """
    格式化阈值判断结果

    Args:
        value: 指标值
        metric_name: 指标名称

    Returns:
        格式化的状态描述
    """
    status = get_threshold_status(metric_name, value)

    if status == "good":
        emoji = "✅"
    elif status == "acceptable":
        emoji = "⚠️"
    else:
        emoji = "❌"

    return f"{emoji} {THRESHOLDS.get(metric_name, {}).get('description', metric_name)}: {value:.1%}" if "rate" in metric_name or "accuracy" in metric_name else f"{emoji} {THRESHOLDS.get(metric_name, {}).get('description', metric_name)}: {value:.0f}ms"
