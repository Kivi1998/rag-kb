"""`OpenAiCompatibleAnswerGenerator` 测试。

对照 Java 版 `ragcore/generation/OpenAiCompatibleAnswerGenerator.java`:验证请求体构造
(stream=true, stream_options.include_usage, model, messages)、SSE 解析(content delta
产出 `QueryEvent.chunk`、usage 回填 metrics、model 回填 metrics、`[DONE]` 哨兵结束)、
`metrics` 原地累加(尤其 `output_characters`)、错误路径(5xx/4xx/网络异常)统一抛
`ModelClientException`。用 `httpx.MockTransport` 构造 SSE 响应。
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx
import pytest

from app.ragcore.generation.metrics import GenerationMetrics
from app.ragcore.generation.openai_compatible_answer_generator import (
    GenerationProperties,
    OpenAiCompatibleAnswerGenerator,
    build_answer_generator,
)
from app.ragcore.generation.prompt_assembler import PromptAssembler
from app.ragcore.model import ModelClientException, QueryEvent, QueryEventType, RetrievedChunk


def _properties(**overrides) -> GenerationProperties:
    defaults = dict(
        enabled=True,
        endpoint="http://model-gateway/chat",
        api_key="",
        model="deepseek-chat",
        timeout_ms=5_000,
        include_usage=True,
    )
    defaults.update(overrides)
    return GenerationProperties(**defaults)


def _client_with_handler(handler, **prop_overrides) -> OpenAiCompatibleAnswerGenerator:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return OpenAiCompatibleAnswerGenerator(_properties(**prop_overrides), PromptAssembler(), http_client=http_client)


def _sse_lines(*lines: str) -> bytes:
    """把多行 SSE 数据拼成符合 `text/event-stream` 格式的字节流。

    每行以 `\\n` 结尾,SSE 块之间留一个空行(OpenAI 实际行为)。
    """
    return "\n".join(lines).encode("utf-8") + b"\n"


def _chunk_line(content: str, model: str = "deepseek-chat") -> str:
    """构造一条 OpenAI 风格的 content delta SSE 行。"""
    payload = {"id": "1", "model": model, "choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload, ensure_ascii=False)}"


def _usage_line(prompt: int, completion: int, model: str = "deepseek-chat") -> str:
    """构造带 usage 的 SSE 行(stream_options.include_usage=true 时最后一个块附带)。"""
    payload = {
        "id": "1",
        "model": model,
        "choices": [],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}"


def _done_line() -> str:
    return "data: [DONE]"


async def _collect(generator: AsyncIterator[QueryEvent]) -> list[QueryEvent]:
    out: list[QueryEvent] = []
    async for event in generator:
        out.append(event)
    return out


class TestPropertiesValidation:
    def test_rejects_blank_endpoint(self):
        with pytest.raises(ValueError):
            _properties(endpoint="   ")

    def test_rejects_blank_model(self):
        with pytest.raises(ValueError):
            _properties(model="")

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError):
            _properties(timeout_ms=0)


class TestModelId:
    def test_model_id_returns_configured_model(self):
        gen = _client_with_handler(lambda req: httpx.Response(200, content=b""))
        assert gen.model_id() == "deepseek-chat"

    def test_model_id_uses_overridden_value(self):
        gen = _client_with_handler(lambda req: httpx.Response(200, content=b""), model="gpt-4")
        assert gen.model_id() == "gpt-4"


class TestRequestBody:
    async def test_request_body_includes_stream_and_options(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, content=_sse_lines(_done_line()))

        gen = _client_with_handler(handler)
        metrics = GenerationMetrics()
        await _collect(gen.stream_with_metrics("q?", [], metrics))

        assert captured["body"]["stream"] is True
        assert captured["body"]["stream_options"] == {"include_usage": True}
        assert captured["body"]["model"] == "deepseek-chat"
        # messages 应该是 system + user 两条
        assert len(captured["body"]["messages"]) == 2
        assert captured["body"]["messages"][0]["role"] == "system"
        assert captured["body"]["messages"][1]["role"] == "user"
        # temperature=0 是 Java 版固定值,保留以匹配生成行为
        assert captured["body"]["temperature"] == 0

    async def test_authorization_header_sent_when_api_key_present(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, content=_sse_lines(_done_line()))

        gen = _client_with_handler(handler, api_key="k-1")
        await _collect(gen.stream_with_metrics("q", [], GenerationMetrics()))

        assert captured["headers"].get("authorization") == "Bearer k-1"

    async def test_accept_header_for_event_stream(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, content=_sse_lines(_done_line()))

        gen = _client_with_handler(handler)
        await _collect(gen.stream_with_metrics("q", [], GenerationMetrics()))

        assert captured["headers"].get("accept") == "text/event-stream"


class TestSseParsing:
    async def test_chunks_emitted_as_query_event_chunk(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse_lines(
                    _chunk_line("第一段"),
                    _chunk_line("第二段"),
                    _done_line(),
                ),
            )

        gen = _client_with_handler(handler)
        metrics = GenerationMetrics()
        events = await _collect(gen.stream_with_metrics("q", [], metrics))

        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert [c.content for c in chunks] == ["第一段", "第二段"]
        # Java 版同款:metrics.output_characters 累加 delta content 长度
        assert metrics.output_characters == len("第一段") + len("第二段")

    async def test_done_sentinel_terminates_stream(self):
        """`[DONE]` 之后即使还有内容也不应该被处理。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse_lines(
                    _chunk_line("OK"),
                    _done_line(),
                    _chunk_line("不应该出现"),
                ),
            )

        gen = _client_with_handler(handler)
        events = await _collect(gen.stream_with_metrics("q", [], GenerationMetrics()))
        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert [c.content for c in chunks] == ["OK"]

    async def test_usage_in_final_chunk_fills_metrics(self):
        """stream_options.include_usage=true 时,最后一个块附带 usage,必须回填 metrics。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse_lines(
                    _chunk_line("回答内容"),
                    _usage_line(prompt=12, completion=8, model="gpt-4o"),
                    _done_line(),
                ),
            )

        gen = _client_with_handler(handler)
        metrics = GenerationMetrics()
        await _collect(gen.stream_with_metrics("q", [], metrics))

        assert metrics.prompt_tokens == 12
        assert metrics.completion_tokens == 8
        # usage 行的 model 优先于 properties.model(不同网关可能返回不同 model 名)
        assert metrics.model == "gpt-4o"

    async def test_falls_back_to_configured_model_when_stream_omits_model(self):
        """每个 chunk 都可能不带 model 字段,只有 usage 块带;不存在 model 时保留 properties.model。"""

        def handler(request: httpx.Request) -> httpx.Response:
            line = f"data: {json.dumps({'choices': [{'delta': {'content': 'hi'}}]})}"
            return httpx.Response(200, content=_sse_lines(line, _done_line()))

        gen = _client_with_handler(handler, model="fallback-model")
        metrics = GenerationMetrics()
        await _collect(gen.stream_with_metrics("q", [], metrics))
        assert metrics.model == "fallback-model"

    async def test_empty_content_delta_does_not_emit_chunk(self):
        """delta.content 是空字符串时不应产出 chunk 事件,与 Java 版一致。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse_lines(
                    f"data: {json.dumps({'choices': [{'delta': {'content': ''}}]})}",
                    _chunk_line("hi"),
                    _done_line(),
                ),
            )

        gen = _client_with_handler(handler)
        events = await _collect(gen.stream_with_metrics("q", [], GenerationMetrics()))
        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert [c.content for c in chunks] == ["hi"]

    async def test_ignores_non_data_lines(self):
        """SSE 注释/心跳行(不以 data: 开头)必须跳过。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse_lines(
                    ": heartbeat",
                    "event: ping",
                    _chunk_line("实际内容"),
                    _done_line(),
                ),
            )

        gen = _client_with_handler(handler)
        events = await _collect(gen.stream_with_metrics("q", [], GenerationMetrics()))
        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert [c.content for c in chunks] == ["实际内容"]

    async def test_empty_data_line_skipped_without_error(self):
        """空 data 行(常见于 SSE keep-alive)必须跳过,不能因为空字符串解析 JSON 失败抛异常。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse_lines(
                    "data:",
                    "data:  ",
                    _chunk_line("ok"),
                    _done_line(),
                ),
            )

        gen = _client_with_handler(handler)
        events = await _collect(gen.stream_with_metrics("q", [], GenerationMetrics()))
        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert [c.content for c in chunks] == ["ok"]


