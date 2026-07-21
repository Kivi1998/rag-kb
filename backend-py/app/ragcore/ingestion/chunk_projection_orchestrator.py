"""Chunk 双投影提交协议:ES 暂存 → Milvus 暂存 → Milvus 激活 → ES 最终激活。

对应 Java 版 `ragcore/ingestion/ChunkProjectionOrchestrator.java`。

任一步失败都不会提前暴露 ES 正文;相同确定性 Chunk ID 的重试使用 Upsert 收敛。

历史教训: 2026-07-15 修复 MilvusVectorIndex.setVisibility() 的 16384-vector
单次 QueryReq 限制;双投影的"stage→stage→activate"三步顺序与该修复一致——
ES 是正文权威源,必须作为最后提交点;只有这一步完成,Pipeline 才能推进 READY。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional
from uuid import UUID

from app.ragcore.index.ports import LexicalChunkIndex, VectorChunkIndex
from app.ragcore.model import Chunk

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DocumentBoundary:
    organization_id: UUID
    knowledge_base_id: UUID
    document_id: UUID


class ChunkProjectionOrchestrator:
    def __init__(
        self,
        lexical_index: LexicalChunkIndex,
        vector_index: Optional[VectorChunkIndex] = None,
    ) -> None:
        if lexical_index is None:
            raise ValueError("lexicalIndex 不能为空")
        self._lexical = lexical_index
        self._vector = vector_index

    async def project(
        self,
        chunks: Iterable[Chunk],
        vectors: Iterable[list[float]],
        embedding_model_version: str,
    ) -> None:
        chunks_list = list(chunks)
        vectors_list = [list(v) for v in vectors]
        boundary = self._validate(chunks_list, vectors_list, embedding_model_version)
        await self._lexical.stage(chunks_list, vectors_list, embedding_model_version)
        if self._vector is not None:
            chunk_version = _first_chunk_version(chunks_list)
            await self._vector.stage(
                chunks_list, vectors_list, embedding_model_version, chunk_version
            )
            await self._vector.activate_document(
                boundary.organization_id, boundary.knowledge_base_id, boundary.document_id
            )
        # ES 是正文权威源,必须作为最后提交点
        await self._lexical.activate_document(
            boundary.organization_id, boundary.knowledge_base_id, boundary.document_id
        )

    def _validate(
        self,
        chunks: list[Chunk],
        vectors: list[list[float]],
        embedding_model_version: str,
    ) -> DocumentBoundary:
        if not chunks or vectors is None or len(chunks) != len(vectors):
            raise ValueError("双投影要求非空且一一对应的 Chunk 与向量")
        if not embedding_model_version or not embedding_model_version.strip():
            raise ValueError("embeddingModelVersion 不能为空")
        boundary = self._boundary(chunks[0])
        chunk_version = _first_chunk_version(chunks)
        for chunk in chunks:
            if boundary != self._boundary(chunk):
                raise ValueError("一次双投影批次只能包含同一租户、知识库和文档")
            if chunk_version != _chunk_version(chunk):
                raise ValueError("一次双投影批次不能混用不同 chunkVersion")
        return boundary

    @staticmethod
    def _boundary(chunk: Chunk) -> DocumentBoundary:
        if (
            chunk is None
            or chunk.organization_id is None
            or chunk.knowledge_base_id is None
            or chunk.document_id is None
            or not chunk.id
            or not chunk.id.strip()
        ):
            raise ValueError("Chunk 必须包含确定性 ID 与完整租户边界")
        return DocumentBoundary(
            organization_id=chunk.organization_id,
            knowledge_base_id=chunk.knowledge_base_id,
            document_id=chunk.document_id,
        )


def _first_chunk_version(chunks: list[Chunk]) -> str:
    return _chunk_version(chunks[0])


def _chunk_version(chunk: Chunk) -> str:
    metadata = chunk.metadata or {}
    return str(metadata.get("chunkVersion") or "v1")
