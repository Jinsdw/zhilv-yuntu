"""
评估报告生成器
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import asdict

from .evaluator import EvaluationReport, EvaluationLevel


class ReportGenerator:
    """评估报告生成器"""

    def __init__(self, output_dir: str = "backend/eval/reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(
        self,
        report: EvaluationReport,
        format: str = "all"
    ) -> Dict[str, Any]:
        """
        生成评估报告

        Args:
            report: 评估报告
            format: 输出格式 (json/markdown/html/all)

        Returns:
            生成的报告内容字典
        """
        results = {}

        if format in ["json", "all"]:
            results["json"] = self._generate_json_report(report)

        if format in ["markdown", "all"]:
            results["markdown"] = self._generate_markdown_report(report)

        if format in ["html", "all"]:
            results["html"] = self._generate_html_report(report)

        return results

    def save_report(
        self,
        report: EvaluationReport,
        format: str = "all"
    ) -> Dict[str, str]:
        """保存报告到文件"""
        results = self.generate_report(report, format)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        level = report.level.value

        saved_paths = {}

        if "json" in results:
            json_path = self.output_dir / f"eval_report_{level}_{timestamp}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(results["json"], f, ensure_ascii=False, indent=2)
            saved_paths["json"] = str(json_path)

        if "markdown" in results:
            md_path = self.output_dir / f"eval_report_{level}_{timestamp}.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(results["markdown"])
            saved_paths["markdown"] = str(md_path)

        if "html" in results:
            html_path = self.output_dir / f"eval_report_{level}_{timestamp}.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(results["html"])
            saved_paths["html"] = str(html_path)

        return saved_paths

    def _generate_json_report(self, report: EvaluationReport) -> Dict[str, Any]:
        """生成 JSON 格式报告"""
        return {
            "summary": {
                "timestamp": report.timestamp,
                "level": report.level.value,
                "total_cases": report.total_cases,
                "passed_cases": report.passed_cases,
                "failed_cases": report.failed_cases_count,
                "pass_rate": f"{report.pass_rate:.1%}",
                "error_count": report.error_count,
            },
            "metrics": {
                "intent_accuracy": f"{report.intent_accuracy:.1%}",
                "city_extraction_accuracy": f"{report.city_extraction_accuracy:.1%}",
                "days_extraction_accuracy": f"{report.days_extraction_accuracy:.1%}",
                "mean_mrr": f"{report.mean_mrr:.1%}",
                "recall_at_k": {
                    f"@{k}": f"{v:.1%}"
                    for k, v in sorted(report.mean_recall_at_k.items())
                },
                "precision_at_k": {
                    f"@{k}": f"{v:.1%}"
                    for k, v in sorted(report.mean_precision_at_k.items())
                },
                "ndcg_at_k": {
                    f"@{k}": f"{v:.1%}"
                    for k, v in sorted(report.mean_ndcg_at_k.items())
                },
                "latency": {
                    "avg_ms": f"{report.avg_latency_ms:.0f}",
                    "p50_ms": f"{report.p50_latency_ms:.0f}",
                    "p95_ms": f"{report.p95_latency_ms:.0f}",
                    "p99_ms": f"{report.p99_latency_ms:.0f}",
                    "min_ms": f"{report.min_latency_ms:.0f}",
                    "max_ms": f"{report.max_latency_ms:.0f}",
                },
                "stages_breakdown": report.stages_breakdown,
            },
            "category_stats": report.by_category,
            "difficulty_stats": report.by_difficulty,
            "priority_stats": report.by_priority,
            "recommendations": report.recommendations,
            "failed_cases": [
                {
                    "case_id": r.case_id,
                    "query": r.query,
                    "detected_intent": r.detected_intent,
                    "detected_city": r.detected_city,
                    "intent_correct": r.intent_correct,
                    "city_correct": r.city_correct,
                    "latency_ms": r.latency_ms,
                    "error": r.error_message,
                }
                for r in report.failed_cases
            ],
        }

    def _generate_markdown_report(self, report: EvaluationReport) -> str:
        """生成 Markdown 格式报告"""
        pass_rate_val = report.pass_rate * 100
        pass_rate_emoji = "✅" if pass_rate_val >= 85 else "⚠️" if pass_rate_val >= 70 else "❌"

        lines = [
            "# 🧭 智旅云图 RAG 评估报告",
            "",
            f"**评估时间**: {report.timestamp}",
            f"**评估级别**: {report.level.value}",
            f"**用例总数**: {report.total_cases}",
            "",
            "---",
            "",
            "## 📊 总体概览",
            "",
            f"| 指标 | 数值 | 状态 |",
            f"|------|------|------|",
            f"| 通过率 | {pass_rate_val:.1f}% | {pass_rate_emoji} |",
            f"| 通过/失败 | {report.passed_cases}/{report.failed_cases_count} | - |",
            f"| 错误数 | {report.error_count} | - |",
            f"| 意图识别准确率 | {report.intent_accuracy:.1%} | - |",
            f"| 城市提取准确率 | {report.city_extraction_accuracy:.1%} | - |",
            f"| 天数提取准确率 | {report.days_extraction_accuracy:.1%} | - |",
            f"| MRR | {report.mean_mrr:.1%} | - |",
            "",
            "## ⚡ 性能指标",
            "",
            f"| 延迟 | 数值 |",
            f"|------|------|",
            f"| 平均延迟 | {report.avg_latency_ms:.0f} ms |",
            f"| P50 延迟 | {report.p50_latency_ms:.0f} ms |",
            f"| P95 延迟 | {report.p95_latency_ms:.0f} ms |",
            f"| P99 延迟 | {report.p99_latency_ms:.0f} ms |",
            f"| 最小延迟 | {report.min_latency_ms:.0f} ms |",
            f"| 最大延迟 | {report.max_latency_ms:.0f} ms |",
            "",
        ]

        # 阶段耗时
        if report.stages_breakdown:
            lines.extend([
                "### 阶段耗时分布",
                "",
                f"| 阶段 | 平均耗时 |",
                f"|------|----------|",
            ])
            for stage, timing in sorted(report.stages_breakdown.items()):
                stage_name = stage.replace("_ms", "").replace("_", " ")
                lines.append(f"| {stage_name} | {timing:.2f} ms |")
            lines.append("")

        # 召回指标
        lines.extend([
            "## 📈 召回指标",
            "",
            "| K值 | Recall@K | Precision@K | NDCG@K |",
            "|------|----------|-------------|--------|",
        ])
        for k in sorted(report.mean_recall_at_k.keys()):
            recall = report.mean_recall_at_k.get(k, 0)
            precision = report.mean_precision_at_k.get(k, 0)
            ndcg = report.mean_ndcg_at_k.get(k, 0)
            lines.append(f"| @{k} | {recall:.1%} | {precision:.1%} | {ndcg:.1%} |")
        lines.append("")

        # 分类统计
        if report.by_category:
            lines.extend([
                "## 📋 分类统计",
                "",
                "| 分类 | 通过/总数 | 通过率 |",
                "|------|-----------|--------|",
            ])
            for cat, stats in report.by_category.items():
                rate = stats["passed"] / stats["total"] if stats["total"] > 0 else 0
                lines.append(f"| {cat} | {stats['passed']}/{stats['total']} | {rate:.1%} |")
            lines.append("")

        # 难度统计
        if report.by_difficulty:
            lines.extend([
                "## 🎯 难度分析",
                "",
                "| 难度 | 通过/总数 | 通过率 |",
                "|------|-----------|--------|",
            ])
            for diff, stats in report.by_difficulty.items():
                rate = stats["passed"] / stats["total"] if stats["total"] > 0 else 0
                emoji = "🟢" if diff == "easy" else "🟡" if diff == "medium" else "🔴"
                lines.append(f"| {emoji} {diff} | {stats['passed']}/{stats['total']} | {rate:.1%} |")
            lines.append("")

        # 优先级统计
        if report.by_priority:
            lines.extend([
                "## ⭐ 优先级统计",
                "",
                "| 优先级 | 通过/总数 | 通过率 |",
                "|--------|-----------|--------|",
            ])
            for pri, stats in report.by_priority.items():
                rate = stats["passed"] / stats["total"] if stats["total"] > 0 else 0
                emoji = "🔴" if pri == "P0" else "🟠" if pri == "P1" else "🟡"
                lines.append(f"| {emoji} {pri} | {stats['passed']}/{stats['total']} | {rate:.1%} |")
            lines.append("")

        # 改进建议
        if report.recommendations:
            lines.extend([
                "## 💡 改进建议",
                "",
            ])
            for i, rec in enumerate(report.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        # 失败用例
        if report.failed_cases:
            lines.extend([
                "## ❌ 失败用例详情",
                "",
                "| 用例ID | 查询 | 检测意图 | 检测城市 | 延迟 | 错误 |",
                "|--------|------|----------|----------|------|------|",
            ])
            for r in report.failed_cases[:20]:  # 只显示前20个
                query_short = r.query[:25] + "..." if len(r.query) > 25 else r.query
                error_short = (r.error_message or "")[:30]
                lines.append(
                    f"| {r.case_id} | {query_short} | {r.detected_intent or '-'} | "
                    f"{r.detected_city or '-'} | {r.latency_ms:.0f}ms | {error_short} |"
                )

        lines.extend([
            "",
            "---",
            f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])

        return "\n".join(lines)

    def _generate_html_report(self, report: EvaluationReport) -> str:
        """生成 HTML 格式报告"""
        pass_rate_val = report.pass_rate * 100
        pass_rate_color = "#28a745" if pass_rate_val >= 85 else "#ffc107" if pass_rate_val >= 70 else "#dc3545"

        html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAG 评估报告 - {report.timestamp}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 24px;
            box-shadow: 0 4px 20px rgba(102, 126, 234, 0.3);
        }}
        .header h1 {{ font-size: 2em; margin-bottom: 8px; }}
        .header p {{ opacity: 0.9; font-size: 0.95em; }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
        }}
        .card h2 {{ color: #2c3e50; margin-bottom: 16px; border-bottom: 2px solid #eee; padding-bottom: 8px; }}
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 16px;
        }}
        .metric {{
            text-align: center;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }}
        .metric-value {{
            font-size: 2em;
            font-weight: bold;
            color: #2c3e50;
        }}
        .metric-label {{ color: #666; font-size: 0.85em; margin-top: 4px; }}
        .pass-rate {{ color: {pass_rate_color}; }}
        .metric-good {{ color: #28a745; }}
        .metric-warning {{ color: #ffc107; }}
        .metric-bad {{ color: #dc3545; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; color: #2c3e50; }}
        tr:hover {{ background: #f8f9fa; }}
        .status-pass {{ color: #28a745; font-weight: 500; }}
        .status-fail {{ color: #dc3545; font-weight: 500; }}
        .recommendation {{
            background: #fff3cd;
            padding: 16px;
            border-radius: 8px;
            margin: 8px 0;
            border-left: 4px solid #ffc107;
        }}
        .recommendation.warning {{ background: #fff; border-left-color: #dc3545; }}
        .tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            margin-left: 8px;
        }}
        .tag-easy {{ background: #d4edda; color: #155724; }}
        .tag-medium {{ background: #fff3cd; color: #856404; }}
        .tag-hard {{ background: #f8d7da; color: #721c24; }}
        .footer {{
            text-align: center;
            color: #999;
            padding: 20px;
            font-size: 0.85em;
        }}
        .stage-bar {{
            background: #e9ecef;
            border-radius: 4px;
            height: 24px;
            margin: 4px 0;
            position: relative;
        }}
        .stage-fill {{
            background: linear-gradient(90deg, #667eea, #764ba2);
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s;
        }}
        .stage-label {{
            position: absolute;
            left: 8px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 0.8em;
            color: #333;
        }}
        .category-card {{
            display: inline-block;
            padding: 16px;
            margin: 8px;
            background: #f8f9fa;
            border-radius: 8px;
            min-width: 150px;
            text-align: center;
        }}
        .category-name {{ font-weight: 600; margin-bottom: 8px; }}
        .category-rate {{ font-size: 1.5em; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧭 智旅云图 RAG 评估报告</h1>
            <p>评估时间: {report.timestamp} | 级别: <strong>{report.level.value}</strong></p>
        </div>

        <div class="card">
            <h2>📊 总体概览</h2>
            <div class="metric-grid">
                <div class="metric">
                    <div class="metric-value pass-rate">{pass_rate_val:.1f}%</div>
                    <div class="metric-label">通过率</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{report.passed_cases}/{report.total_cases}</div>
                    <div class="metric-label">通过/总数</div>
                </div>
                <div class="metric">
                    <div class="metric-value {'metric-good' if report.intent_accuracy >= 0.85 else 'metric-warning' if report.intent_accuracy >= 0.7 else 'metric-bad'}">{report.intent_accuracy:.1%}</div>
                    <div class="metric-label">意图识别准确率</div>
                </div>
                <div class="metric">
                    <div class="metric-value {'metric-good' if report.city_extraction_accuracy >= 0.9 else 'metric-warning' if report.city_extraction_accuracy >= 0.8 else 'metric-bad'}">{report.city_extraction_accuracy:.1%}</div>
                    <div class="metric-label">城市提取准确率</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{report.mean_mrr:.1%}</div>
                    <div class="metric-label">MRR</div>
                </div>
                <div class="metric">
                    <div class="metric-value {'metric-good' if report.error_count == 0 else 'metric-bad'}">{report.error_count}</div>
                    <div class="metric-label">错误数</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>⚡ 性能指标</h2>
            <table>
                <tr><th>指标</th><th>数值</th></tr>
                <tr><td>平均延迟</td><td>{report.avg_latency_ms:.0f} ms</td></tr>
                <tr><td>P50 延迟</td><td>{report.p50_latency_ms:.0f} ms</td></tr>
                <tr><td>P95 延迟</td><td>{report.p95_latency_ms:.0f} ms</td></tr>
                <tr><td>P99 延迟</td><td>{report.p99_latency_ms:.0f} ms</td></tr>
                <tr><td>最小延迟</td><td>{report.min_latency_ms:.0f} ms</td></tr>
                <tr><td>最大延迟</td><td>{report.max_latency_ms:.0f} ms</td></tr>
            </table>
"""

        # 阶段耗时
        if report.stages_breakdown:
            max_stage_time = max(report.stages_breakdown.values()) if report.stages_breakdown else 1
            html += "<h3 style='margin-top: 16px;'>阶段耗时分布</h3>"
            for stage, timing in sorted(report.stages_breakdown.items(), key=lambda x: -x[1]):
                stage_name = stage.replace("_ms", "").replace("_", " ")
                width = (timing / max_stage_time) * 100
                html += f"""
                <div style="margin: 8px 0;">
                    <div style="display: flex; justify-content: space-between;">
                        <span>{stage_name}</span>
                        <span>{timing:.2f} ms</span>
                    </div>
                    <div class="stage-bar">
                        <div class="stage-fill" style="width: {width}%"></div>
                    </div>
                </div>
                """

        # 召回指标
        html += """
        <div class="card">
            <h2>📈 召回指标</h2>
            <table>
                <tr><th>K</th><th>Recall@K</th><th>Precision@K</th><th>NDCG@K</th></tr>
        """
        for k in sorted(report.mean_recall_at_k.keys()):
            recall = report.mean_recall_at_k.get(k, 0)
            precision = report.mean_precision_at_k.get(k, 0)
            ndcg = report.mean_ndcg_at_k.get(k, 0)
            html += f"<tr><td>@{k}</td><td>{recall:.1%}</td><td>{precision:.1%}</td><td>{ndcg:.1%}</td></tr>"
        html += "</table></div>"

        # 分类统计
        if report.by_category:
            html += """
            <div class="card">
                <h2>📋 分类统计</h2>
            """
            for cat, stats in report.by_category.items():
                rate = stats["passed"] / stats["total"] if stats["total"] > 0 else 0
                rate_color = "#28a745" if rate >= 0.85 else "#ffc107" if rate >= 0.7 else "#dc3545"
                html += f"""
                <div class="category-card">
                    <div class="category-name">{cat}</div>
                    <div class="category-rate" style="color: {rate_color};">{rate:.1%}</div>
                    <div style="color: #666; font-size: 0.85em;">{stats['passed']}/{stats['total']}</div>
                </div>
                """
            html += "</div>"

        # 改进建议
        if report.recommendations:
            html += """
            <div class="card">
                <h2>💡 改进建议</h2>
            """
            for rec in report.recommendations:
                is_critical = "P0" in rec or "必须" in rec
                html += f'<div class="recommendation{" warning" if is_critical else ""}">{rec}</div>'
            html += "</div>"

        # 失败用例
        if report.failed_cases:
            html += """
            <div class="card">
                <h2>❌ 失败用例</h2>
                <table>
                    <tr><th>用例ID</th><th>查询</th><th>检测意图</th><th>检测城市</th><th>延迟</th></tr>
            """
            for r in report.failed_cases[:15]:
                query_short = r.query[:30] + "..." if len(r.query) > 30 else r.query
                html += f"""
                    <tr>
                        <td><code>{r.case_id}</code></td>
                        <td>{query_short}</td>
                        <td>{r.detected_intent or '-'}</td>
                        <td>{r.detected_city or '-'}</td>
                        <td>{r.latency_ms:.0f}ms</td>
                    </tr>
                """
            html += "</table></div>"

        html += f"""
        <div class="footer">
            <p>报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>智旅云图 RAG 评估系统</p>
        </div>
    </div>
</body>
</html>
        """

        return html
