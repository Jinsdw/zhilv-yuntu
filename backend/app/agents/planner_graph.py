"""
山海拾光（智旅云图） - LangGraph 主图

主图（planner_graph）：
    START → prefetch_rag → llm_plan ⇄ rag_tool_node
                                ↓
                            parse_draft → (repair_json) → validate_repair
                                                            ↓
                                          amap_backfill → build_trip → enrich_budget → END
                            ↓（任意步骤失败且允许 fallback）
                        fallback → END
"""

from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    amap_backfill_node,
    build_trip_node,
    enrich_budget_node,
    fallback_node,
    llm_plan_node,
    parse_draft_node,
    prefetch_rag_node,
    repair_json_node,
    route_after_build,
    route_after_llm,
    route_after_parse,
    route_after_validate,
    validate_repair_node,
)
from app.agents.rag_tool import RAGTool
from app.agents.state import PlannerState
from app.agents.tools import build_rag_tool_node

# 已编译图单例（懒加载）
_compiled_planner_graph = None


def build_planner_graph(rag_tool: Optional[RAGTool] = None):
    """
    构造并编译主规划 StateGraph。

    Args:
        rag_tool: 可选的 RAGTool 实例，用于构造 ToolNode；默认使用模块单例

    Returns:
        已编译的 CompiledStateGraph，可 .invoke(state) / .astream(state)
    """
    g = StateGraph(PlannerState)

    # 节点
    g.add_node("prefetch_rag", prefetch_rag_node)
    g.add_node("llm_plan", llm_plan_node)
    g.add_node("rag_tools", build_rag_tool_node(rag_tool))
    g.add_node("parse_draft", parse_draft_node)
    g.add_node("repair_json", repair_json_node)
    g.add_node("validate_repair", validate_repair_node)
    g.add_node("amap_backfill", amap_backfill_node)
    g.add_node("build_trip", build_trip_node)
    g.add_node("enrich_budget", enrich_budget_node)
    g.add_node("fallback", fallback_node)

    # 入口
    g.add_edge(START, "prefetch_rag")
    g.add_edge("prefetch_rag", "llm_plan")

    # LLM 后路由：有 tool_calls → rag_tools → 回 llm_plan；无则 parse
    g.add_conditional_edges(
        "llm_plan",
        route_after_llm,
        {
            "tools": "rag_tools",
            "parse": "parse_draft",
            "fallback": "fallback",
        },
    )
    g.add_edge("rag_tools", "llm_plan")

    # 解析后路由
    g.add_conditional_edges(
        "parse_draft",
        route_after_parse,
        {
            "validate": "validate_repair",
            "repair": "repair_json",
            "fallback": "fallback",
        },
    )
    # 修复后强制回到 parse_draft 再解析一次
    g.add_edge("repair_json", "parse_draft")

    # 校验后路由：无 error → 高德补数据 → build_trip
    g.add_conditional_edges(
        "validate_repair",
        route_after_validate,
        {
            "backfill": "amap_backfill",
            "fallback": "fallback",
        },
    )
    g.add_edge("amap_backfill", "build_trip")

    # build_trip 后路由
    g.add_conditional_edges(
        "build_trip",
        route_after_build,
        {
            "enrich": "enrich_budget",
            "fallback": "fallback",
        },
    )
    g.add_edge("enrich_budget", END)
    g.add_edge("fallback", END)

    return g.compile()
def get_planner_graph():
    """获取已编译主图单例（懒加载）。"""
    global _compiled_planner_graph
    if _compiled_planner_graph is None:
        _compiled_planner_graph = build_planner_graph()
    return _compiled_planner_graph