class TestErrorPropagation:
    async def test_5xx_raises_model_client_exception(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        gen = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await _collect(gen.stream_with_metrics("q", [], GenerationMetrics()))

    async def test_4xx_raises_model_client_exception(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        gen = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await _collect(gen.stream_with_metrics("q", [], GenerationMetrics()))

    async def test_transport_error_raises_model_client_exception(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        gen = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await _collect(gen.stream_with_metrics("q", [], GenerationMetrics()))

    async def test_malformed_json_raises_model_client_exception(self):
        """非 JSON 的 data 行(不是空)按 Java 版同款语义,抛 ModelClientException。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_sse_lines("data: not-json-at-all", _done_line()))

        gen = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await _collect(gen.stream_with_metrics("q", [], GenerationMetrics()))


class TestContextPrompting:
    async def test_additional_system_context_appears_in_system_prompt(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, content=_sse_lines(_done_line()))

        gen = _client_with_handler(handler)
        await _collect(
            gen.stream_with_metrics("q", [], GenerationMetrics(), additional_system_context="用户是财务")
        )

        system_prompt = captured["body"]["messages"][0]["content"]
        assert "用户是财务" in system_prompt

    async def test_user_prompt_contains_question(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, content=_sse_lines(_done_line()))

        gen = _client_with_handler(handler)
        # 用 RetrievedChunk 包装一下避免 mypy 报类型错误;PromptAssembler 不要求 chunk 有内容
        await _collect(
            gen.stream_with_metrics("这是用户的问题", [], GenerationMetrics())
        )

        user_prompt = captured["body"]["messages"][1]["content"]
        assert "这是用户的问题" in user_prompt


class TestMetricsInPlaceUpdate:
    async def test_output_characters_accumulates_across_chunks(self):
        """Java 版 `outputCharacters += content.asText().length()` 的 Python 对应。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse_lines(
                    _chunk_line("a"),
                    _chunk_line("bb"),
                    _chunk_line("ccc"),
                    _done_line(),
                ),
            )

        gen = _client_with_handler(handler)
        metrics = GenerationMetrics()
        await _collect(gen.stream_with_metrics("q", [], metrics))
        assert metrics.output_characters == 6  # 1+2+3

    async def test_metrics_default_unchanged_when_stream_empty(self):
        """空流(只有 [DONE])应当让 metrics 保持原状,除 model 字段可能没被覆盖。"""
        gen = _client_with_handler(lambda req: httpx.Response(200, content=_sse_lines(_done_line())))
        metrics = GenerationMetrics()
        await _collect(gen.stream_with_metrics("q", [], metrics))
        assert metrics.output_characters == 0
        assert metrics.prompt_tokens is None
        assert metrics.completion_tokens is None


class TestBuildAnswerGenerator:
    def test_disabled_returns_none(self):
        class _Cfg:
            rag_generation_enabled = False

        assert build_answer_generator(_Cfg()) is None

    def test_enabled_builds_generator(self, monkeypatch):
        for var in ("all_proxy", "ALL_PROXY", "http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
            monkeypatch.delenv(var, raising=False)

        class _Cfg:
            rag_generation_enabled = True
            rag_generation_endpoint = "http://gw/chat"
            rag_generation_api_key = ""
            rag_generation_model = "deepseek-chat"
            rag_generation_timeout_ms = 60_000
            rag_generation_include_usage = True

        gen = build_answer_generator(_Cfg())
        assert isinstance(gen, OpenAiCompatibleAnswerGenerator)
        assert gen.model_id() == "deepseek-chat"
