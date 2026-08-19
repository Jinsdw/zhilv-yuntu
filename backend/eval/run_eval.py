"""
RAG 评估入口脚本

使用方法（在 backend 目录下运行）:
    # 标准评估
    python eval/run_eval.py

    # 快速评估（仅核心用例）
    python eval/run_eval.py --level quick

    # 完整评估
    python eval/run_eval.py --level full

    # 持续监控模式
    python eval/run_eval.py --monitor

    # 仅生成报告
    python eval/run_eval.py --report

    # 列出所有用例
    python eval/run_eval.py --list

    # 测试单个用例
    python eval/run_eval.py --test "北京三天怎么玩"
"""

import argparse
import sys
import io
from pathlib import Path

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 获取 backend 目录（项目根目录下的 backend 文件夹）
run_eval_path = Path(__file__).resolve()  # backend/eval/run_eval.py
backend_dir = run_eval_path.parent.parent  # backend/
project_root = backend_dir.parent  # zhilv-yuntu-jins/

# 添加 backend 目录到 sys.path（这样可以 from eval.xxx 导入）
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from loguru import logger

from eval.evaluator import RAGEvaluator, EvaluationCase, EvaluationLevel
from eval.cases.base_cases import BASE_CASES
from eval.cases.intent_cases import INTENT_CASES
from eval.cases.retrieval_cases import RETRIEVAL_CASES
from eval.cases.regression_cases import REGRESSION_CASES
from eval.reporter import ReportGenerator
from eval.monitor import RAGMonitor, MonitorConfig


def load_cases(level: EvaluationLevel) -> list[EvaluationCase]:
    """根据级别加载评估用例"""
    cases = []

    if level == EvaluationLevel.QUICK:
        # 快速评估：每个分类取2个用例
        for case in BASE_CASES[:8]:
            cases.append(EvaluationCase(
                case_id=case.case_id,
                query=case.query,
                expected_intent=case.expected_intent,
                expected_city=case.expected_city,
                expected_days=case.expected_days,
                category=case.category,
                difficulty=case.difficulty,
            ))

    elif level == EvaluationLevel.STANDARD:
        # 标准评估：所有基础用例 + 意图用例
        for case in BASE_CASES:
            cases.append(EvaluationCase(
                case_id=case.case_id,
                query=case.query,
                expected_intent=case.expected_intent,
                expected_city=case.expected_city,
                expected_days=case.expected_days,
                category=case.category,
                difficulty=case.difficulty,
            ))

        # 添加意图用例
        for intent, items in INTENT_CASES.items():
            for item in items[:5]:  # 每类取5个
                cases.append(EvaluationCase(
                    case_id=item["case_id"],
                    query=item["query"],
                    expected_intent=intent,
                    category="意图识别",
                ))

    else:  # FULL
        # 完整评估：所有用例
        for case in BASE_CASES:
            cases.append(EvaluationCase(
                case_id=case.case_id,
                query=case.query,
                expected_intent=case.expected_intent,
                expected_city=case.expected_city,
                expected_days=case.expected_days,
                expected_keywords=case.expected_keywords,
                category=case.category,
                difficulty=case.difficulty,
            ))

        # 添加意图用例
        for intent, items in INTENT_CASES.items():
            for item in items:
                cases.append(EvaluationCase(
                    case_id=item["case_id"],
                    query=item["query"],
                    expected_intent=intent,
                    category="意图识别",
                ))

        # 添加检索用例
        for item in RETRIEVAL_CASES:
            cases.append(EvaluationCase(
                case_id=item["case_id"],
                query=item["query"],
                expected_keywords=item.get("expected_keywords", []),
                expected_city=item.get("city"),
                category=item.get("category", "general"),
                difficulty=item.get("difficulty", "medium"),
            ))

        # 添加回归用例
        for item in REGRESSION_CASES:
            cases.append(EvaluationCase(
                case_id=item["case_id"],
                query=item["query"],
                expected_intent=item.get("required_intent"),
                expected_city=item.get("required_city"),
                category="回归测试",
                priority=item.get("priority", "P1"),
            ))

    return cases


