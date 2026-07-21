"""OpenAiCompatibleEmbeddingClient 测试。

对照 Java 版 `OpenAiCompatibleEmbeddingClient.java`：429/5xx 触发重试（超过 max_attempts
后抛出 ModelClientException）、4xx 参数错误不重试、batch 请求按下标把响应向量对应回请求
顺序。用 `httpx.MockTransport` 模拟服务端，不发真实网络请求。
"""

from __future__ import annotations

import httpx
import pytest

from app.ragcore.embedding.openai_compatible import (
    EmbeddingProperties,
    OpenAiCompatibleEmbeddingClient,
    build_embedding_client,
)
from app.ragcore.model import ModelClientException


def _properties(**overrides) -> EmbeddingProperties:
    defaults = dict(
        enabled=True,
        endpoint="http://model-gateway/v1/embeddings",
        api_key="",
        model="bge-m3",
        timeout_ms=5_000,
        batch_size=32,
        max_attempts=3,
        retry_backoff_ms=1,  # 测试里用极小值，避免真的睡 backoff
    )
    defaults.update(overrides)
    return EmbeddingProperties(**defaults)


def _client_with_handler(handler, **prop_overrides) -> OpenAiCompatibleEmbeddingClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return OpenAiCompatibleEmbeddingClient(_properties(**prop_overrides), http_client=http_client)


def _embedding_response(indices_and_vectors: list[tuple[int, list[float]]], model: str | None = None) -> dict:
    body: dict = {"data": [{"index": i, "embedding": v} for i, v in indices_and_vectors]}
    if model is not None:
        body["model"] = model
    return body


class TestEmbeddingPropertiesValidation:
    def test_defaults_are_valid(self):
        props = _properties()
        assert props.batch_size == 32
        assert props.max_attempts == 3

    def test_rejects_blank_endpoint(self):
        with pytest.raises(ValueError):
            _properties(endpoint="  ")

    def test_rejects_blank_model(self):
        with pytest.raises(ValueError):
            _properties(model="")

    def test_rejects_non_positive_batch_size(self):
        with pytest.raises(ValueError):
            _properties(batch_size=0)

    def test_rejects_max_attempts_out_of_range(self):
        with pytest.raises(ValueError):
            _properties(max_attempts=0)
        with pytest.raises(ValueError):
            _properties(max_attempts=11)

    def test_rejects_negative_retry_backoff(self):
        with pytest.raises(ValueError):
            _properties(retry_backoff_ms=-1)

    def test_rejects_retry_backoff_over_ceiling(self):
        with pytest.raises(ValueError):
            _properties(retry_backoff_ms=60_001)

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError):
            _properties(timeout_ms=0)


class TestEmptyAndInvalidInput:
    async def test_empty_texts_returns_empty_result_without_http_call(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=_embedding_response([]))

        client = _client_with_handler(handler)
        result = await client.embed([])
        assert result.vectors == ()
        assert result.model_version == "bge-m3"
        assert calls == []

    async def test_blank_text_in_batch_raises_value_error(self):
        client = _client_with_handler(lambda request: httpx.Response(200, json=_embedding_response([])))
        with pytest.raises(ValueError):
            await client.embed(["ok", "   "])

    async def test_none_like_blank_text_raises_value_error(self):
        client = _client_with_handler(lambda request: httpx.Response(200, json=_embedding_response([])))
        with pytest.raises(ValueError):
            await client.embed([""])


class TestSuccessfulEmbedding:
    async def test_single_batch_vectors_align_by_index(self):
        """响应里 index 乱序返回也必须按 index 排回请求顺序，而不是按响应数组顺序。"""

        def handler(request: httpx.Request) -> httpx.Response:
            payload = _embedding_response([(1, [0.2, 0.2]), (0, [0.1, 0.1])], model="bge-m3-v2")
            return httpx.Response(200, json=payload)

        client = _client_with_handler(handler)
        result = await client.embed(["文本A", "文本B"])
        assert result.vectors == ((0.1, 0.1), (0.2, 0.2))
        assert result.model_version == "bge-m3-v2"

    async def test_batching_splits_requests_and_concatenates_in_order(self):
        seen_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = request.read()
            import json as _json

            payload = _json.loads(body)
            seen_bodies.append(payload["input"])
            vectors = [(i, [float(len(t))]) for i, t in enumerate(payload["input"])]
            return httpx.Response(200, json=_embedding_response(vectors))

        client = _client_with_handler(handler, batch_size=2)
        texts = ["a", "bb", "ccc", "dddd", "e"]
        result = await client.embed(texts)
        assert seen_bodies == [["a", "bb"], ["ccc", "dddd"], ["e"]]
        assert result.vectors == ((1.0,), (2.0,), (3.0,), (4.0,), (1.0,))

    async def test_blank_model_version_in_response_keeps_previous_model(self):
        def handler(request: httpx.Request) -> httpx.Response:
            payload = _embedding_response([(0, [0.1])], model="   ")
            return httpx.Response(200, json=payload)

        client = _client_with_handler(handler)
        result = await client.embed(["x"])
        assert result.model_version == "bge-m3"

    async def test_api_key_sets_authorization_header(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=_embedding_response([(0, [0.1])]))

        client = _client_with_handler(handler, api_key="secret-key")
        await client.embed(["x"])
        assert captured["auth"] == "Bearer secret-key"

    async def test_no_api_key_omits_authorization_header(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=_embedding_response([(0, [0.1])]))

        client = _client_with_handler(handler, api_key="")
        await client.embed(["x"])
        assert captured["auth"] is None


