"""BM25 / 关键词候选召回端口。对应 Java 版 `ragcore/retrieval/LexicalCandidateSource.java`。

实现必须在底层 ES 查询的 bool.filter 中强制注入 organization_id、knowledge_base_id
和 retrieval_ready=true 三条 tenant 过滤,且对 document_ids 非空时叠加 document_id
范围过滤——禁止把过滤交给调用方,这是 toB 隔离红线。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ragcore.index.search_request import SearchRequest
from app.ragcore.model import RetrievedChunk


@runtime_checkable
class LexicalCandidateSource(Protocol):
    async def search(self, request: SearchRequest) -> list[RetrievedChunk]: ...