def run_evaluation(level: EvaluationLevel = EvaluationLevel.STANDARD) -> dict:
    """运行评估"""
    logger.info(f"开始 {level.value} 级别 RAG 评估")
    print(f"\n{'=' * 60}")
    print(f"  智旅云图 RAG 评估系统")
    print(f"{'=' * 60}")
    print(f"  评估级别: {level.value}")
    print(f"{'=' * 60}\n")

    # 加载用例
    cases = load_cases(level)
    print(f"📋 加载了 {len(cases)} 个评估用例\n")

    # 创建评估器
    evaluator = RAGEvaluator()

    # 执行评估
    print("🚀 开始评估...\n")
    report = evaluator.evaluate_all(cases, level)

    # 生成报告
    generator = ReportGenerator()
    saved_paths = generator.save_report(report, format="all")

    # 输出摘要
    print(f"\n{'=' * 60}")
    print("  评估完成")
    print(f"{'=' * 60}")

    # 状态判断
    pass_rate = report.pass_rate * 100
    if pass_rate >= 85:
        status = "✅ 通过"
    elif pass_rate >= 70:
        status = "⚠️ 警告"
    else:
        status = "❌ 失败"

    print(f"\n📊 总体结果:")
    print(f"   通过率: {pass_rate:.1f}% {status}")
    print(f"   通过/失败: {report.passed_cases}/{report.failed_cases_count}")
    print(f"   错误数: {report.error_count}")

    print(f"\n🎯 意图识别:")
    print(f"   准确率: {report.intent_accuracy:.1%}")

    print(f"\n🏙️ 城市提取:")
    print(f"   准确率: {report.city_extraction_accuracy:.1%}")

    print(f"\n📈 检索质量:")
    print(f"   MRR: {report.mean_mrr:.1%}")
    print(f"   Recall@5: {report.mean_recall_at_k.get(5, 0):.1%}")

    print(f"\n⚡ 性能:")
    print(f"   平均延迟: {report.avg_latency_ms:.0f}ms")
    print(f"   P95 延迟: {report.p95_latency_ms:.0f}ms")

    # 分类统计
    if report.by_category:
        print(f"\n📋 分类统计:")
        for cat, stats in report.by_category.items():
            rate = stats["passed"] / stats["total"] if stats["total"] > 0 else 0
            bar = "█" * int(rate * 20) + "░" * (20 - int(rate * 20))
            print(f"   {cat}: {rate:.0%} |{bar}| {stats['passed']}/{stats['total']}")

    print(f"\n📁 报告已保存:")
    for fmt, path in saved_paths.items():
        print(f"   - {fmt}: {path}")

    # 改进建议
    if report.recommendations:
        print(f"\n💡 改进建议:")
        for i, rec in enumerate(report.recommendations[:5], 1):
            print(f"   {i}. {rec}")

    print(f"\n{'=' * 60}\n")

    return generator._generate_json_report(report)


def list_cases(level: EvaluationLevel = EvaluationLevel.STANDARD):
    """列出所有用例"""
    cases = load_cases(level)

    print(f"\n{'=' * 60}")
    print(f"  评估用例列表 ({len(cases)} 个)")
    print(f"{'=' * 60}\n")

    # 按分类分组
    by_category = {}
    for case in cases:
        cat = case.category
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(case)

    for cat, cat_cases in by_category.items():
        print(f"\n📁 {cat} ({len(cat_cases)} 个)")
        print("-" * 50)
        for case in cat_cases:
            intent_icon = {
                "itinerary": "🗓️",
                "scenic_spot": "🏞️",
                "dining": "🍜",
                "accommodation": "🏨",
            }.get(case.expected_intent or "", "📝")

            city = case.expected_city or "-"
            print(f"   {intent_icon} [{case.case_id}] {case.query[:40]}{'...' if len(case.query) > 40 else ''}")
            print(f"       城市: {city} | 难度: {case.difficulty}")


