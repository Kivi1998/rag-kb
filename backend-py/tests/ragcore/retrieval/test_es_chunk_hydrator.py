"""`ElasticsearchChunkHydrator` 多租户隔离测试。

对应 Java 版 `ragcore/retrieval/ElasticsearchChunkHydrator.java`。
这是 toB 红线三道防御里**最关键**的一道:即便向量库(ES / Milvus)已经带了 org/kb filter,
ChunkHydrator 仍要在自己的 ES 查询里强制注入 org/kb filter 并对回程结果逐条二次校验。
本测试构造跨组织 / 跨知识库 chunk,断言任何越权数据都不会被返回,即使 ES 错误地把
这些数据也吐回来了。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.retrieval.es_chunk_hydrator import ElasticsearchChunkHydrator


def _chunk_source(
    chunk_id: str,
    org_id: UUID,
    kb_id: UUID,
    document_id: UUID | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "chunk_id": chunk_id,
        "org_id": str(org_id),
        "kb_id": str(kb_id),
        "document_id": str(document_id or uuid4()),
        "ordinal": 0,
        "content": f"content of {chunk_id}",
        "heading_path": [],
        "metadata": {},
    }
    base.update(overrides)
    return base


def _make_hits(*sources: dict[str, Any]) -> dict[str, Any]:
    return {"hits": {"hits": [{"_source": s} for s in sources]}}


class _FakeESClient:
    """最小化 ES client,只支持 hydrator 调用 search。记录入参供测试断言。"""

    def __init__(self, response: Any | None = "__DEFAULT", raise_exc: Exception | None = None) -> None:
        # 哨兵区分"未传(用默认空 hits)"与"传 None(模拟 ES 返回 None 响应)"
        if response == "__DEFAULT":
            self.response = _make_hits()
        else:
            self.response = response
        self.raise_exc = raise_exc
        self.last_body: dict[str, Any] | None = None
        self.last_index: str | None = None
        self.call_count = 0

    async def search(self, *, index: str, body: dict[str, Any]) -> Any:
        self.call_count += 1
        self.last_index = index
        self.last_body = body
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response


class TestTenantBoundaryInjection:
    """ChunkHydrator 必须在每次 ES 查询的 bool.filter 注入
    org_id / kb_id / retrieval_ready=true 三条——这是第二道纵深防御,
    即便上游向量库错误把越权数据传进来,这里也必须被挡掉。"""

    @pytest.mark.asyncio
    async def test_org_id_and_kb_id_injected_into_filter(self):
        es = _FakeESClient()
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")

        org_id = uuid4()
        kb_id = uuid4()
        await hydrator.find_by_chunk_ids(org_id, kb_id, ["c-1"])

        filters = es.last_body["query"]["bool"]["filter"]
        term_filters = [f for f in filters if "term" in f]
        # 展开成 {field: value} 平铺字典,便于断言
        flat = {field: conf for f in term_filters for field, conf in f["term"].items()}
        assert flat["org_id"] == str(org_id)
        assert flat["kb_id"] == str(kb_id)
        assert flat["retrieval_ready"] is True

    @pytest.mark.asyncio
    async def test_chunk_ids_injected_into_filter(self):
        es = _FakeESClient()
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")

        await hydrator.find_by_chunk_ids(uuid4(), uuid4(), ["c-1", "c-2", "c-3"])
        filters = es.last_body["query"]["bool"]["filter"]
        terms_filters = [f for f in filters if "terms" in f]
        assert terms_filters, "应该有 terms 过滤命中 chunk_id 列表"
        assert set(terms_filters[0]["terms"]["chunk_id"]) == {"c-1", "c-2", "c-3"}


class TestEmptyAndBoundaryChecks:
    @pytest.mark.asyncio
    async def test_empty_chunk_ids_returns_empty_without_es_call(self):
        es = _FakeESClient()
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")
        result = await hydrator.find_by_chunk_ids(uuid4(), uuid4(), [])
        assert result == []
        assert es.call_count == 0

    @pytest.mark.asyncio
    async def test_blank_chunk_ids_filtered_out(self):
        """空字符串应被去重逻辑过滤——多个空 ID 不应触发 ES 调用;合法 ID
        即使重复也应至少打一次 ES。"""
        es = _FakeESClient()
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")
        # 全是空字符串时,过滤后 ids 为空,不打 ES
        result = await hydrator.find_by_chunk_ids(uuid4(), uuid4(), ["", ""])
        assert result == []
        assert es.call_count == 0

    @pytest.mark.asyncio
    async def test_missing_org_id_rejected(self):
        es = _FakeESClient()
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")
        with pytest.raises(ValueError):
            await hydrator.find_by_chunk_ids(None, uuid4(), ["c-1"])  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_missing_kb_id_rejected(self):
        es = _FakeESClient()
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")
        with pytest.raises(ValueError):
            await hydrator.find_by_chunk_ids(uuid4(), None, ["c-1"])  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_es_failure_wrapped_in_index_exception(self):
        """ES 抛任何异常都被包成 ElasticsearchIndexException,便于上层 fail-open 路径识别。"""
        es = _FakeESClient(raise_exc=RuntimeError("connection lost"))
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")
        with pytest.raises(ElasticsearchIndexException):
            await hydrator.find_by_chunk_ids(uuid4(), uuid4(), ["c-1"])


class TestCrossTenantFiltering:
    """**核心:多租户隔离回归**。构造 ES 错误地返回了跨组织/跨知识库 chunk 的场景,
    hydrator 必须在结果回程时再次过滤,绝不能让越权 chunk 回到 HybridRetriever 手里。"""

    @pytest.mark.asyncio
    async def test_filters_out_chunks_with_wrong_org_id(self):
        """ES 把别的组织的 chunk 也吐回来了——hydrator 必须丢掉。"""
        request_org = uuid4()
        request_kb = uuid4()
        foreign_org = uuid4()  # 别的组织

        # ES 错误返回:同一个 chunk_id 但分属两个不同 org
        foreign_source = _chunk_source("c-1", org_id=foreign_org, kb_id=request_kb)
        own_source = _chunk_source("c-2", org_id=request_org, kb_id=request_kb)
        es = _FakeESClient(_make_hits(foreign_source, own_source))
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")

        result = await hydrator.find_by_chunk_ids(request_org, request_kb, ["c-1", "c-2"])
        # 跨组织的 c-1 必须被过滤掉
        assert [c.id for c in result] == ["c-2"]

    @pytest.mark.asyncio
    async def test_filters_out_chunks_with_wrong_kb_id(self):
        """同 org 但跨知识库——hydrator 必须丢掉。"""
        request_org = uuid4()
        request_kb = uuid4()
        foreign_kb = uuid4()  # 同 org 内的另一个知识库

        cross_kb_source = _chunk_source("c-1", org_id=request_org, kb_id=foreign_kb)
        own_source = _chunk_source("c-2", org_id=request_org, kb_id=request_kb)
        es = _FakeESClient(_make_hits(cross_kb_source, own_source))
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")

        result = await hydrator.find_by_chunk_ids(request_org, request_kb, ["c-1", "c-2"])
        assert [c.id for c in result] == ["c-2"]

    @pytest.mark.asyncio
    async def test_all_cross_tenant_returns_empty(self):
        request_org = uuid4()
        request_kb = uuid4()
        foreign = uuid4()

        es = _FakeESClient(_make_hits(
            _chunk_source("c-1", org_id=foreign, kb_id=foreign),
            _chunk_source("c-2", org_id=foreign, kb_id=foreign),
        ))
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")
        result = await hydrator.find_by_chunk_ids(request_org, request_kb, ["c-1", "c-2"])
        assert result == []

    @pytest.mark.asyncio
    async def test_malformed_source_skipped_not_raised(self):
        """单条 _source 缺字段时,该条跳过;其他合法 chunk 仍要正确返回。"""
        request_org = uuid4()
        request_kb = uuid4()

        malformed = {"chunk_id": "bad", "org_id": str(request_org), "kb_id": str(request_kb)}  # 缺 document_id/ordinal/content
        good = _chunk_source("good", request_org, request_kb)
        es = _FakeESClient(_make_hits(malformed, good))
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")
        result = await hydrator.find_by_chunk_ids(request_org, request_kb, ["bad", "good"])
        assert [c.id for c in result] == ["good"]


class TestInputOrderPreserved:
    """返回列表必须按输入 ID 顺序,HybridRetriever 据此按向量排名重组。"""

    @pytest.mark.asyncio
    async def test_returns_in_input_id_order_not_es_order(self):
        request_org = uuid4()
        request_kb = uuid4()

        # ES 返回顺序与请求顺序相反
        es = _FakeESClient(_make_hits(
            _chunk_source("c-second", request_org, request_kb),
            _chunk_source("c-first", request_org, request_kb),
            _chunk_source("c-third", request_org, request_kb),
        ))
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")
        result = await hydrator.find_by_chunk_ids(
            request_org, request_kb, ["c-first", "c-second", "c-third"]
        )
        assert [c.id for c in result] == ["c-first", "c-second", "c-third"]

    @pytest.mark.asyncio
    async def test_unfound_ids_skipped(self):
        """ES 找不到的 chunk_id 直接略过,HybridRetriever 把它计入"孤儿指标"——而不是补 None。"""
        request_org = uuid4()
        request_kb = uuid4()
        es = _FakeESClient(_make_hits(_chunk_source("c-1", request_org, request_kb)))
        hydrator = ElasticsearchChunkHydrator(es_client=es, index_name="rag_chunks_v1")
        result = await hydrator.find_by_chunk_ids(
            request_org, request_kb, ["c-1", "c-missing", "c-not-in-es"]
        )
        assert [c.id for c in result] == ["c-1"]
