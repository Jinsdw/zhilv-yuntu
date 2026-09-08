"""
山海拾光（智旅云图） - LLM 客户端工厂

通过 langchain-openai 的 ChatOpenAI 对接 OpenAI 兼容端点，
让 LangGraph / ToolNode 等机制原生可用，移除对 zai 库的硬依赖。

平台由 .env 的 LLM_PROVIDER 切换（config.get_active_llm_config）：
- zhipu / zhipu4（智谱）：https://open.bigmodel.cn/api/paas/v4
- packycode：https://www.packyapi.com/v1
- deepseek（DeepSeek 官方 API）：https://api.deepseek.com/v1

日志约定（便于 grep 排查）：
- ``LLM 请求入参 [note]``：平台/模型/端点/温度/最大 tokens/流式/思考参数
- ``LLM 请求消息 [note]``：本次调用完整消息体（system/user/assistant/tool）
- ``LLM 思考过程 [note]``：模型 reasoning_content（思考过程全文）
- ``调用大模型``：兼容旧日志格式的平台/模型/端点一行
"""

from __future__ import annotations

import json
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from loguru import logger

from app.config import get_active_llm_config, settings


class ReasoningLoggingChatOpenAI(ChatOpenAI):
    """
    ChatOpenAI 子类：捕获智谱等兼容端点返回的 reasoning_content（思考过程）。

    langchain-openai 默认丢弃 OpenAI 规范之外的字段（如智谱的 reasoning_content）。
    本子类在流式与非流式两条路径上把它写入
    message.additional_kwargs["reasoning_content"]，供调用方写入日志；
    流式分片在调用方累加时（chunk += chunk）会按字符串自动拼接为完整思考过程。
    """

    def _convert_chunk_to_generation_chunk(
        self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None
    ):
        generation = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation is not None:
            try:
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    generation.message.additional_kwargs["reasoning_content"] = reasoning
            except Exception:
                pass
        return generation

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info=generation_info)
        try:
            response_dict = (
                response
                if isinstance(response, dict)
                else response.model_dump(warnings=False)
            )
            choices = response_dict.get("choices") or []
            for i, generation in enumerate(result.generations):
                message = generation.message
                if not isinstance(message, AIMessage):
                    continue
                choice = choices[i] if i < len(choices) else {}
                choice_message = (
                    (choice.get("message") or {}) if isinstance(choice, dict) else {}
                )
                reasoning = choice_message.get("reasoning_content")
                if reasoning:
                    existing = message.additional_kwargs.get("reasoning_content")
                    if isinstance(existing, str):
                        message.additional_kwargs["reasoning_content"] = existing + reasoning
                    else:
                        message.additional_kwargs["reasoning_content"] = reasoning
        except Exception:
            pass
        return result


def get_llm_thinking_config() -> Optional[dict]:
    """
    返回当前平台应发送的 thinking 参数。

    智谱（zhipu / zhipu4）且 LLM_THINKING_ENABLED=True 时返回 {"type": "enabled"}，
    其余平台返回 None（避免 OpenAI 兼容端点拒绝未知参数）。
    """
    cfg = get_active_llm_config()
    if cfg["provider"] in ("zhipu", "zhipu4") and settings.LLM_THINKING_ENABLED:
        return {"type": "enabled"}
    return None


def build_llm(
    *,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    streaming: bool = False,
    timeout: float = settings.LLM_TIMEOUT,
    enable_thinking: Optional[bool] = None,
) -> ChatOpenAI:
    """
    构造一个 LangChain ChatModel 实例，指向当前 LLM_PROVIDER 配置的 OpenAI 兼容端点。

    Args:
        model: 模型名，默认取当前 LLM_PROVIDER 对应配置的模型
        temperature: 采样温度，规划类建议 0.2-0.4
        max_tokens: 单次输出最大 tokens
        streaming: 是否流式（true 时底层走 SSE，invoke 仍返回完整消息，
            并可捕获流式 reasoning_content 写入日志）
        timeout: 单次请求超时（秒），默认取 settings.LLM_TIMEOUT
        enable_thinking: 是否开启思考；None 时跟随 settings.LLM_THINKING_ENABLED
            （仅智谱平台生效）

    Returns:
        ReasoningLoggingChatOpenAI 实例，可用于 LangGraph 的 ToolNode / create_react_agent
    """
    cfg = get_active_llm_config()
    extra_body: dict[str, Any] = {}
    if enable_thinking is None or enable_thinking:
        thinking = get_llm_thinking_config()
        if thinking:
            # 智谱 thinking 是 OpenAI 规范之外的参数，必须走 extra_body 透传，
            # 不能放 model_kwargs（后者会被当作具名参数传给 SDK 导致
            # "Completions.create() got an unexpected keyword argument 'thinking'"）
            extra_body["thinking"] = thinking
    return ReasoningLoggingChatOpenAI(
        model=model or cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
        timeout=timeout,
        extra_body=extra_body or None,
    )