class TestRetryBehavior:
    async def test_429_retries_then_succeeds(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] < 3:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json=_embedding_response([(0, [0.5])]))

        client = _client_with_handler(handler, max_attempts=3)
        result = await client.embed(["x"])
        assert call_count["n"] == 3
        assert result.vectors == ((0.5,),)

    async def test_5xx_retries_then_succeeds(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] < 2:
                return httpx.Response(503, json={"error": "unavailable"})
            return httpx.Response(200, json=_embedding_response([(0, [0.5])]))

        client = _client_with_handler(handler, max_attempts=3)
        result = await client.embed(["x"])
        assert call_count["n"] == 2
        assert result.vectors == ((0.5,),)

    async def test_exceeds_max_attempts_raises_model_client_exception(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(500, json={"error": "boom"})

        client = _client_with_handler(handler, max_attempts=3)
        with pytest.raises(ModelClientException):
            await client.embed(["x"])
        assert call_count["n"] == 3

    async def test_4xx_does_not_retry(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(400, json={"error": "bad request"})

        client = _client_with_handler(handler, max_attempts=3)
        with pytest.raises(ModelClientException):
            await client.embed(["x"])
        assert call_count["n"] == 1

    async def test_404_does_not_retry(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(404, json={"error": "not found"})

        client = _client_with_handler(handler, max_attempts=3)
        with pytest.raises(ModelClientException):
            await client.embed(["x"])
        assert call_count["n"] == 1

    async def test_transport_error_retries_then_raises_after_max_attempts(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            raise httpx.ConnectError("connection refused", request=request)

        client = _client_with_handler(handler, max_attempts=2)
        with pytest.raises(ModelClientException):
            await client.embed(["x"])
        assert call_count["n"] == 2

    async def test_malformed_response_after_200_does_not_retry(self):
        """响应解析失败（size 不匹配）不在重试范围内，直接抛出，与 Java 版一致。"""

        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(200, json={"data": []})

        client = _client_with_handler(handler, max_attempts=3)
        with pytest.raises(ModelClientException):
            await client.embed(["x"])
        assert call_count["n"] == 1


class TestResponseParsing:
    async def test_missing_index_raises(self):
        client = _client_with_handler(
            lambda request: httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        )
        with pytest.raises(ModelClientException):
            await client.embed(["x"])

    async def test_empty_embedding_vector_raises(self):
        client = _client_with_handler(
            lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": []}]})
        )
        with pytest.raises(ModelClientException):
            await client.embed(["x"])

    async def test_non_numeric_vector_element_raises(self):
        client = _client_with_handler(
            lambda request: httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [0.1, "oops"]}]}
            )
        )
        with pytest.raises(ModelClientException):
            await client.embed(["x"])

    async def test_duplicate_index_raises(self):
        client = _client_with_handler(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 0, "embedding": [0.1]},
                        {"index": 0, "embedding": [0.2]},
                    ]
                },
            )
        )
        with pytest.raises(ModelClientException):
            await client.embed(["x", "y"])

    async def test_not_json_response_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json")

        client = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await client.embed(["x"])


class TestBuildEmbeddingClient:
    def test_disabled_returns_none(self):
        class _Cfg:
            rag_embedding_enabled = False

        assert build_embedding_client(_Cfg()) is None

    def test_enabled_builds_client(self, monkeypatch):
        # 本机开发环境可能配了 SOCKS 代理环境变量；build_embedding_client 未注入
        # http_client 时会用默认 httpx.AsyncClient()（trust_env=True）立即建连接池，
        # 这里清掉代理变量避免测试因缺少可选依赖 socksio 而失败，与被测逻辑本身无关。
        for var in ("all_proxy", "ALL_PROXY", "http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
            monkeypatch.delenv(var, raising=False)

        class _Cfg:
            rag_embedding_enabled = True
            rag_embedding_endpoint = "http://gw/v1/embeddings"
            rag_embedding_api_key = ""
            rag_embedding_model = "bge-m3"
            rag_embedding_timeout_ms = 5_000
            rag_embedding_batch_size = 32
            rag_embedding_max_attempts = 3
            rag_embedding_retry_backoff_ms = 200

        client = build_embedding_client(_Cfg())
        assert isinstance(client, OpenAiCompatibleEmbeddingClient)
