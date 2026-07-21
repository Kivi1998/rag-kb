"""文档入库状态机枚举。对应 Java 版 `ragcore/model/IngestionStatus.java`。

状态只允许按 队列→解析→切分→向量化→索引→就绪 的顺序向前推进;
任一处理中状态均可进入 FAILED,删除请求进入 DELETING。
"""

from __future__ import annotations

from enum import Enum


class IngestionStatus(str, Enum):
    QUEUED = "QUEUED"
    PARSING = "PARSING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"
    DELETING = "DELETING"


# 处理中(已被 Worker 领取)的活跃状态;用于租约恢复、并发去重等场景
ACTIVE_STATUSES: frozenset[IngestionStatus] = frozenset(
    {
        IngestionStatus.PARSING,
        IngestionStatus.CHUNKING,
        IngestionStatus.EMBEDDING,
        IngestionStatus.INDEXING,
    }
)

# 文档被申请删除时,这些活跃状态要被允许打断(DELETING 是更高优先级)
INTERRUPTIBLE_STATUSES: frozenset[IngestionStatus] = frozenset(
    {
        IngestionStatus.QUEUED,
        IngestionStatus.PARSING,
        IngestionStatus.CHUNKING,
        IngestionStatus.EMBEDDING,
        IngestionStatus.INDEXING,
        IngestionStatus.FAILED,
    }
)
