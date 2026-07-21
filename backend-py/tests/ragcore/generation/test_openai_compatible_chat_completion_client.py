"""`OpenAiCompatibleChatCompletionClient` 测试。

对照 Java 版 `OpenAiCompatibleChatCompletionClient.java`:验证配置校验、HTTP 请求结构、
成功路径解析 content、错误路径(5xx/4xx/网络异常/响应非法 JSON/缺字段)统一抛
`ModelClientException` 且不重试——这与 Rerank/Embedding 客户端一致,Java 版也没有重试。
用 `httpx.MockTransport` 模拟服务端,避免在测试里启真实 HTTP 服务。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.ragcore.generation.openai_compatible_chat_completion_client import (
    ChatCompletionProperties,
    OpenAiCompatibleChatCompletionClient,
    build_chat_completion_client,
)
from app.ragcore.model import ModelClientException


def _properties(**overrides) -> ChatCompletionProperties:
    defaults = dict(
        enabled=True,
        endpoint="http://model-gateway/chat",
        api_key="",
        model="deepseek-chat",
        timeout_ms=5_000,
        include_usage=True,
    )
    defaults.update(overrides)
    return ChatCompletionProperties(**defaults)


def _client_with_handler(handler, **prop_overrides) -> OpenAiCompatibleChatCompletionClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return OpenAiCompatibleChatCompletionClient(_properties(**prop_overrides), http_client=http_client)


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


class TestRequestBody:
    async def test_body_uses_model_and_stream_false(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        client = _client_with_handler(handler, model="deepseek-chat")
        await client.complete("sys", "user")

        assert captured["body"]["model"] == "deepseek-chat"
        assert captured["body"]["stream"] is False
        assert captured["body"]["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user"},
        ]

    async def test_authorization_header_sent_when_api_key_present(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        client = _client_with_handler(handler, api_key="secret-key")
        await client.complete("s", "u")

        assert captured["headers"].get("authorization") == "Bearer secret-key"

    async def test_no_authorization_header_when_api_key_blank(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        client = _client_with_handler(handler, api_key="")
        await client.complete("s", "u")

        # httpx 头名是 lower-case
        assert "authorization" not in captured["headers"]


class TestHappyPath:
    async def test_returns_first_choice_message_content(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "这是回答"}}]},
            )

        client = _client_with_handler(handler)
        result = await client.complete("sys", "user")

        assert result == "这是回答"

    async def test_picks_first_choice_when_multiple(self):
        """Java 版只取 `choices.get(0)`,与 OpenAI 行为一致(其它 choice 一般是 n>1)。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "第一个"}},
                        {"message": {"content": "第二个"}},
                    ]
                },
            )

        client = _client_with_handler(handler)
        result = await client.complete("s", "u")
        assert result == "第一个"


class TestNoRetryOnFailure:
    """Java 版无重试逻辑,单次失败即抛 — 这里验证 4xx/5xx/网络异常都不重试。"""

    async def test_5xx_raises_without_retry(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(503, json={"error": "unavailable"})

        client = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await client.complete("s", "u")
        assert call_count["n"] == 1

    async def test_4xx_raises_without_retry(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(401, json={"error": "unauthorized"})

        client = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await client.complete("s", "u")
        assert call_count["n"] == 1

    async def test_transport_error_raises_model_client_exception(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await client.complete("s", "u")


class TestResponseParsingErrors:
    async def test_missing_choices_raises(self):
        client = _client_with_handler(lambda req: httpx.Response(200, json={"foo": "bar"}))
        with pytest.raises(ModelClientException):
            await client.complete("s", "u")

    async def test_empty_choices_raises(self):
        client = _client_with_handler(lambda req: httpx.Response(200, json={"choices": []}))
        with pytest.raises(ModelClientException):
            await client.complete("s", "u")

    async def test_missing_message_raises(self):
        client = _client_with_handler(
            lambda req: httpx.Response(200, json={"choices": [{"finish_reason": "stop"}]})
        )
        with pytest.raises(ModelClientException):
            await client.complete("s", "u")

    async def test_missing_content_raises(self):
        client = _client_with_handler(
            lambda req: httpx.Response(200, json={"choices": [{"message": {"role": "assistant"}}]})
        )
        with pytest.raises(ModelClientException):
            await client.complete("s", "u")

    async def test_non_json_response_raises(self):
        client = _client_with_handler(lambda req: httpx.Response(200, content=b"not json"))
        with pytest.raises(ModelClientException):
            await client.complete("s", "u")


class TestBuildChatCompletionClient:
    def test_disabled_returns_none(self):
        class _Cfg:
            rag_generation_enabled = False

        assert build_chat_completion_client(_Cfg()) is None

    def test_enabled_builds_client(self, monkeypatch):
        for var in ("all_proxy", "ALL_PROXY", "http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
            monkeypatch.delenv(var, raising=False)

        class _Cfg:
            rag_generation_enabled = True
            rag_generation_endpoint = "http://gw/chat"
            rag_generation_api_key = "k"
            rag_generation_model = "deepseek-chat"
            rag_generation_timeout_ms = 30_000
            rag_generation_include_usage = True

        client = build_chat_completion_client(_Cfg())
        assert isinstance(client, OpenAiCompatibleChatCompletionClient)
