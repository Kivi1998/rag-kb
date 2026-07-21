"""服务端生成 Embedding 后用于 ES kNN / Milvus 召回的租户边界请求。

对应 Java 版 `ragcore/retrieval/VectorSearchRequest.java`。
`document_ids` 非空时，索引实现应在租户过滤之外叠加 document_id 范围过滤。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VectorSearchRequest:
    organization_id: UUID
    knowledge_base_id: UUID
    query_vector: list[float] = field(default_factory=list)
    top_k: int = 0
    document_ids: tuple[UUID, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # 冻结后再校正，确保 tuple/list 不可变。
        object.__setattr__(self, "query_vector", list(self.query_vector or []))
        object.__setattr__(self, "document_ids", tuple(self.document_ids or ()))
        if self.organization_id is None or self.knowledge_base_id is None:
            raise ValueError("VectorSearchRequest 必须携带 organization_id 与 knowledge_base_id")
        if not self.query_vector:
            raise ValueError("VectorSearchRequest.query_vector 不能为空")
        if self.top_k <= 0:
            raise ValueError("VectorSearchRequest.top_k 必须大于 0")
