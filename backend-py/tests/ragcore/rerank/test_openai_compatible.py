"""OpenAiCompatibleRerankerClient 测试。

对照 Java 版 `OpenAiCompatibleRerankerClient.java`：与 Embedding 客户端不同，Rerank
客户端没有重试逻辑（单次请求失败即抛出），这里重点验证不重试这一点、以及分数排序/
截断逻辑。用 `httpx.MockTransport` 模拟服务端。
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.ragcore.model import Chunk, ModelClientException, RetrievedChunk
from app.ragcore.rerank.openai_compatible import (
    OpenAiCompatibleRerankerClient,
    RerankProperties,
    build_reranker_client,
)


def _chunk(content: str, ordinal: int = 0) -> Chunk:
    return Chunk(
        id=str(uuid4()),
        organization_id=None,
        knowledge_base_id=None,
        document_id=None,
        ordinal=ordinal,
        content=content,
    )


def _candidate(content: str, ordinal: int = 0) -> RetrievedChunk:
    return RetrievedChunk(chunk=_chunk(content, ordinal), bm25_rank=1, vector_rank=1, rrf_score=0.5)


def _properties(**overrides) -> RerankProperties:
    defaults = dict(enabled=True, endpoint="http://model-gateway/rerank", api_key="", model="bge-reranker", timeout_ms=5_000)
    defaults.update(overrides)
    return RerankProperties(**defaults)


def _client_with_handler(handler, **prop_overrides) -> OpenAiCompatibleRerankerClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return OpenAiCompatibleRerankerClient(_properties(**prop_overrides), http_client=http_client)


class TestRerankPropertiesValidation:
    def test_rejects_blank_endpoint(self):
        with pytest.raises(ValueError):
            _properties(endpoint="  ")

    def test_rejects_blank_model(self):
        with pytest.raises(ValueError):
            _properties(model="")

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError):
            _properties(timeout_ms=0)


class TestEmptyInputShortCircuits:
    async def test_blank_query_returns_empty_without_http_call(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"results": []})

        client = _client_with_handler(handler)
        result = await client.rerank("   ", [_candidate("a")], top_k=5)
        assert result == []
        assert calls == []

    async def test_empty_candidates_returns_empty_without_http_call(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"results": []})

        client = _client_with_handler(handler)
        result = await client.rerank("query", [], top_k=5)
        assert result == []
        assert calls == []

    async def test_non_positive_top_k_returns_empty_without_http_call(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"results": []})

        client = _client_with_handler(handler)
        result = await client.rerank("query", [_candidate("a")], top_k=0)
        assert result == []
        assert calls == []


class TestRerankSortingAndTruncation:
    async def test_results_sorted_descending_by_score(self):
        candidates = [_candidate("low", 0), _candidate("high", 1), _candidate("mid", 2)]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 0, "relevance_score": 0.1},
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 2, "relevance_score": 0.5},
                    ]
                },
            )

        client = _client_with_handler(handler)
        result = await client.rerank("q", candidates, top_k=3)
        assert [c.chunk.content for c in result] == ["high", "mid", "low"]
        assert [c.final_score for c in result] == [0.9, 0.5, 0.1]
        assert [c.rerank_score for c in result] == [0.9, 0.5, 0.1]

    async def test_truncates_to_top_k(self):
        candidates = [_candidate("a", 0), _candidate("b", 1), _candidate("c", 2)]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 0, "relevance_score": 0.3},
                        {"index": 1, "relevance_score": 0.7},
                        {"index": 2, "relevance_score": 0.5},
                    ]
                },
            )

        client = _client_with_handler(handler)
        result = await client.rerank("q", candidates, top_k=2)
        assert len(result) == 2
        assert [c.chunk.content for c in result] == ["b", "c"]

    async def test_preserves_bm25_and_vector_rank_from_original_candidate(self):
        candidate = RetrievedChunk(chunk=_chunk("x"), bm25_rank=3, vector_rank=7, rrf_score=0.2)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.8}]})

        client = _client_with_handler(handler)
        result = await client.rerank("q", [candidate], top_k=1)
        assert result[0].bm25_rank == 3
        assert result[0].vector_rank == 7
        assert result[0].rrf_score == 0.2

    async def test_score_field_fallback_when_relevance_score_absent(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": [{"index": 0, "score": 0.42}]})

        client = _client_with_handler(handler)
        result = await client.rerank("q", [_candidate("a")], top_k=1)
        assert result[0].final_score == 0.42

    async def test_request_body_contains_documents_and_top_n(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json={"results": []})

        client = _client_with_handler(handler)
        await client.rerank("我的问题", [_candidate("文档A"), _candidate("文档B")], top_k=5)
        assert captured["body"]["query"] == "我的问题"
        assert captured["body"]["documents"] == ["文档A", "文档B"]
        assert captured["body"]["top_n"] == 5


class TestNoRetryOnFailure:
    """Java 版 Rerank 客户端没有重试逻辑；这是与 Embedding 客户端最重要的行为差异。"""

    async def test_5xx_does_not_retry(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(503, json={"error": "unavailable"})

        client = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await client.rerank("q", [_candidate("a")], top_k=1)
        assert call_count["n"] == 1

    async def test_429_does_not_retry(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(429, json={"error": "rate limited"})

        client = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await client.rerank("q", [_candidate("a")], top_k=1)
        assert call_count["n"] == 1

    async def test_transport_error_raises_model_client_exception(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = _client_with_handler(handler)
        with pytest.raises(ModelClientException):
            await client.rerank("q", [_candidate("a")], top_k=1)


class TestResponseParsingErrors:
    async def test_missing_results_field_raises(self):
        client = _client_with_handler(lambda request: httpx.Response(200, json={"foo": "bar"}))
        with pytest.raises(ModelClientException):
            await client.rerank("q", [_candidate("a")], top_k=1)

    async def test_out_of_range_index_raises(self):
        client = _client_with_handler(
            lambda request: httpx.Response(200, json={"results": [{"index": 5, "relevance_score": 0.5}]})
        )
        with pytest.raises(ModelClientException):
            await client.rerank("q", [_candidate("a")], top_k=1)

    async def test_non_numeric_score_raises(self):
        client = _client_with_handler(
            lambda request: httpx.Response(200, json={"results": [{"index": 0, "relevance_score": "high"}]})
        )
        with pytest.raises(ModelClientException):
            await client.rerank("q", [_candidate("a")], top_k=1)

    async def test_not_json_response_raises(self):
        client = _client_with_handler(lambda request: httpx.Response(200, content=b"not json"))
        with pytest.raises(ModelClientException):
            await client.rerank("q", [_candidate("a")], top_k=1)


class TestBuildRerankerClient:
    def test_disabled_returns_none(self):
        class _Cfg:
            rag_rerank_enabled = False

        assert build_reranker_client(_Cfg()) is None

    def test_enabled_builds_client(self, monkeypatch):
        for var in ("all_proxy", "ALL_PROXY", "http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
            monkeypatch.delenv(var, raising=False)

        class _Cfg:
            rag_rerank_enabled = True
            rag_rerank_endpoint = "http://gw/rerank"
            rag_rerank_api_key = ""
            rag_rerank_model = "bge-reranker"
            rag_rerank_timeout_ms = 5_000

        client = build_reranker_client(_Cfg())
        assert isinstance(client, OpenAiCompatibleRerankerClient)
