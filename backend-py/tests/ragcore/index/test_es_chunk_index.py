"""`ElasticsearchChunkIndex` 多租户保护与 lifecycle 测试。

对应 Java 版 `ragcore/index/ElasticsearchChunkIndex.java`。
关键保护:
- `search()` 永远抛 NotImplementedError——混合检索必须走 HybridRetriever
- `delete_by_document_id` / `activate_document` / `deactivate_document` 都强制
  org_id + kb_id + document_id 三键,缺一不可
- `upsert` 是 stage + activate 的合并快捷路径
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.ragcore.index.es_chunk_index import ElasticsearchChunkIndex
from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.model import Chunk


def _settings(**overrides) -> Settings:
    defaults = dict(
        rag_es_index_name="rag_chunks_v1",
        rag_es_vector_dimensions=4,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _chunk(
    chunk_id: str = "c-1",
    org: UUID | None = None,
    kb: UUID | None = None,
    doc: UUID | None = None,
) -> Chunk:
    return Chunk(
        id=chunk_id,
        organization_id=org or uuid4(),
        knowledge_base_id=kb or uuid4(),
        document_id=doc or uuid4(),
        ordinal=0,
        content="content",
    )


class _FakeESClient:
    def __init__(self) -> None:
        self.bulk_calls: list[dict] = []
        self.delete_by_query_calls: list[dict] = []
        self.update_by_query_calls: list[dict] = []
        self.exists_response: bool = True
        self.create_called: int = 0
        self.put_mapping_called: int = 0

        # 模拟 es.indices.exists(...) 的链式属性访问
        self.indices = self._Indices(self)

    class _Indices:
        def __init__(self, parent: "_FakeESClient") -> None:
            self._parent = parent

        async def exists(self, *, index: str) -> bool:
            return self._parent.exists_response

        async def create(self, *, index: str, mappings: dict) -> dict:
            self._parent.create_called += 1
            return {"acknowledged": True}

        async def put_mapping(self, *, index: str, properties: dict) -> dict:
            self._parent.put_mapping_called += 1
            return {"acknowledged": True}

    async def bulk(self, *, index: str, operations: list) -> dict:
        self.bulk_calls.append({"index": index, "operations": operations})
        return {"errors": False, "items": []}

    async def delete_by_query(self, *, index: str, query: dict, **kwargs) -> dict:
        self.delete_by_query_calls.append({"index": index, "query": query, **kwargs})
        return {"deleted": 0}

    async def update_by_query(self, *, index: str, query: dict, script: dict = None, **kwargs) -> dict:
        self.update_by_query_calls.append({"index": index, "query": query, "script": script, **kwargs})
        return {"updated": 0}


class TestSearchIsForbidden:
    @pytest.mark.asyncio
    async def test_search_raises_not_implemented(self):
        """混合检索必须走 HybridRetriever;这个无租户过滤保护的 search() 必须禁掉。"""
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        from app.ragcore.index.search_request import SearchRequest

        with pytest.raises(NotImplementedError):
            await index.search(
                SearchRequest(organization_id=uuid4(), knowledge_base_id=uuid4(), query="x", top_k=10)
            )


class TestUpsert:
    @pytest.mark.asyncio
    async def test_empty_chunks_no_op(self):
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        await index.upsert([], [], "model-v1")
        assert es.bulk_calls == []
        assert es.update_by_query_calls == []

    @pytest.mark.asyncio
    async def test_chunks_and_vectors_must_align(self):
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        chunk = _chunk()
        with pytest.raises(ValueError):
            await index.upsert([chunk], [], "model-v1")

    @pytest.mark.asyncio
    async def test_vector_dim_must_match(self):
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings(rag_es_vector_dimensions=4))
        chunk = _chunk()
        with pytest.raises(ValueError):
            await index.upsert([chunk], [[0.1, 0.2]], "model-v1")  # 只有 2 维

    @pytest.mark.asyncio
    async def test_bulk_errors_raise(self):
        es = _FakeESClient()
        es.bulk = lambda **kw: (_ for _ in ()).throw(RuntimeError("ES 5xx"))
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        chunk = _chunk()
        with pytest.raises(ElasticsearchIndexException):
            await index.upsert([chunk], [[0.1, 0.2, 0.3, 0.4]], "model-v1")

    @pytest.mark.asyncio
    async def test_partial_bulk_errors_raise(self):
        """bulk 返回 errors=True 时也要抛,不能吞掉。"""
        es = _FakeESClient()
        # 默认 bulk 改成返回 errors
        async def fake_bulk(**kw):
            return {
                "errors": True,
                "items": [{"index": {"error": {"reason": "mapping conflict"}}}],
            }

        es.bulk = fake_bulk
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        chunk = _chunk()
        with pytest.raises(ElasticsearchIndexException):
            await index.upsert([chunk], [[0.1, 0.2, 0.3, 0.4]], "model-v1")


class TestDeleteByDocumentId:
    @pytest.mark.asyncio
    async def test_filter_includes_org_kb_document(self):
        """delete_by_document_id 必须强制三个键,任一缺失的 chunk 不会被误删。"""
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())

        org = uuid4()
        kb = uuid4()
        doc = uuid4()
        await index.delete_by_document_id(org, kb, doc)

        call = es.delete_by_query_calls[0]
        filters = call["query"]["bool"]["filter"]
        flat = {field: conf for f in filters for field, conf in f["term"].items()}
        assert flat["org_id"] == str(org)
        assert flat["kb_id"] == str(kb)
        assert flat["document_id"] == str(doc)

    @pytest.mark.asyncio
    async def test_missing_org_id_raises(self):
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        with pytest.raises(ValueError):
            await index.delete_by_document_id(None, uuid4(), uuid4())  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_missing_kb_id_raises(self):
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        with pytest.raises(ValueError):
            await index.delete_by_document_id(uuid4(), None, uuid4())  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_missing_document_id_raises(self):
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        with pytest.raises(ValueError):
            await index.delete_by_document_id(uuid4(), uuid4(), None)  # type: ignore[arg-type]


class TestVisibilityToggle:
    @pytest.mark.asyncio
    async def test_activate_document_uses_painless_script(self):
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        org, kb, doc = uuid4(), uuid4(), uuid4()
        await index.activate_document(org, kb, doc)
        assert len(es.update_by_query_calls) == 1
        call = es.update_by_query_calls[0]
        assert call["script"]["params"]["ready"] is True
        filters = call["query"]["bool"]["filter"]
        flat = {field: conf for f in filters for field, conf in f["term"].items()}
        assert flat["org_id"] == str(org)
        assert flat["kb_id"] == str(kb)
        assert flat["document_id"] == str(doc)

    @pytest.mark.asyncio
    async def test_deactivate_document_uses_painless_script(self):
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        org, kb, doc = uuid4(), uuid4(), uuid4()
        await index.deactivate_document(org, kb, doc)
        assert len(es.update_by_query_calls) == 1
        assert es.update_by_query_calls[0]["script"]["params"]["ready"] is False

    @pytest.mark.asyncio
    async def test_missing_ids_raises_for_visibility_toggle(self):
        es = _FakeESClient()
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        with pytest.raises(ValueError):
            await index.activate_document(None, uuid4(), uuid4())  # type: ignore[arg-type]


class TestEnsureIndex:
    @pytest.mark.asyncio
    async def test_creates_index_when_missing(self):
        es = _FakeESClient()
        es.exists_response = False
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        await index.ensure_index()
        assert es.create_called == 1

    @pytest.mark.asyncio
    async def test_skips_creation_when_exists(self):
        es = _FakeESClient()
        es.exists_response = True
        index = ElasticsearchChunkIndex(es_client=es, cfg=_settings())
        await index.ensure_index()
        assert es.create_called == 0
