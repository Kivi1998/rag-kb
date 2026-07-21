"""Milvus 向量投影:先不可见暂存,再按租户文档边界激活。

对应 Java 版 `ragcore/index/MilvusVectorIndex.java`,实现 `app.ragcore.index.ports.VectorChunkIndex`
端口。正文和引用字段仍以 Elasticsearch 为权威来源,Milvus 只保存向量与最小过滤字段。

历史教训(2026-07-18 review 修复的 HIGH 缺陷,本次移植必须保留修复后的行为):
`setVisibility()` 曾经用单次 `QueryReq(limit=16384)` 拉取文档下全部待翻转可见性的 chunk_id,
超过该上限的文档只会处理第一页,尾部 chunk 静默停留在旧的 `retrieval_ready` 状态——删除场景下
表现为已删除文档的部分内容仍可被检索到。本文件的 `_query_all_chunk_ids()` 必须始终按 offset
翻页查询直到拿到不足一页的结果为止,不能只信任单次 limit 查询就代表"全部"。
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID

from pymilvus import MilvusClient  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.config import settings as default_settings
from app.ragcore.index.exceptions import MilvusVectorException
from app.ragcore.index.milvus_collection_manager import MilvusCollectionManager
from app.ragcore.model import Chunk

logger = logging.getLogger(__name__)

_C = MilvusCollectionManager

# org_id/kb_id/document_id 用 Milvus filter 模板占位符,取值经 filter_params 参数化传入,
# 而不是拼接进 filter 字符串——避免过滤表达式注入。
_DOCUMENT_FILTER = f"{_C.ORG_ID} == {{org_id}} and {_C.KB_ID} == {{kb_id}} and {_C.DOCUMENT_ID} == {{document_id}}"

# 单页查询上限;超过一页时必须翻页拉取,不能只处理第一页就视为完成。
_VISIBILITY_QUERY_PAGE_SIZE = 16_384


class MilvusVectorIndex:
    """`VectorChunkIndex` 端口的 Milvus 实现。对应 Java 版 `MilvusVectorIndex`。"""

    def __init__(self, client: MilvusClient, cfg: Settings | None = None) -> None:
        self._client = client
        cfg = cfg or default_settings
        self._collection_name = cfg.rag_milvus_collection
        self._vector_dimensions = cfg.rag_milvus_vector_dimensions
        self._rpc_timeout_s = cfg.rag_milvus_rpc_timeout_ms / 1000

    # ---- VectorChunkIndex --------------------------------------------------

    async def stage(
        self,
        chunks: list[Chunk],
        vectors: list[list[float]],
        embedding_model_version: str,
        chunk_version: str,
    ) -> None:
        self._validate_batch(chunks, vectors, embedding_model_version, chunk_version)
        if not chunks:
            return
        indexed_at = int(time.time() * 1000)
        rows: list[dict] = []
        for chunk, vector in zip(chunks, vectors):
            if vector is None or len(vector) != self._vector_dimensions:
                raise ValueError(f"Milvus 向量维度必须为 {self._vector_dimensions}")
            rows.append(
                {
                    _C.CHUNK_ID: chunk.id,
                    _C.EMBEDDING: list(vector),
                    _C.ORG_ID: str(chunk.organization_id),
                    _C.KB_ID: str(chunk.knowledge_base_id),
                    _C.DOCUMENT_ID: str(chunk.document_id),
                    _C.EMBEDDING_MODEL: embedding_model_version,
                    _C.CHUNK_VERSION: chunk_version,
                    _C.RETRIEVAL_READY: False,
                    _C.INDEXED_AT: indexed_at,
                }
            )
        try:
            await asyncio.to_thread(
                self._client.upsert,
                collection_name=self._collection_name,
                data=rows,
                timeout=self._rpc_timeout_s,
            )
        except Exception as ex:  # noqa: BLE001 - 统一包装为可识别异常
            raise MilvusVectorException("Milvus 向量暂存失败") from ex

    async def activate_document(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None:
        await self._set_visibility(organization_id, knowledge_base_id, document_id, True)

    async def deactivate_document(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None:
        await self._set_visibility(organization_id, knowledge_base_id, document_id, False)

    async def delete_by_document_id(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None:
        values = self._document_boundary(organization_id, knowledge_base_id, document_id)
        try:
            await asyncio.to_thread(
                self._client.delete,
                collection_name=self._collection_name,
                filter=_DOCUMENT_FILTER,
                filter_params=values,
                timeout=self._rpc_timeout_s,
            )
        except Exception as ex:  # noqa: BLE001
            raise MilvusVectorException("Milvus 文档向量删除失败") from ex

    # ---- 内部实现 --------------------------------------------------------

    async def _set_visibility(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID, ready: bool
    ) -> None:
        values = self._document_boundary(organization_id, knowledge_base_id, document_id)
        try:
            chunk_ids = await self._query_all_chunk_ids(values)
            if chunk_ids:
                updates = [{_C.CHUNK_ID: chunk_id, _C.RETRIEVAL_READY: ready} for chunk_id in chunk_ids]
                await asyncio.to_thread(
                    self._client.upsert,
                    collection_name=self._collection_name,
                    data=updates,
                    partial_update=True,
                    timeout=self._rpc_timeout_s,
                )
        except MilvusVectorException:
            raise
        except Exception as ex:  # noqa: BLE001
            action = "Milvus 文档向量激活失败" if ready else "Milvus 文档向量关闭可见性失败"
            raise MilvusVectorException(action) from ex

    async def _query_all_chunk_ids(self, boundary_values: dict[str, str]) -> list[str]:
        """翻页拉取文档下全部 chunk_id,不能只取第一页。

        单文档 chunk 数可能超过单页上限(大文档/细粒度切块),若只查一页就直接更新可见性,
        超出部分会永久停留在旧的 `retrieval_ready` 状态且没有任何报错:激活时表现为部分
        chunk 永远不可检索;关闭可见性(删除前置步骤)时表现为已删除文档的部分内容仍可被
        检索到,属于静默的数据可见性/治理缺陷。对应 Java 版修复后的 `queryAllChunkIds()`。
        """
        chunk_ids: list[str] = []
        offset = 0
        while True:
            page = await asyncio.to_thread(
                self._client.query,
                collection_name=self._collection_name,
                filter=_DOCUMENT_FILTER,
                filter_params=boundary_values,
                output_fields=[_C.CHUNK_ID],
                offset=offset,
                limit=_VISIBILITY_QUERY_PAGE_SIZE,
                consistency_level="Session",
                timeout=self._rpc_timeout_s,
            )
            ids = [str(row[_C.CHUNK_ID]) for row in page if row.get(_C.CHUNK_ID) is not None]
            chunk_ids.extend(ids)
            if len(ids) < _VISIBILITY_QUERY_PAGE_SIZE:
                return chunk_ids
            offset += _VISIBILITY_QUERY_PAGE_SIZE

    @staticmethod
    def _document_boundary(
        organization_id: UUID | None, knowledge_base_id: UUID | None, document_id: UUID | None
    ) -> dict[str, str]:
        if organization_id is None or knowledge_base_id is None or document_id is None:
            raise ValueError("Milvus 文档操作必须包含 orgId、kbId、documentId")
        return {
            "org_id": str(organization_id),
            "kb_id": str(knowledge_base_id),
            "document_id": str(document_id),
        }

    @staticmethod
    def _validate_batch(
        chunks: list[Chunk],
        vectors: list[list[float]],
        embedding_model_version: str,
        chunk_version: str,
    ) -> None:
        if chunks is None or vectors is None or len(chunks) != len(vectors):
            raise ValueError("Chunk 与向量必须按下标一一对应")
        if not embedding_model_version or not embedding_model_version.strip():
            raise ValueError("embeddingModelVersion 和 chunkVersion 不能为空")
        if not chunk_version or not chunk_version.strip():
            raise ValueError("embeddingModelVersion 和 chunkVersion 不能为空")
        for chunk in chunks:
            if (
                chunk is None
                or not chunk.id
                or not chunk.id.strip()
                or chunk.organization_id is None
                or chunk.knowledge_base_id is None
                or chunk.document_id is None
            ):
                raise ValueError("Milvus Chunk 必须包含 ID 与完整租户边界")
