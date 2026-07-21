"""`ElasticsearchVectorCandidateSource` 多租户 + kNN 查询参数测试。

对应 Java 版 `ragcore/retrieval/ElasticsearchVectorCandidateSource.java`。
锁住 kNN 查询的 filter 注入(同样有 org/kb/retrieval_ready 三条),
查询向量维度校验,document_ids 范围过滤;ES kNN 错误响应必须显式抛
ElasticsearchIndexException(不静默吃)。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.retrieval.es_vector_candidate_source import ElasticsearchVectorCandidateSource
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest


def _hits(*pairs: tuple[str, float]) -> dict[str, Any]:
    return {
        "hits": {
            "hits": [
                {"_source": {"chunk_id": cid}, "_score": score} for cid, score in pairs
            ]
        }
    }


class _FakeESClient:
    def __init__(self, response: Any | None = "<DEFAULT", raise_exc: Exception | None = None) -> None:
        # 哨兵字符串区分"未传(用默认空 hits)"与"传 None(模拟 ES 返回 None 响应)"
        if response == "<DEFAULT":
            self.response = _hits()
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


def _make_source(es: _FakeESClient, dimensions: int = 4) -> ElasticsearchVectorCandidateSource:
    return ElasticsearchVectorCandidateSource(
        es_client=es, index_name="rag_chunks_v1", vector_dimensions=dimensions
    )


def _request(dimensions: int = 4, **overrides) -> VectorSearchRequest:
    base = dict(
        organization_id=uuid4(),
        knowledge_base_id=uuid4(),
        query_vector=[0.1] * dimensions,
        top_k=5,
        document_ids=(),
    )
    base.update(overrides)
    return VectorSearchRequest(**base)


class TestKnnFilterInjection:
    @pytest.mark.asyncio
    async def test_org_id_kb_id_retrieval_ready_in_knn_filter(self):
        es = _FakeESClient()
        source = _make_source(es)
        org_id = uuid4()
        kb_id = uuid4()
        await source.search(
            VectorSearchRequest(
                organization_id=org_id,
                knowledge_base_id=kb_id,
                query_vector=[0.1, 0.2, 0.3, 0.4],
                top_k=5,
            )
        )
        knn = es.last_body["knn"]
        filters = knn["filter"]
        terms = {next(iter(f["term"])): f["term"][next(iter(f["term"]))] for f in filters if "term" in f}
        assert terms["org_id"] == str(org_id)
        assert terms["kb_id"] == str(kb_id)
        assert terms["retrieval_ready"] is True

    @pytest.mark.asyncio
    async def test_document_ids_inject_terms_filter(self):
        es = _FakeESClient()
        source = _make_source(es)
        doc_id = uuid4()
        await source.search(_request(document_ids=(doc_id,)))
        knn = es.last_body["knn"]
        terms_filters = [f for f in knn["filter"] if "terms" in f]
        assert any(f["terms"].get("document_id") == [str(doc_id)] for f in terms_filters)

    @pytest.mark.asyncio
    async def test_num_candidates_at_least_three_times_top_k(self):
        """num_candidates >= 3*top_k 是 ES HNSW 召回率与时延的平衡点。"""
        es = _FakeESClient()
        source = _make_source(es)
        await source.search(_request(top_k=10))
        assert es.last_body["knn"]["num_candidates"] >= 30
        assert es.last_body["knn"]["num_candidates"] >= 100  # 文档里写的下限

    @pytest.mark.asyncio
    async def test_field_is_content_vector(self):
        """ES 索引的 kNN 字段名是 content_vector;Hydrator 维护 mapping 决定了这个名称,
        改了就破坏 HNSW 召回路径。"""
        es = _FakeESClient()
        source = _make_source(es)
        await source.search(_request())
        assert es.last_body["knn"]["field"] == "content_vector"

    @pytest.mark.asyncio
    async def test_source_filtered_to_chunk_id_only(self):
        """_source 只取 chunk_id 字段,正文走 ChunkHydrator 补齐——避免 ES 投影字段漂移。"""
        es = _FakeESClient()
        source = _make_source(es)
        await source.search(_request())
        assert es.last_body["_source"] == ["chunk_id"]


class TestDimensionValidation:
    @pytest.mark.asyncio
    async def test_wrong_dimension_rejected(self):
        """维度校验失败必须 fail-fast,绝不能让 ES 接到维度不匹配的向量。"""
        es = _FakeESClient()
        source = _make_source(es, dimensions=4)
        with pytest.raises(ValueError):
            await source.search(
                VectorSearchRequest(
                    organization_id=uuid4(),
                    knowledge_base_id=uuid4(),
                    query_vector=[0.1, 0.2, 0.3],  # 只有 3 维
                    top_k=5,
                )
            )

    @pytest.mark.asyncio
    async def test_correct_dimension_accepted(self):
        es = _FakeESClient()
        source = _make_source(es, dimensions=4)
        await source.search(_request(dimensions=4))
        assert es.call_count == 1


class TestBoundaryAndErrorHandling:
    @pytest.mark.asyncio
    async def test_missing_org_id_rejected(self):
        es = _FakeESClient()
        source = _make_source(es)
        with pytest.raises(ValueError):
            await source.search(
                VectorSearchRequest(
                    organization_id=None,  # type: ignore[arg-type]
                    knowledge_base_id=uuid4(),
                    query_vector=[0.1, 0.2, 0.3, 0.4],
                    top_k=5,
                )
            )

    @pytest.mark.asyncio
    async def test_missing_kb_id_rejected(self):
        es = _FakeESClient()
        source = _make_source(es)
        with pytest.raises(ValueError):
            await source.search(
                VectorSearchRequest(
                    organization_id=uuid4(),
                    knowledge_base_id=None,  # type: ignore[arg-type]
                    query_vector=[0.1, 0.2, 0.3, 0.4],
                    top_k=5,
                )
            )

    @pytest.mark.asyncio
    async def test_es_exception_wrapped(self):
        es = _FakeESClient(raise_exc=RuntimeError("oops"))
        source = _make_source(es)
        with pytest.raises(ElasticsearchIndexException):
            await source.search(_request())

    @pytest.mark.asyncio
    async def test_response_without_hits_hits_raises(self):
        es = _FakeESClient(response={"hits": {}})
        source = _make_source(es)
        with pytest.raises(ElasticsearchIndexException):
            await source.search(_request())

    @pytest.mark.asyncio
    async def test_none_response_raises(self):
        es = _FakeESClient(response=None)
        source = _make_source(es)
        with pytest.raises(ElasticsearchIndexException):
            await source.search(_request())


class TestHitConversion:
    @pytest.mark.asyncio
    async def test_hits_converted_to_vector_hits_in_es_rank_order(self):
        es = _FakeESClient(_hits(("c-1", 0.95), ("c-2", 0.85), ("c-3", 0.75)))
        source = _make_source(es)
        result = await source.search(_request())
        assert [h.chunk_id for h in result] == ["c-1", "c-2", "c-3"]
        assert [h.rank for h in result] == [1, 2, 3]
        assert [h.score for h in result] == [0.95, 0.85, 0.75]

    @pytest.mark.asyncio
    async def test_hit_without_chunk_id_skipped(self):
        """单条 hit 缺 chunk_id 时跳过,不抛错;rank 由剩余 hit 顺序补齐。"""
        es = _FakeESClient(
            response={
                "hits": {
                    "hits": [
                        {"_source": {"chunk_id": "c-1"}, "_score": 0.9},
                        {"_source": {}, "_score": 0.8},  # 缺 chunk_id
                        {"_source": {"chunk_id": "c-2"}, "_score": 0.7},
                    ]
                }
            }
        )
        source = _make_source(es)
        result = await source.search(_request())
        # rank 应该是 ES 原始顺序(让 HybridRetriever 知道 c-2 原本排第 3)
        assert [h.chunk_id for h in result] == ["c-1", "c-2"]
        assert [h.rank for h in result] == [1, 3]
