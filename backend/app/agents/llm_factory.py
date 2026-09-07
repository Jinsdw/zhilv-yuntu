"""
智旅云图 - LLM 客户端工厂

通过 langchain-openai 的 ChatOpenAI 对接 OpenAI 兼容端点，
让 LangGraph / ToolNode 等机制原生可用，移除对 zai 库的硬依赖。

平台由 .env 的 LLM_PROVIDER 切换（config.get_active_llm_config）：
- zhipu（智谱）：https://open.bigmodel.cn/api/paas/v4
- packycode：https://www.packyapi.com/v1
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_openai import ChatOpenAI

from app.config import get_active_llm_config, settings


def build_llm(
    *,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    streaming: bool = False,
    timeout: float = 60.0,
) -> ChatOpenAI:
    """
    构造一个 LangChain ChatModel 实例，指向当前 LLM_PROVIDER 配置的 OpenAI 兼容端点。

    Args:
        model: 模型名，默认取当前 LLM_PROVIDER 对应配置的模型
        temperature: 采样温度，规划类建议 0.2-0.4
        max_tokens: 单次输出最大 tokens
        streaming: 是否流式（LangGraph 节点一般用非流式，stream 模式由入口控制）
        timeout: 单次请求超时（秒）

    Returns:
        ChatOpenAI 实例，可用于 LangGraph 的 ToolNode / create_react_agent
    """
    cfg = get_active_llm_config()
    return ChatOpenAI(
        model=model or cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
        timeout=timeout,
    )


def build_json_llm(**kwargs: Any) -> ChatOpenAI:
    """
    构造强制 JSON 输出的 ChatModel。

    用于 parse_draft 失败后的 repair_json 节点，
    以及需要稳定 JSON 的最终回复轮。
    """
    llm = build_llm(**kwargs)
    # langchain-openai 通过 model_kwargs 透传 response_format
    return llm.bind(response_format={"type": "json_object"})


# 默认单例（懒加载，首次访问时构造）
_default_llm: Optional[ChatOpenAI] = None


def get_default_llm() -> ChatOpenAI:
    """获取默认 LLM 单例。"""
    global _default_llm
    if _default_llm is None:
        _default_llm = build_llm()
    return _default_llm
