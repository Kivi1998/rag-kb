"""重排模型适配层协议，输入和输出均保留候选块以便审计。

对应 Java 版 `ragcore/rerank/RerankerClient.java`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ragcore.model import RetrievedChunk


@runtime_checkable
class RerankerClient(Protocol):
    async def rerank(
        self, query: str, candidates: list[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        """对 candidates 重新打分排序，取前 top_k 个；query/candidates 为空或 top_k<=0 时返回空列表。"""
        ...
