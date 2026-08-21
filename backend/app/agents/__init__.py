# 智旅云图后端 Agents 模块（LangGraph 实现）

# RAG 工具（Phase 5 实现，保持不变）
from app.agents.rag_tool import (
    TOOL_NAME,
    GuideCity,
    GuideCategory,
    SearchGuidesArgs,
    RAGChunk,
    RAGQueryInfo,
    RAGToolStats,
    RAGToolResult,
    RAGTool,
    rag_tool,
)

# 行程规划 Agent（薄壳 + 业务纯函数）
from app.agents.trip_planner_agent import (
    DraftDay,
    DraftHotel,
    DraftItem,
    DraftItinerary,
    DraftMeal,
    PlannerError,
    PlannerParseError,
    PlannerValidationError,
    TripPlannerAgent,
    build_user_prompt,
    extract_json_object,
    trip_planner_agent,
)

# LangGraph 状态
from app.agents.state import EditDayState, PlannerState

# LangGraph 图
from app.agents.planner_graph import (
    build_edit_day_graph,
    build_planner_graph,
    get_edit_day_graph,
    get_planner_graph,
)

# LLM 工厂
from app.agents.llm_factory import build_json_llm, build_llm, get_default_llm

# LangChain 工具封装
from app.agents.tools import (
    build_rag_tool_node,
    build_rag_tools,
    get_default_rag_tool_node,
    get_default_rag_tools,
)

__all__ = [
    # RAG 工具
    "TOOL_NAME",
    "GuideCity",
    "GuideCategory",
    "SearchGuidesArgs",
    "RAGChunk",
    "RAGQueryInfo",
    "RAGToolStats",
    "RAGToolResult",
    "RAGTool",
    "rag_tool",
    # 行程规划 Agent
    "DraftDay",
    "DraftHotel",
    "DraftItem",
    "DraftItinerary",
    "DraftMeal",
    "PlannerError",
    "PlannerParseError",
    "PlannerValidationError",
    "TripPlannerAgent",
    "build_user_prompt",
    "extract_json_object",
    "trip_planner_agent",
    # LangGraph 状态
    "PlannerState",
    "EditDayState",
    # LangGraph 图
    "build_planner_graph",
    "build_edit_day_graph",
    "get_planner_graph",
    "get_edit_day_graph",
    # LLM 工厂
    "build_llm",
    "build_json_llm",
    "get_default_llm",
    # LangChain 工具封装
    "build_rag_tools",
    "build_rag_tool_node",
    "get_default_rag_tools",
    "get_default_rag_tool_node",
]
