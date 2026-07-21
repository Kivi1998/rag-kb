"""按向量命中 ID 补齐 ES Chunk 的端口。对应 Java 版 `ragcore/retrieval/ChunkHydrator.java`。

实现必须在 ES 查询中强制 org_id/kb_id 过滤,并在结果返回后再次校验每条 chunk 的
organization_id/knowledge_base_id 与请求一致(纵深防御,绝不能信任上游向量库的过滤)。
返回值顺序必须与可找到的输入 ID 顺序一致,以便 HybridRetriever 按向量排名顺序重排。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.ragcore.model import Chunk


@runtime_checkable
class ChunkHydrator(Protocol):
    async def find_by_chunk_ids(
        self, organization_id: UUID, knowledge_base_id: UUID, chunk_ids: list[str]
    ) -> list[Chunk]: ...
