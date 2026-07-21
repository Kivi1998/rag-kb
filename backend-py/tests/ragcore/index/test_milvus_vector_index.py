"""`MilvusVectorIndex.setVisibility` 分页回归测试(2026-07-18 修复的 HIGH 级别 bug)。

**这是本测试套件中最重要的回归测试**。

对照 Java 版 `ragcore/index/MilvusVectorIndex.java`。

历史教训(模块 docstring):`setVisibility()` 曾经用单次 `QueryReq(limit=16384)` 拉取文档下
全部待翻转可见性的 chunk_id,超过该上限的文档只会处理第一页,尾部 chunk 静默停留在旧的
`retrieval_ready` 状态——删除场景下表现为已删除文档的部分内容仍可被检索到。

修复后行为:`_query_all_chunk_ids()` 必须始终按 offset 翻页查询直到拿到不足一页的结果
为止,不能只信任单次 limit 查询就代表"全部"。

本测试构造 **超过一页(16384)** 的数据量场景,断言:
1. activate_document 全部 chunk 都被翻转 retrieval_ready=True
2. deactivate_document 全部 chunk 都被翻转 retrieval_ready=False
3. delete_by_document_id 触发时所有 chunk 都被 delete
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ragcore.index.exceptions import MilvusVectorException
from app.ragcore.index.milvus_vector_index import (
    MilvusVectorIndex,
    _VISIBILITY_QUERY_PAGE_SIZE,
)
from app.ragcore.model import Chunk


class _FakeMilvusClient:
    """模拟 pymilvus MilvusClient,只覆盖 setVisibility/delete 路径用到的 API。

    关键:必须真实地按 offset 翻页——单次 `query(..., offset=N, limit=16384)` 只
    返回一页;下一 offset=N+16384,直到不足一页。"""

    def __init__(self) -> None:
        # chunk_id 列表,模拟一个文档下所有 chunk
        self._chunks: list[str] = []
        # 状态:retrieval_ready 默认 False
        self._state: dict[str, bool] = {}
        # 调用记录
        self.query_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    def seed(self, chunk_ids: list[str]) -> None:
        """注入大量 chunk,所有 retrieval_ready 默认 False(stage() 后的状态)。"""
        self._chunks = list(chunk_ids)
        for cid in chunk_ids:
            self._state[cid] = False

    def has_collection(self, **kwargs) -> bool:
        return True

    def load_collection(self, **kwargs) -> None:
        return None

    def query(self, **kwargs) -> list[dict[str, Any]]:
        """按 offset + limit 翻页模拟 Milvus query 行为,记录每次调用的 filter_params/offset/limit。"""
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", _VISIBILITY_QUERY_PAGE_SIZE)
        self.query_calls.append({
            "offset": offset,
            "limit": limit,
            "filter_params": kwargs.get("filter_params"),
        })
        page = self._chunks[offset : offset + limit]
        return [{MilvusVectorIndex.__class__.__module__ and "chunk_id": cid} for cid in page]

    def upsert(self, **kwargs) -> Any:
        """记录 partial_update 写入,同步更新 self._state。"""
        data = kwargs.get("data", [])
        self.upsert_calls.append({
            "data": data,
            "partial_update": kwargs.get("partial_update", False),
        })
        for row in data:
            cid = row.get("chunk_id")
            if cid is not None and "retrieval_ready" in row:
                self._state[cid] = row["retrieval_ready"]
        return None

    def delete(self, **kwargs) -> Any:
        self.delete_calls.append({
            "filter": kwargs.get("filter"),
            "filter_params": kwargs.get("filter_params"),
        })
        # 模拟 Milvus 按 filter 删除
        params = kwargs.get("filter_params", {})
        target_doc = params.get("document_id")
        before = len(self._chunks)
        self._chunks = [
            c for c in self._chunks
            if target_doc not in c or self._state.get(c) is None
        ]
        return {"deleted": before - len(self._chunks)}


def _build_chunk(chunk_id: str, org_id: UUID, kb_id: UUID, document_id: UUID) -> Chunk:
    return Chunk(
        id=chunk_id,
        organization_id=org_id,
        knowledge_base_id=kb_id,
        document_id=document_id,
        ordinal=0,
        content="x",
    )


def _base_settings(**overrides):
    from app.core.config import Settings

    defaults = dict(
        rag_milvus_database="default",
        rag_milvus_collection="rag_chunks_vector_v1",
        rag_milvus_vector_dimensions=1024,
        rag_milvus_rpc_timeout_ms=3000,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _query_chunk_id_key() -> str:
    return "chunk_id"


def _patch_query_to_return_chunks(monkeypatch, client: _FakeMilvusClient):
    """让 _query_all_chunk_ids 的 query 调用真实地按 _chunks 翻页,而不是依赖 .query() 模拟。"""
    # 调整 _FakeMilvusClient 的 query() 行为以匹配真实 Milvus 响应形状
    original_query = client.query

    def patched_query(**kwargs):
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", _VISIBILITY_QUERY_PAGE_SIZE)
        client.query_calls.append({
            "offset": offset,
            "limit": limit,
            "filter_params": kwargs.get("filter_params"),
        })
        page = client._chunks[offset : offset + limit]
        return [{"chunk_id": cid} for cid in page]

    client.query = patched_query


class TestPageSizeConstant:
    def test_visibility_query_page_size_is_16384(self):
        """单页上限 16384 与 Java 版一致;改这个值会破坏和 Milvus 服务的协议一致性。"""
        assert _VISIBILITY_QUERY_PAGE_SIZE == 16384


class TestActivateDocumentPaginationRegression:
    """**HIGH 级别 bug 回归**:activate_document 必须翻页处理所有 chunk,
    不能只处理第一页就退出。这是 2026-07-18 修复的真实缺陷。"""

    @pytest.mark.asyncio
    async def test_activate_all_chunks_when_count_exceeds_one_page(self):
        """构造 20_000 个 chunk(超过 16_384 的单页上限),activate_document
        必须全部翻成 retrieval_ready=True,不能只处理前 16_384 个。"""
        client = _FakeMilvusClient()
        org_id = uuid4()
        kb_id = uuid4()
        document_id = uuid4()
        all_chunks = [f"chunk-{i:06d}" for i in range(20_000)]
        client.seed(all_chunks)
        _patch_query_to_return_chunks(None, client)  # 不需要 monkeypatch,我们的 query 已经是了

        index = MilvusVectorIndex(client, cfg=_base_settings(rag_milvus_vector_dimensions=1024))
        await index.activate_document(org_id, kb_id, document_id)

        # 校验:全部 20_000 个 chunk 都被翻成 True
        assert all(client._state[cid] is True for cid in all_chunks)
        # 校验:翻页确实发生了——offset 不止 0
        offsets = [call["offset"] for call in client.query_calls]
        assert 0 in offsets
        # 至少要翻到第二个 offset(否则只处理了第一页 = 16_384 条,bug 复现)
        assert max(offsets) >= _VISIBILITY_QUERY_PAGE_SIZE, (
            f"必须翻页到第二个 offset,但实际只查到 offsets={offsets[:5]}..."
        )
        # 翻页次数 = ceil(20_000/16_384) = 2
        assert len(client.query_calls) == 2

    @pytest.mark.asyncio
    async def test_activate_exactly_one_page_size(self):
        """恰好 16_384 个 chunk(等于单页上限)——也是 2 次 query(第二页返回 0 条提前结束)。
        不能再用 ceil(N/P) <= N/P+1 的偷懒实现。"""
        client = _FakeMilvusClient()
        org_id = uuid4()
        kb_id = uuid4()
        document_id = uuid4()
        all_chunks = [f"chunk-{i:06d}" for i in range(_VISIBILITY_QUERY_PAGE_SIZE)]
        client.seed(all_chunks)
        _patch_query_to_return_chunks(None, client)

        index = MilvusVectorIndex(client, cfg=_base_settings())
        await index.activate_document(org_id, kb_id, document_id)

        assert all(client._state[cid] is True for cid in all_chunks)
        # 第一页恰好满,第二页查 0 条后停止
        assert len(client.query_calls) == 2

    @pytest.mark.asyncio
    async def test_activate_no_chunks_skips_upsert(self):
        """文档下没有 chunk 时,setVisibility 应直接跳过,不发 upsert。"""
        client = _FakeMilvusClient()
        org_id = uuid4()
        kb_id = uuid4()
        document_id = uuid4()
        # _chunks 是空的
        _patch_query_to_return_chunks(None, client)

        index = MilvusVectorIndex(client, cfg=_base_settings())
        await index.activate_document(org_id, kb_id, document_id)

        assert client.upsert_calls == []


class TestDeactivateDocumentPaginationRegression:
    """`deactivate_document` 同样必须翻页——删除前置步骤,把 retrieval_ready
    翻成 False(过滤阶段 `retrieval_ready=true` 不会再命中)。bug 复现场景:
    大文档只翻了第一页,后半部分 chunk 仍可被检索到。"""

    @pytest.mark.asyncio
    async def test_deactivate_all_chunks_when_count_exceeds_one_page(self):
        client = _FakeMilvusClient()
        org_id = uuid4()
        kb_id = uuid4()
        document_id = uuid4()
        all_chunks = [f"chunk-{i:06d}" for i in range(20_000)]
        client.seed(all_chunks)
        # 模拟已激活状态
        for cid in all_chunks:
            client._state[cid] = True
        _patch_query_to_return_chunks(None, client)

        index = MilvusVectorIndex(client, cfg=_base_settings())
        await index.deactivate_document(org_id, kb_id, document_id)

        assert all(client._state[cid] is False for cid in all_chunks)
        offsets = [call["offset"] for call in client.query_calls]
        assert max(offsets) >= _VISIBILITY_QUERY_PAGE_SIZE, "deactivate 也必须翻页"


class TestDeleteByDocumentId:
    @pytest.mark.asyncio
    async def test_delete_uses_filter_template(self):
        """delete_by_document_id 用 _DOCUMENT_FILTER 模板 + filter_params 传值,
        而不是字符串拼接,避免过滤表达式注入。"""
        client = _FakeMilvusClient()
        index = MilvusVectorIndex(client, cfg=_base_settings())

        org_id = uuid4()
        kb_id = uuid4()
        document_id = uuid4()
        await index.delete_by_document_id(org_id, kb_id, document_id)

        assert len(client.delete_calls) == 1
        call = client.delete_calls[0]
        # 模板用占位符 {org_id} / {kb_id} / {document_id}
        assert "org_id" in call["filter"]
        assert "kb_id" in call["filter"]
        assert "document_id" in call["filter"]
        # 实际值在 filter_params 里
        assert call["filter_params"]["org_id"] == str(org_id)
        assert call["filter_params"]["kb_id"] == str(kb_id)
        assert call["filter_params"]["document_id"] == str(document_id)
        # 关键:模板里不应该有真实 UUID 值(避免字符串拼接)
        assert str(org_id) not in call["filter"]
        assert str(kb_id) not in call["filter"]

    @pytest.mark.asyncio
    async def test_delete_failure_wrapped(self):
        client = _FakeMilvusClient()
        client.delete = lambda **kw: (_ for _ in ()).throw(RuntimeError("RPC down"))

        index = MilvusVectorIndex(client, cfg=_base_settings())
        with pytest.raises(MilvusVectorException):
            await index.delete_by_document_id(uuid4(), uuid4(), uuid4())


class TestStageValidation:
    """stage() 必须在写入前校验每个 chunk 的完整性,避免把不完整数据落到 Milvus。"""

    @pytest.mark.asyncio
    async def test_chunks_and_vectors_must_align(self):
        client = _FakeMilvusClient()
        index = MilvusVectorIndex(client, cfg=_base_settings(rag_milvus_vector_dimensions=4))

        chunk = _build_chunk("c-1", uuid4(), uuid4(), uuid4())
        with pytest.raises(ValueError):
            await index.stage([chunk], [[0.1, 0.2, 0.3]], "model-v1", "v1")  # 长度不匹配

    @pytest.mark.asyncio
    async def test_vector_dim_must_match_settings(self):
        client = _FakeMilvusClient()
        index = MilvusVectorIndex(client, cfg=_base_settings(rag_milvus_vector_dimensions=4))

        chunk = _build_chunk("c-1", uuid4(), uuid4(), uuid4())
        with pytest.raises(ValueError):
            await index.stage([chunk], [[0.1, 0.2, 0.3, 0.4, 0.5, 0.6]], "model-v1", "v1")

    @pytest.mark.asyncio
    async def test_chunk_must_have_tenant_ids(self):
        client = _FakeMilvusClient()
        index = MilvusVectorIndex(client, cfg=_base_settings(rag_milvus_vector_dimensions=4))

        chunk = Chunk(
            id="c-1",
            organization_id=None,  # 缺
            knowledge_base_id=uuid4(),
            document_id=uuid4(),
            ordinal=0,
            content="x",
        )
        with pytest.raises(ValueError):
            await index.stage([chunk], [[0.1, 0.2, 0.3, 0.4]], "model-v1", "v1")

    @pytest.mark.asyncio
    async def test_empty_chunks_no_op(self):
        client = _FakeMilvusClient()
        index = MilvusVectorIndex(client, cfg=_base_settings(rag_milvus_vector_dimensions=4))
        await index.stage([], [], "model-v1", "v1")
        assert client.upsert_calls == []

    @pytest.mark.asyncio
    async def test_empty_embedding_model_version_rejected(self):
        client = _FakeMilvusClient()
        index = MilvusVectorIndex(client, cfg=_base_settings(rag_milvus_vector_dimensions=4))
        chunk = _build_chunk("c-1", uuid4(), uuid4(), uuid4())
        with pytest.raises(ValueError):
            await index.stage([chunk], [[0.1, 0.2, 0.3, 0.4]], "", "v1")

    @pytest.mark.asyncio
    async def test_upsert_failure_wrapped(self):
        client = _FakeMilvusClient()
        client.upsert = lambda **kw: (_ for _ in ()).throw(RuntimeError("RPC fail"))

        index = MilvusVectorIndex(client, cfg=_base_settings(rag_milvus_vector_dimensions=4))
        chunk = _build_chunk("c-1", uuid4(), uuid4(), uuid4())
        with pytest.raises(MilvusVectorException):
            await index.stage([chunk], [[0.1, 0.2, 0.3, 0.4]], "model-v1", "v1")


class TestDocumentBoundaryValidation:
    @pytest.mark.asyncio
    async def test_missing_tenant_id_raises(self):
        client = _FakeMilvusClient()
        index = MilvusVectorIndex(client, cfg=_base_settings())
        with pytest.raises(ValueError):
            await index.activate_document(None, uuid4(), uuid4())  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_missing_kb_id_raises(self):
        client = _FakeMilvusClient()
        index = MilvusVectorIndex(client, cfg=_base_settings())
        with pytest.raises(ValueError):
            await index.activate_document(uuid4(), None, uuid4())  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_missing_document_id_raises(self):
        client = _FakeMilvusClient()
        index = MilvusVectorIndex(client, cfg=_base_settings())
        with pytest.raises(ValueError):
            await index.activate_document(uuid4(), uuid4(), None)  # type: ignore[arg-type]
