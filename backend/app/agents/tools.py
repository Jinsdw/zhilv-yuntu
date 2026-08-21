"""
智旅云图 - LangChain 工具封装

把 Phase 5 已实现的 RAGTool（rag_tool.py，保持不动）包装为 LangChain @tool，
供 LangGraph 的 ToolNode 直接消费。

设计要点：
- 不修改 rag_tool.py，保留其 Pydantic 契约与内部多路/降级逻辑
- 仅在外层做一层 LangChain Tool 适配，签名严格对齐 SearchGuidesArgs
- 工具返回字符串（RAGToolResult.model_dump_json），保持与原 function calling 一致
- 单元测试可继续直接测试 RAGTool，也可测试 @tool 包装层
"""

from __future__ import annotations

import json
from typing import Any, Optional

from langchain_core.tools import StructuredTool, tool
from langgraph.prebuilt import ToolNode
from loguru import logger

from app.agents.rag_tool import (
    GuideCategory,
    GuideCity,
    RAGTool,
    SearchGuidesArgs,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    rag_tool as _default_rag_tool,
)


def _build_search_guides_tool(rag_tool: RAGTool) -> StructuredTool:
    """
    把 RAGTool.execute 包装为 LangChain StructuredTool。

    使用 StructuredTool 而非 @tool 装饰器，是为了：
    1. 在函数体内直接拿到 SearchGuidesArgs 对象（强类型）
    2. args_schema 自动复用 rag_tool.py 的 Pydantic 契约，与原 as_openai_tools 输出一致
    """

    def _run(
        query: str,
        city: Optional[GuideCity] = None,
        category: Optional[GuideCategory] = None,
        top_k: int = 5,
        use_cache: bool = True,
        use_rerank: bool = True,
    ) -> str:
        args = SearchGuidesArgs(
            query=query,
            city=city,
            category=category,
            top_k=top_k,
            use_cache=use_cache,
            use_rerank=use_rerank,
        )
        # execute 内部会规范化 city/category 并做参数校验失败兜底
        return rag_tool.execute(TOOL_NAME, args.model_dump(mode="json", exclude_none=True))

    async def _arun(
        query: str,
        city: Optional[GuideCity] = None,
        category: Optional[GuideCategory] = None,
        top_k: int = 5,
        use_cache: bool = True,
        use_rerank: bool = True,
    ) -> str:
        # RAGTool 当前为同步实现；异步路径直接走同步，避免阻塞事件循环
        # 若后续引入异步 Retriever，可在此处 await
        return _run(query, city, category, top_k, use_cache, use_rerank)

    return StructuredTool.from_function(
        func=_run,
        coroutine=_arun,
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        args_schema=SearchGuidesArgs,
    )


def build_rag_tools(rag_tool: Optional[RAGTool] = None) -> list[StructuredTool]:
    """
    构造 RAG 工具列表（目前只有一个 search_travel_guides）。

    Args:
        rag_tool: 可选的 RAGTool 实例；默认使用模块单例 rag_tool.rag_tool
    """
    tool_instance = rag_tool or _default_rag_tool
    return [_build_search_guides_tool(tool_instance)]


def build_rag_tool_node(rag_tool: Optional[RAGTool] = None) -> ToolNode:
    """
    构造 LangGraph 预置 ToolNode，用于在 planner graph 中执行 RAG 工具。

    节点会读取 state["messages"] 末尾的 tool_calls，分发到对应工具，
    并把结果以 ToolMessage 形式 append 回 messages。
    """
    tools = build_rag_tools(rag_tool)
    return ToolNode(tools)


# 模块级默认实例（懒加载，避免 import 时即触发 zai / ChromaDB 初始化）
_default_tools: Optional[list[StructuredTool]] = None
_default_tool_node: Optional[ToolNode] = None


def get_default_rag_tools() -> list[StructuredTool]:
    """获取默认 RAG 工具列表单例。"""
    global _default_tools
    if _default_tools is None:
        _default_tools = build_rag_tools()
    return _default_tools


def get_default_rag_tool_node() -> ToolNode:
    """获取默认 RAG ToolNode 单例。"""
    global _default_tool_node
    if _default_tool_node is None:
        _default_tool_node = build_rag_tool_node()
    return _default_tool_node
