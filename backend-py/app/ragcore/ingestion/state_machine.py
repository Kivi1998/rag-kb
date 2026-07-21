"""文档入库状态迁移规则,Worker 与管理接口均应通过此类校验状态变化。

对应 Java 版 `ragcore/model/IngestionStateMachine.java`。
"""

from __future__ import annotations

from app.ragcore.ingestion.status import IngestionStatus

# from -> {to, ...} 的合法迁移表
_TRANSITIONS: dict[IngestionStatus, frozenset[IngestionStatus]] = {
    IngestionStatus.QUEUED: frozenset(
        {IngestionStatus.PARSING, IngestionStatus.FAILED, IngestionStatus.DELETING}
    ),
    IngestionStatus.PARSING: frozenset(
        {IngestionStatus.CHUNKING, IngestionStatus.FAILED, IngestionStatus.DELETING}
    ),
    IngestionStatus.CHUNKING: frozenset(
        {IngestionStatus.EMBEDDING, IngestionStatus.FAILED, IngestionStatus.DELETING}
    ),
    IngestionStatus.EMBEDDING: frozenset(
        {IngestionStatus.INDEXING, IngestionStatus.FAILED, IngestionStatus.DELETING}
    ),
    IngestionStatus.INDEXING: frozenset(
        {IngestionStatus.READY, IngestionStatus.FAILED, IngestionStatus.DELETING}
    ),
    IngestionStatus.READY: frozenset({IngestionStatus.QUEUED, IngestionStatus.DELETING}),
    IngestionStatus.FAILED: frozenset({IngestionStatus.QUEUED, IngestionStatus.DELETING}),
    IngestionStatus.DELETING: frozenset(),
}


def can_transition(from_status: IngestionStatus | None, to_status: IngestionStatus | None) -> bool:
    if from_status is None or to_status is None:
        return False
    return to_status in _TRANSITIONS.get(from_status, frozenset())


def require_transition(from_status: IngestionStatus, to_status: IngestionStatus) -> None:
    if not can_transition(from_status, to_status):
        raise ValueError(f"不允许的入库状态迁移: {from_status} -> {to_status}")
