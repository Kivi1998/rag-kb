"""`ElasticsearchLexicalCandidateSource` 多租户 + BM25 字段权重测试。

对应 Java 版 `ragcore/retrieval/ElasticsearchLexicalCandidateSource.java`。
校验词法候选源必须把 org/kb 过滤作为硬性 bool.filter 注入,symbol_names / config_keys
/ error_codes / content_search 的 boost 权重与 Java 版完全一致;document_ids 非空
时叠加 document_id 范围过滤;非法响应(缺 hits.hits)必须显式失败,而不是吞掉。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.index.search_request import SearchRequest
from app.ragcore.retrieval.es_lexical_candidate_source import ElasticsearchLexicalCandidateSource


def _chunk_source(chunk_id: str, org: UUID, kb: UUID, document: UUID | None = None) -> dict:
    return {
        "chunk_id": chunk_id,
        "org_id": str(org),
        "kb_id": str(kb),
        "document_id": str(document or uuid4()),
        "ordinal": 0,
        "content": "x",
    }


def _make_hits(*sources: dict, scores: list[float] | None = None) -> dict[str, Any]:
    if scores is None:
        scores = [1.0] * len(sources)
    return {
        "hits": {
            "hits": [
                {"_source": s, "_score": score}
                for s, score in zip(sources, scores)
            ]
        }
    }


class _FakeESClient:
    def __init__(self, response: Any | None = "__DEFAULT", raise_exc: Exception | None = None) -> None:
        # 哨兵区分"未传(用默认空 hits)"与"传 None(模拟 ES 返回 None 响应)"
        if response == "__DEFAULT":
            self.response = _make_hits()
        else:
            self.response = response
        self.raise_exc = raise_exc
        self.last_body: dict[str, Any] | None = None
        self.call_count = 0

    async def search(self, *, index: str, body: dict[str, Any]) -> Any:
        self.call_count += 1
        self.last_body = body
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response


def _make_source() -> ElasticsearchLexicalCandidateSource:
    return ElasticsearchLexicalCandidateSource(es_client=_FakeESClient(), index_name="rag_chunks_v1")


def _request(**overrides) -> SearchRequest:
    base = dict(
        organization_id=uuid4(),
        knowledge_base_id=uuid4(),
        query="NullPointerException",
        top_k=10,
        document_ids=(),
    )
    base.update(overrides)
    return SearchRequest(**base)


class TestQueryFilterInjection:
    """bool.filter 必须含 org_id + kb_id + retrieval_ready=true;调用方
    不再二次注入,这是 toB 第二道纵深防御。"""

    @pytest.mark.asyncio
    async def test_org_id_and_kb_id_in_filter(self):
        es = _FakeESClient()
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")

        org_id = uuid4()
        kb_id = uuid4()
        await source.search(
            SearchRequest(organization_id=org_id, knowledge_base_id=kb_id, query="x", top_k=10)
        )

        filters = es.last_body["query"]["bool"]["filter"]
        term_filters = [f for f in filters if "term" in f]
        flat = {field: conf for f in term_filters for field, conf in f["term"].items()}
        assert flat["org_id"] == str(org_id)
        assert flat["kb_id"] == str(kb_id)
        assert flat["retrieval_ready"] is True

    @pytest.mark.asyncio
    async def test_document_ids_inject_terms_filter(self):
        """document_ids 非空时必须叠加 document_id 范围过滤,与 ES bool.filter 风格一致。"""
        es = _FakeESClient()
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        doc_id = uuid4()
        await source.search(
            SearchRequest(
                organization_id=uuid4(),
                knowledge_base_id=uuid4(),
                query="x",
                top_k=10,
                document_ids=(doc_id,),
            )
        )
        filters = es.last_body["query"]["bool"]["filter"]
        terms_filters = [f for f in filters if "terms" in f]
        assert any(
            f["terms"].get("document_id") == [str(doc_id)] for f in terms_filters
        ), "document_ids 非空时应叠加 document_id terms 过滤"

    @pytest.mark.asyncio
    async def test_empty_document_ids_skips_terms_filter(self):
        es = _FakeESClient()
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        await source.search(_request())
        filters = es.last_body["query"]["bool"]["filter"]
        assert not any("terms" in f and "document_id" in f.get("terms", {}) for f in filters)


class TestBoostWeights:
    """symbol_names(8)/config_keys(7)/error_codes(7)/content_search(1) 的 boost 数值
    与 Java 版必须逐一对齐——这是跨语言评估集契约,改了就破坏中文 vs 错误码权重平衡。"""

    @pytest.mark.asyncio
    async def test_should_clauses_boosts_match_java(self):
        es = _FakeESClient()
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        await source.search(_request())
        shoulds = es.last_body["query"]["bool"]["should"]
        boosts = {}
        for s in shoulds:
            # s 形如 {"term": {"symbol_names": {"value": q, "boost": 8}}}
            # 或 {"match": {"content_search": {"query": q, "boost": 1}}}
            for op_type, op_conf in s.items():
                for field, conf in op_conf.items():
                    boosts[field] = conf.get("boost")
        assert boosts["symbol_names"] == 8
        assert boosts["config_keys"] == 7
        assert boosts["error_codes"] == 7
        assert boosts["content_search"] == 1

    @pytest.mark.asyncio
    async def test_minimum_should_match_is_1(self):
        """minimum_should_match=1 是 BM25 走 OR 逻辑的标志;改成 0 会让零命中也有结果。"""
        es = _FakeESClient()
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        await source.search(_request())
        assert es.last_body["query"]["bool"]["minimum_should_match"] == 1

    @pytest.mark.asyncio
    async def test_query_text_appears_in_term_clauses(self):
        es = _FakeESClient()
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        await source.search(_request(query="NullPointerException"))
        shoulds = es.last_body["query"]["bool"]["should"]
        for clause in shoulds:
            if "term" in clause:
                values = list(clause["term"].values())
                if isinstance(values[0], dict) and "value" in values[0]:
                    assert values[0]["value"] == "NullPointerException"


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_without_es_call(self):
        """空 query 是上游 HybriRetriever 早退过的合法输入,这里不能再发 ES 请求。"""
        es = _FakeESClient()
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        result = await source.search(_request(query=""))
        assert result == []
        assert es.call_count == 0

    @pytest.mark.asyncio
    async def test_blank_query_returns_empty_without_es_call(self):
        es = _FakeESClient()
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        result = await source.search(_request(query="   \n"))
        assert result == []
        assert es.call_count == 0

    @pytest.mark.asyncio
    async def test_missing_org_id_rejected(self):
        with pytest.raises(ValueError):
            await _make_source().search(
                SearchRequest(
                    organization_id=None,  # type: ignore[arg-type]
                    knowledge_base_id=uuid4(),
                    query="x",
                    top_k=10,
                )
            )

    @pytest.mark.asyncio
    async def test_missing_kb_id_rejected(self):
        with pytest.raises(ValueError):
            await _make_source().search(
                SearchRequest(
                    organization_id=uuid4(),
                    knowledge_base_id=None,  # type: ignore[arg-type]
                    query="x",
                    top_k=10,
                )
            )


class TestResponseParsingAndCrossTenant:
    @pytest.mark.asyncio
    async def test_response_without_hits_hits_raises(self):
        es = _FakeESClient(response={"hits": {}})  # 没有 hits.hits
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        with pytest.raises(ElasticsearchIndexException):
            await source.search(_request())

    @pytest.mark.asyncio
    async def test_es_exception_wrapped(self):
        es = _FakeESClient(raise_exc=RuntimeError("network blip"))
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        with pytest.raises(ElasticsearchIndexException):
            await source.search(_request())

    @pytest.mark.asyncio
    async def test_none_response_raises(self):
        es = _FakeESClient(response=None)
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        with pytest.raises(ElasticsearchIndexException):
            await source.search(_request())

    @pytest.mark.asyncio
    async def test_top_k_propagated_to_es_size(self):
        es = _FakeESClient()
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        await source.search(_request(top_k=42))
        assert es.last_body["size"] == 42

    @pytest.mark.asyncio
    async def test_chunks_ranked_by_es_order_with_bm25_rank(self):
        """BM25 路径下,bm25_rank 必须是 ES 返回的 rank(从 1 开始)。"""
        org = uuid4()
        kb = uuid4()
        es = _FakeESClient(_make_hits(
            _chunk_source("c-a", org, kb),
            _chunk_source("c-b", org, kb),
            _chunk_source("c-c", org, kb),
            scores=[0.9, 0.7, 0.5],
        ))
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        result = await source.search(_request(organization_id=org, knowledge_base_id=kb))
        assert [c.chunk.id for c in result] == ["c-a", "c-b", "c-c"]
        assert [c.bm25_rank for c in result] == [1, 2, 3]
        assert [c.vector_rank for c in result] == [None, None, None]
        assert result[0].final_score == 0.9

    @pytest.mark.asyncio
    async def test_skips_malformed_hit(self):
        """单条 _source 缺字段,跳过该 rank,后续 rank 仍按 ES 原顺序(不要把"跳过"算成 gap)。"""
        org = uuid4()
        kb = uuid4()
        malformed = {"chunk_id": "broken", "org_id": str(org)}  # 缺 kb_id/document_id
        good = _chunk_source("good", org, kb)
        es = _FakeESClient(_make_hits(malformed, good))
        source = ElasticsearchLexicalCandidateSource(es_client=es, index_name="rag_chunks_v1")
        result = await source.search(_request(organization_id=org, knowledge_base_id=kb))
        # good 在 ES 返回里就是 rank=2,这里透传 bm25_rank=2 而非 1(避免下游误判 top-1)
        assert [c.chunk.id for c in result] == ["good"]
        assert result[0].bm25_rank == 2
