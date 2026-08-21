"""
智旅云图 - LangGraph 主图与单日编辑子图

主图（planner_graph）：
    START → prefetch_rag → llm_plan ⇄ rag_tool_node
                                ↓
                            parse_draft → (repair_json) → validate_repair
                                                            ↓
                                                       build_trip → enrich_budget → END
                            ↓（任意步骤失败且允许 fallback）
                        fallback → END

单日编辑子图（edit_day_graph）：
    START → build_edit_day_input → llm_plan ⇄ rag_tool_node
                                       ↓
                                  parse_draft → (repair) → merge_edit_day → END
"""

from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    build_edit_day_input_node,
    build_trip_node,
    enrich_budget_node,
    fallback_node,
    llm_plan_node,
    merge_edit_day_node,
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
from app.agents.state import EditDayState, PlannerState
from app.agents.tools import build_rag_tool_node

# 已编译图单例（懒加载）
_compiled_planner_graph = None
_compiled_edit_day_graph = None


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

    # 校验后路由
    g.add_conditional_edges(
        "validate_repair",
        route_after_validate,
        {
            "build_trip": "build_trip",
            "fallback": "fallback",
        },
    )

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


def build_edit_day_graph(rag_tool: Optional[RAGTool] = None):
    """
    构造并编译单日编辑 StateGraph。

    与主图共享 llm_plan_node / parse_draft_node / rag_tools，
    但起始/结束节点不同：以 build_edit_day_input 起始，以 merge_edit_day 结束。
    """
    g = StateGraph(EditDayState)

    g.add_node("build_input", build_edit_day_input_node)
    g.add_node("llm_plan", llm_plan_node)
    g.add_node("rag_tools", build_rag_tool_node(rag_tool))
    g.add_node("parse_draft", parse_draft_node)
    g.add_node("repair_json", repair_json_node)
    g.add_node("merge_edit_day", merge_edit_day_node)

    g.add_edge(START, "build_input")
    g.add_edge("build_input", "llm_plan")

    g.add_conditional_edges(
        "llm_plan",
        route_after_llm,
        {
            "tools": "rag_tools",
            "parse": "parse_draft",
            "fallback": "merge_edit_day",
        },
    )
    g.add_edge("rag_tools", "llm_plan")

    g.add_conditional_edges(
        "parse_draft",
        route_after_parse,
        {
            "validate": "merge_edit_day",
            "repair": "repair_json",
            "fallback": "merge_edit_day",
        },
    )
    g.add_edge("repair_json", "parse_draft")

    g.add_edge("merge_edit_day", END)

    return g.compile()


def get_planner_graph():
    """获取已编译主图单例（懒加载）。"""
    global _compiled_planner_graph
    if _compiled_planner_graph is None:
        _compiled_planner_graph = build_planner_graph()
    return _compiled_planner_graph


def get_edit_day_graph():
    """获取已编译单日编辑子图单例（懒加载）。"""
    global _compiled_edit_day_graph
    if _compiled_edit_day_graph is None:
        _compiled_edit_day_graph = build_edit_day_graph()
    return _compiled_edit_day_graph
