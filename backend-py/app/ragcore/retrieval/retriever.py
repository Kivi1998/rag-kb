"""混合召回、融合和可选重排的编排端口。对应 Java 版 `ragcore/retrieval/Retriever.java`。

`retrieve_with_decision` 才是真正入口——返回结构化结果或显式拒答原因,避免"空结果 ⇒
LLM 自填"的安全漏洞。`retrieve` 是简化入口,实现可以选择性覆盖。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.ragcore.model import RetrievedChunk
from app.ragcore.retrieval.retrieval_options import RetrievalOptions
from app.ragcore.retrieval.retrieval_result import RetrievalResult


@runtime_checkable
class Retriever(Protocol):
    async def retrieve(
        self,
        organization_id: UUID,
        knowledge_base_id: UUID,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedChunk]: ...

    async def retrieve_with_decision(
        self,
        organization_id: UUID,
        knowledge_base_id: UUID,
        query: str,
        options: RetrievalOptions,
    ) -> RetrievalResult: ...
