"""向量候选召回端口。对应 Java 版 `ragcore/retrieval/VectorCandidateSource.java`。

只返回 chunk_id / 排名 / 分数三个最小字段,正文必须通过受租户保护的 ChunkHydrator 补齐。
所有实现(ES kNN / Milvus)在构造底层查询时必须把 organization_id、knowledge_base_id、
retrieval_ready=true 参数化注入 filter——绝不能返回无 tenant 过滤的命中。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ragcore.retrieval.vector_hit import VectorHit
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest


@runtime_checkable
class VectorCandidateSource(Protocol):
    async def search(self, request: VectorSearchRequest) -> list[VectorHit]: ...
