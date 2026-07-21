"""HttpNliClient 测试。

对照 Java 版 `HttpNliClient.java`：与 Rerank/Generation 客户端一样没有重试逻辑（单次请求
失败即抛出）。用 `httpx.MockTransport` 模拟 `nli-gateway`。
"""

from __future__ import annotations

import httpx
import pytest

from app.ragcore.model import ModelClientException
from app.ragcore.nli.client import NliVerdict
from app.ragcore.nli.http_client import HttpNliClient, NliProperties, build_nli_client


def _properties(**overrides) -> NliProperties:
    defaults = dict(enabled=True, endpoint="http://nli-gateway/nli", timeout_ms=5_000)
    defaults.update(overrides)
    return NliProperties(**defaults)


def _client_with_handler(handler, **prop_overrides) -> HttpNliClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return HttpNliClient(_properties(**prop_overrides), http_client=http_client)


class TestNliPropertiesValidation:
    def test_rejects_blank_endpoint(self):
        with pytest.raises(ValueError):
            _properties(endpoint="  ")

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError):
            _properties(timeout_ms=0)


class TestSuccessfulCheck:
    async def test_parses_verdict_from_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "label": "entailment",
                    "entailment_prob": 0.85,
                    "neutral_prob": 0.1,
                    "contradiction_prob": 0.05,
                },
            )

        client = _client_with_handler(handler)
        verdict = await client.check("premise", "hypothesis")

        assert verdict == NliVerdict(
            label="entailment", entailment_prob=0.85, neutral_prob=0.1, contradiction_prob=0.05
        )

    async def test_request_body_contains_premise_and_hypothesis(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            captured["body"] = _json.loads(request.read())
            return httpx.Response(
                200,
                json={"label": "neutral", "entailment_prob": 0.1, "neutral_prob": 0.8, "contradiction_prob": 0.1},
            )

        client = _client_with_handler(handler)
        await client.check("这是前提", "这是假设")

        assert captured["body"] == {"premise": "这是前提", "hypothesis": "这是假设"}


class TestNoRetryOnFailure:
    async def test_5xx_does_not_retry(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(503, json={"error": "unavailable"})

        client = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await client.check("p", "h")
        assert call_count["n"] == 1

    async def test_transport_error_raises_model_client_exception(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await client.check("p", "h")


class TestResponseParsingErrors:
    async def test_missing_field_raises(self):
        client = _client_with_handler(
            lambda request: httpx.Response(200, json={"label": "entailment", "entailment_prob": 0.9})
        )
        with pytest.raises(ModelClientException):
            await client.check("p", "h")

    async def test_non_numeric_prob_raises(self):
        client = _client_with_handler(
            lambda request: httpx.Response(
                200,
                json={
                    "label": "entailment",
                    "entailment_prob": "high",
                    "neutral_prob": 0.1,
                    "contradiction_prob": 0.0,
                },
            )
        )
        with pytest.raises(ModelClientException):
            await client.check("p", "h")

    async def test_not_json_response_raises(self):
        client = _client_with_handler(lambda request: httpx.Response(200, content=b"not json"))
        with pytest.raises(ModelClientException):
            await client.check("p", "h")


class TestBuildNliClient:
    def test_disabled_returns_none(self):
        class _Cfg:
            rag_nli_enabled = False

        assert build_nli_client(_Cfg()) is None

    def test_enabled_builds_client(self, monkeypatch):
        for var in ("all_proxy", "ALL_PROXY", "http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
            monkeypatch.delenv(var, raising=False)

        class _Cfg:
            rag_nli_enabled = True
            rag_nli_endpoint = "http://nli-gateway/nli"
            rag_nli_timeout_ms = 5_000

        client = build_nli_client(_Cfg())
        assert isinstance(client, HttpNliClient)
