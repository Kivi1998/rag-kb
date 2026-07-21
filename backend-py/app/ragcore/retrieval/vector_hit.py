"""向量数据库返回的最小命中单元。对应 Java 版 `ragcore/retrieval/VectorHit.java`。

只携带 chunk_id、排名、分数，禁止承载未校验的正文或引用元数据——正文必须通过受租户
保护的 `ChunkHydrator` 补齐，避免 ES/Milvus 投影字段漂移后误把任意外部 chunk 内容
注入检索结果。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VectorHit:
    chunk_id: str
    rank: int
    score: float

    def __post_init__(self) -> None:
        if not self.chunk_id or not self.chunk_id.strip():
            raise ValueError("VectorHit.chunk_id 不能为空")
        if self.rank <= 0:
            raise ValueError("VectorHit.rank 必须为正数")
        if not math.isfinite(self.score):
            raise ValueError("VectorHit.score 必须为有限数")
