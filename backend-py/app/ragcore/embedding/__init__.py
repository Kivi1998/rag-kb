"""向量模型适配层。对应 Java 版 `ragcore/embedding/`。"""

from app.ragcore.embedding.client import EmbeddingClient
from app.ragcore.embedding.openai_compatible import (
    OpenAiCompatibleEmbeddingClient,
    build_embedding_client,
)

__all__ = [
    "EmbeddingClient",
    "OpenAiCompatibleEmbeddingClient",
    "build_embedding_client",
]
