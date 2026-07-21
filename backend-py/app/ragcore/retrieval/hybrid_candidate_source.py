"""两路(BM25 + kNN)候选召回端口。对应 Java 版 `ragcore/retrieval/HybridCandidateSource.java`。

仅作为旧构造器的兼容入口保留(评测脚本/存量测试),新生产代码应使用
`LexicalCandidateSource` + `VectorCandidateSource` + `ChunkHydrator` 三端口独立组装。
每个实现必须在底层查询中强制注入 organization_id、knowledge_base_id、retrieval_ready=true。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ragcore.index.search_request import SearchRequest
from app.ragcore.model import RetrievedChunk
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest


@runtime_checkable
class HybridCandidateSource(Protocol):
    async def search_bm25(self, request: SearchRequest) -> list[RetrievedChunk]: ...

    async def search_knn(self, request: VectorSearchRequest) -> list[RetrievedChunk]: ...
