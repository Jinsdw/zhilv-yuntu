"""
智旅云图 - llm_factory 单元测试

覆盖：
- thinking 参数开关（智谱开启 / 配置关闭 / 非智谱平台不发送）
- 流式与非流式响应中 reasoning_content（思考过程）的捕获
- LLM 请求入参 / 思考过程日志输出
"""

from loguru import logger
from langchain_core.messages import AIMessage, AIMessageChunk

from app.agents.llm_factory import (
    ReasoningLoggingChatOpenAI,
    build_llm,
    log_llm_reasoning,
    log_llm_reasoning_from_message,
    log_llm_request,
)
from app.config import settings


def _make_llm() -> ReasoningLoggingChatOpenAI:
    return ReasoningLoggingChatOpenAI(
        model="test-model",
        api_key="test-key",
        base_url="https://example.com/v1",
        temperature=0.0,
        max_tokens=128,
    )


def test_thinking_enabled_for_zhipu(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "zhipu")
    monkeypatch.setattr(settings, "LLM_THINKING_ENABLED", True)
    llm = build_llm(enable_thinking=True)
    assert llm.extra_body.get("thinking") == {"type": "enabled"}


def test_thinking_disabled_by_settings(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "zhipu")
    monkeypatch.setattr(settings, "LLM_THINKING_ENABLED", False)
    llm = build_llm()
    assert llm.extra_body is None


def test_thinking_not_sent_for_other_providers(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "packycode")
    monkeypatch.setattr(settings, "LLM_THINKING_ENABLED", True)
    llm = build_llm()
    assert llm.extra_body is None


def test_streaming_chunk_reasoning_captured():
    llm = _make_llm()
    chunk = {
        "choices": [
            {
                "delta": {
                    "role": "assistant",
                    "reasoning_content": "先分析用户需求",
                }
            }
        ],
    }
    generation = llm._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, {})
    assert generation is not None
    assert (
        generation.message.additional_kwargs.get("reasoning_content")
        == "先分析用户需求"
    )


def test_non_streaming_reasoning_captured():
    llm = _make_llm()
    response = {
        "id": "x",
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "{}",
                    "reasoning_content": "思考：先检查 JSON 结构",
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    result = llm._create_chat_result(response)
    message = result.generations[0].message
    assert message.additional_kwargs.get("reasoning_content") == "思考：先检查 JSON 结构"


def test_log_llm_request_writes_full_payload():
    records = []
    sink_id = logger.add(lambda msg: records.append(str(msg)))
    try:
        log_llm_request(
            messages=[{"role": "user", "content": "帮我规划成都三日游"}],
            note="test",
            temperature=0.5,
            max_tokens=16,
            streaming=False,
            tools=["search_travel_guides"],
        )
    finally:
        logger.remove(sink_id)
    text = "\n".join(records)
    assert "LLM 请求入参[test]" in text
    assert '"temperature": 0.5' in text
    assert '"tools": ["search_travel_guides"]' in text
    assert "帮我规划成都三日游" in text


def test_log_llm_reasoning_from_message():
    records = []
    sink_id = logger.add(lambda msg: records.append(str(msg)))
    try:
        message = AIMessage(
            content="{}",
            additional_kwargs={"reasoning_content": "逐步思考：先选景点再排时间"},
        )
        log_llm_reasoning_from_message(message, note="plan")
        log_llm_reasoning("第二段思考", note="repair_json")
    finally:
        logger.remove(sink_id)
    text = "\n".join(records)
    assert "LLM 思考过程[plan] : 逐步思考：先选景点再排时间" in text
    assert "LLM 思考过程[repair_json] : 第二段思考" in text
