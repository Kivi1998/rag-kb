"""混合检索与重排阶段的查询参数。对应 Java 版 `ragcore/retrieval/RetrievalOptions.java`。

字段语义与默认值必须与 Java 版完全一致——评估脚本与跨语言对照测试依赖这套契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetrievalOptions:
    candidate_limit: int
    result_limit: int
    rerank: bool
    document_ids: tuple[UUID, ...] = field(default_factory=tuple)
    precomputed_query_vector: list[float] | None = None
    bm25_weight: float = 1.0
    vector_weight: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_ids", tuple(self.document_ids or ()))
        if self.precomputed_query_vector is not None:
            object.__setattr__(self, "precomputed_query_vector", list(self.precomputed_query_vector))
        if self.candidate_limit <= 0 or self.result_limit <= 0 or self.result_limit > self.candidate_limit:
            raise ValueError("候选数必须大于等于结果数，且两者都大于 0")
        if self.bm25_weight < 0 or self.vector_weight < 0:
            raise ValueError("检索权重不能为负数")

    @staticmethod
    def defaults() -> "RetrievalOptions":
        """默认值: 50 候选, 8 结果, 开启重排, 等权重。"""
        return RetrievalOptions(
            candidate_limit=50,
            result_limit=8,
            rerank=True,
            document_ids=(),
            precomputed_query_vector=None,
            bm25_weight=1.0,
            vector_weight=1.0,
        )

    def with_precomputed_query_vector(self, vector: Iterable[float] | None) -> "RetrievalOptions":
        """附加一个已经算好的查询向量,避免检索阶段重复调用 Embedding。"""
        return RetrievalOptions(
            candidate_limit=self.candidate_limit,
            result_limit=self.result_limit,
            rerank=self.rerank,
            document_ids=self.document_ids,
            precomputed_query_vector=list(vector) if vector is not None else None,
            bm25_weight=self.bm25_weight,
            vector_weight=self.vector_weight,
        )

    def with_weights(self, bm25_weight: float, vector_weight: float) -> "RetrievalOptions":
        """按查询意图分类结果调整两路召回的 RRF 权重,不改变其他参数。"""
        if bm25_weight < 0 or vector_weight < 0:
            raise ValueError("检索权重不能为负数")
        return RetrievalOptions(
            candidate_limit=self.candidate_limit,
            result_limit=self.result_limit,
            rerank=self.rerank,
            document_ids=self.document_ids,
            precomputed_query_vector=self.precomputed_query_vector,
            bm25_weight=bm25_weight,
            vector_weight=vector_weight,
        )