def log_llm_invocation() -> None:
    """
    在每次调用大模型前打印当前平台与模型，便于日志定位输出来源。

    所有真实 LLM 调用（行程生成 / JSON 修复 / 天气建议 / 意图识别）
    都在 invoke 之前调用本函数。
    """
    cfg = get_active_llm_config()
    logger.info(
        f"调用大模型: 平台={cfg['provider']} 模型={cfg['model']} 端点={cfg['base_url']} "
        f"思考={bool(get_llm_thinking_config())}"
    )


def _message_to_log_dict(message: Any) -> Any:
    """LangChain 消息 → 可 JSON 序列化的 OpenAI 兼容消息 dict（仅用于日志）。"""
    if not isinstance(message, BaseMessage):
        return message
    role_map = {
        "human": "user",
        "ai": "assistant",
        "system": "system",
        "tool": "tool",
        "function": "function",
        "chat": getattr(message, "role", "chat"),
    }
    entry: dict[str, Any] = {"role": role_map.get(message.type, message.type)}
    entry["content"] = message.content
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        entry["tool_calls"] = tool_calls
    tool_call_id = getattr(message, "tool_call_id", None)
    if tool_call_id:
        entry["tool_call_id"] = tool_call_id
    return entry


def log_llm_request(
    *,
    messages: list,
    note: str = "",
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    streaming: Optional[bool] = None,
    thinking: Optional[dict] = None,
    tools: Optional[list] = None,
    **extra: Any,
) -> None:
    """
    每次调用大模型前记录完整入参（平台 / 模型 / 参数 / 全部消息）。

    Args:
        messages: 将发送给模型的完整消息列表（LangChain 消息或 dict）
        note: 调用场景标签（如 plan / repair_json / weather_suggest），便于 grep
        tools: 绑定的工具名列表（可选）
        extra: 其余请求参数，随入参一并记录
    """
    cfg = get_active_llm_config()
    label = f"[{note}] " if note else ""
    try:
        params: dict[str, Any] = {
            "provider": cfg["provider"],
            "model": model or cfg["model"],
            "base_url": cfg["base_url"],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "streaming": streaming,
            "thinking": thinking,
            "tools": tools,
        }
        params.update(extra)
        logger.info(
            f"LLM 请求入参{label}: {json.dumps(params, ensure_ascii=False, default=str)}"
        )
        serialized = [_message_to_log_dict(m) for m in messages]
        logger.info(
            f"LLM 请求消息{label}: {json.dumps(serialized, ensure_ascii=False, default=str)}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"LLM 请求入参记录失败: {exc}")


def log_llm_reasoning(reasoning: str, *, note: str = "") -> None:
    """把模型思考过程（reasoning_content）写入日志。"""
    if not reasoning:
        return
    label = f"[{note}] " if note else ""
    logger.info(f"LLM 思考过程{label}: {reasoning}")


def log_llm_reasoning_from_message(message: Any, *, note: str = "") -> None:
    """从模型响应（LangChain 消息 / dict / SDK 对象）中提取 reasoning_content 并写日志。"""
    reasoning = None
    try:
        if isinstance(message, BaseMessage):
            reasoning = (message.additional_kwargs or {}).get("reasoning_content")
        elif isinstance(message, dict):
            reasoning = message.get("reasoning_content")
        elif message is not None:
            reasoning = getattr(message, "reasoning_content", None)
    except Exception:
        reasoning = None
    if reasoning:
        log_llm_reasoning(str(reasoning), note=note)


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
