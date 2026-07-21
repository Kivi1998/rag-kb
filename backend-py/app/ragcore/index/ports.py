"""倒排索引与向量索引的端口协议。对应 Java 版 `ragcore/index/ChunkIndex.java`、
`ragcore/index/LexicalChunkIndex.java`、`ragcore/index/VectorChunkIndex.java`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.ragcore.index.search_request import SearchRequest
from app.ragcore.model import Chunk, RetrievedChunk


@runtime_checkable
class ChunkIndex(Protocol):
    """倒排索引与向量索引的统一端口(遗留兼容接口)。

    对应 Java 版 `ChunkIndex`。Java 版的 ES 实现里 `search()` 直接抛
    `UnsupportedOperationException`——混合检索必须走 `HybridRetriever` 而非这个无租户
    过滤保护的泛型 search，Python 实现同样禁止真正实现这个方法。
    """

    async def upsert(
        self, chunks: list[Chunk], vectors: list[list[float]], embedding_model_version: str
    ) -> None: ...

    async def delete_by_document_id(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None: ...

    async def search(self, request: SearchRequest) -> list[RetrievedChunk]: ...


@runtime_checkable
class LexicalChunkIndex(Protocol):
    """ES Chunk 词法投影的暂存、激活和隐藏端口。对应 Java 版 `LexicalChunkIndex`。"""

    async def stage(
        self, chunks: list[Chunk], vectors: list[list[float]], embedding_model_version: str
    ) -> None: ...

    async def activate_document(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None: ...

    async def deactivate_document(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None: ...

    async def delete_by_document_id(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None: ...


@runtime_checkable
class VectorChunkIndex(Protocol):
    """独立向量投影端口；正文和引用字段仍以 Elasticsearch 为权威来源。

    对应 Java 版 `VectorChunkIndex`。
    """

    async def stage(
        self,
        chunks: list[Chunk],
        vectors: list[list[float]],
        embedding_model_version: str,
        chunk_version: str,
    ) -> None: ...

    async def activate_document(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None: ...

    async def deactivate_document(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None: ...

    async def delete_by_document_id(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None: ...
