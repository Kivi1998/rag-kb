"""带组织与知识库边界的检索请求。对应 Java 版 `ragcore/index/SearchRequest.java`。

索引/候选源实现不得忽略租户过滤条件；`document_ids` 非空时应在租户过滤之外叠加范围过滤，
只在指定文档内检索。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SearchRequest:
    organization_id: UUID
    knowledge_base_id: UUID
    query: str
    top_k: int
    document_ids: tuple[UUID, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_ids", tuple(self.document_ids or ()))
        if self.top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        if self.organization_id is None or self.knowledge_base_id is None:
            raise ValueError("organization_id 与 knowledge_base_id 不能为空")
