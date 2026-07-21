"""基于排名而非不同分数量纲的 Reciprocal Rank Fusion。

对应 Java 版 `ragcore/retrieval/RrfFusion.java`。常量
`DEFAULT_RANK_CONSTANT = 60` 与 `MIN_RRF_SCORE = 0.01` 都从 Java 版原样搬运,
不要改动——MIN_RRF_SCORE 校准于 150 题人工标注评估集,改动会破坏拒答早退阈值。
"""

from __future__ import annotations

from typing import Iterable

from app.ragcore.model import RetrievedChunk

DEFAULT_RANK_CONSTANT: int = 60
MIN_RRF_SCORE: float = 0.01


def _rank_score(rank: int | None) -> float:
    if rank is None:
        return 0.0
    return 1.0 / (DEFAULT_RANK_CONSTANT + rank)


def fuse(
    bm25: Iterable[RetrievedChunk],
    vector: Iterable[RetrievedChunk],
    bm25_weight: float = 1.0,
    vector_weight: float = 1.0,
) -> list[RetrievedChunk]:
    """按权重加权的 RRF 融合。两路权重均为 1.0 时与未加权版本数学等价。"""
    if bm25_weight < 0 or vector_weight < 0:
        raise ValueError("bm25_weight 与 vector_weight 不能为负数")

    candidates: dict[str, RetrievedChunk] = {}

    for item in bm25 or []:
        previous = candidates.get(item.chunk.id)
        bm25_rank = item.bm25_rank
        vector_rank = previous.vector_rank if previous is not None else None
        score = bm25_weight * _rank_score(bm25_rank) + vector_weight * _rank_score(vector_rank)
        candidates[item.chunk.id] = RetrievedChunk(
            chunk=item.chunk,
            bm25_rank=bm25_rank,
            vector_rank=vector_rank,
            rrf_score=score,
            rerank_score=previous.rerank_score if previous is not None else None,
            final_score=score,
        )

    for item in vector or []:
        previous = candidates.get(item.chunk.id)
        bm25_rank = previous.bm25_rank if previous is not None else None
        vector_rank = item.vector_rank
        score = bm25_weight * _rank_score(bm25_rank) + vector_weight * _rank_score(vector_rank)
        candidates[item.chunk.id] = RetrievedChunk(
            chunk=item.chunk,
            bm25_rank=bm25_rank,
            vector_rank=vector_rank,
            rrf_score=score,
            rerank_score=previous.rerank_score if previous is not None else None,
            final_score=score,
        )

    return sorted(
        candidates.values(),
        key=lambda c: (c.rrf_score is None, -(c.rrf_score or 0.0)),
    )