def test_single_query(query: str):
    """测试单个查询"""
    print(f"\n{'=' * 60}")
    print(f"  单用例测试")
    print(f"{'=' * 60}\n")
    print(f"查询: {query}\n")

    evaluator = RAGEvaluator()
    case = EvaluationCase(
        case_id="test_001",
        query=query,
    )

    result = evaluator.evaluate_case(case)

    print(f"✅ 检索成功，返回 {len(result.retrieved_docs)} 条结果\n")

    print(f"📋 意图识别:")
    print(f"   检测意图: {result.detected_intent}")
    print(f"   检测城市: {result.detected_city}")
    print(f"   检测天数: {result.detected_days}")

    print(f"\n📈 质量指标:")
    print(f"   MRR: {result.mrr:.1%}")
    print(f"   平均相关性: {result.avg_relevance:.2f}")

    print(f"\n⚡ 性能:")
    print(f"   延迟: {result.latency_ms:.0f}ms")

    if result.stages_timing:
        print(f"\n⏱️ 阶段耗时:")
        for stage, timing in sorted(result.stages_timing.items()):
            print(f"   - {stage}: {timing:.2f}ms")

    print(f"\n📄 返回文档:")
    for i, doc in enumerate(result.retrieved_docs[:3], 1):
        doc_preview = doc.get("document", "")[:100]
        print(f"   [{i}] {doc_preview}...")

    print(f"\n{'=' * 60}\n")


def run_monitor():
    """运行持续监控模式"""
    logger.info("启动 RAG 持续监控...")

    print(f"\n{'=' * 60}")
    print(f"  智旅云图 RAG 监控模式")
    print(f"{'=' * 60}\n")

    config = MonitorConfig(
        auto_eval_interval_hours=24,
        regression_threshold=0.05,
        latency_threshold_ms=3000,
        pass_rate_threshold=0.85,
        history_dir="backend/eval/history",
        keep_history_days=30
    )

    monitor = RAGMonitor(config)

    def eval_callback():
        return run_evaluation(EvaluationLevel.QUICK)

    # 运行首次检查
    print("🔍 执行健康检查...\n")
    health = monitor.run_scheduled_check(eval_callback)

    print(f"\n📊 健康状态: ", end="")
    if health.status == "healthy":
        print("✅ 健康")
    elif health.status == "degraded":
        print("⚠️ 降级")
    else:
        print("❌ 异常")

    if health.alerts:
        print(f"\n🚨 告警:")
        for alert in health.alerts:
            print(f"   - {alert}")

    if health.recommendations:
        print(f"\n💡 建议:")
        for rec in health.recommendations:
            print(f"   - {rec}")

    # 显示趋势
    if "trends" in health.metrics:
        trends = health.metrics["trends"]
        if "pass_rate_change" in trends:
            change = trends["pass_rate_change"]
            emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            print(f"\n{emoji} 趋势 (最近7天):")
            print(f"   通过率变化: {change:+.1%}")

    print(f"\n{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="智旅云图 RAG 评估工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_eval.py                          # 标准评估
  python run_eval.py --level quick            # 快速评估
  python run_eval.py --level full              # 完整评估
  python run_eval.py --list                   # 列出所有用例
  python run_eval.py --test "北京三天怎么玩"  # 测试单个查询
  python run_eval.py --monitor                # 持续监控模式
        """
    )

    parser.add_argument(
        "--level",
        choices=["quick", "standard", "full"],
        default="standard",
        help="评估级别 (默认: standard)"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有用例"
    )

    parser.add_argument(
        "--test",
        type=str,
        help="测试单个查询"
    )

    parser.add_argument(
        "--monitor",
        action="store_true",
        help="持续监控模式"
    )

    parser.add_argument(
        "--report",
        action="store_true",
        help="生成历史报告"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="显示详细日志"
    )

    args = parser.parse_args()

    # 配置日志
    logger.remove()
    if args.verbose:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="INFO")

    if args.list:
        level = EvaluationLevel(args.level)
        list_cases(level)
    elif args.test:
        test_single_query(args.test)
    elif args.monitor:
        run_monitor()
    elif args.report:
        print("报告生成功能需要指定历史数据文件")
    else:
        level = EvaluationLevel(args.level)
        run_evaluation(level)


if __name__ == "__main__":
    main()
