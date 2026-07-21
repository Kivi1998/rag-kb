"""向量模型适配层协议，屏蔽本地模型和云模型差异。

对应 Java 版 `ragcore/embedding/EmbeddingClient.java`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ragcore.model import EmbeddingResult


@runtime_checkable
class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """把 texts 编码为向量；texts 为空时返回空结果，texts 含空白文本时抛出 ValueError。"""
        ...
