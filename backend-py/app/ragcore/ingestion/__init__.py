"""文档摄取子包。对应 Java 版 `ragcore/ingestion/`。

公共 API:
    状态机:
        IngestionStatus, ACTIVE_STATUSES, INTERRUPTIBLE_STATUSES,
        can_transition, require_transition
    任务快照:
        IngestionTask, StaleIngestionLeaseException
    端口:
        DocumentIngestionPipeline, IngestionJobLifecycleService, ParsedArtifactStore
    核心实现:
        ChunkProjectionOrchestrator, DefaultDocumentIngestionPipeline,
        IngestionMetrics, ParsedArtifactStore,
        SqlAlchemyIngestionJobLifecycleService
    调度:
        IngestionWorker, run_deletion_cleanup_loop
    删除补偿:
        DocumentDeletionService

多租户: ChunkProjectionOrchestrator 在 stage 之前校验同一批次 Chunk 共享
org_id/kb_id/document_id;DocumentDeletionService 强制 org_id/kb_id 由服务端
记录注入,删除路径不接受请求覆盖。
"""

from app.ragcore.ingestion.artifact_store import ParsedArtifactStore, SavedArtifact
from app.ragcore.ingestion.chunk_projection_orchestrator import (
    ChunkProjectionOrchestrator,
    DocumentBoundary,
)
from app.ragcore.ingestion.default_pipeline import DefaultDocumentIngestionPipeline
from app.ragcore.ingestion.deletion_service import DocumentDeletionService
from app.ragcore.ingestion.deletion_worker import (
    DEFAULT_BATCH_LIMIT,
    DEFAULT_POLL_INTERVAL_SECONDS,
    run_deletion_cleanup_loop,
)
from app.ragcore.ingestion.exceptions import StaleIngestionLeaseException
from app.ragcore.ingestion.lifecycle_service import IngestionJobLifecycleService
from app.ragcore.ingestion.metrics import IngestionMetrics
from app.ragcore.ingestion.pipeline import DocumentIngestionPipeline
from app.ragcore.ingestion.sqlalchemy_lifecycle_service import (
    SqlAlchemyIngestionJobLifecycleService,
)
from app.ragcore.ingestion.state_machine import can_transition, require_transition
from app.ragcore.ingestion.status import (
    ACTIVE_STATUSES,
    INTERRUPTIBLE_STATUSES,
    IngestionStatus,
)
from app.ragcore.ingestion.task import IngestionTask
from app.ragcore.ingestion.worker import IngestionWorker

__all__ = [
    # 状态机
    "IngestionStatus",
    "ACTIVE_STATUSES",
    "INTERRUPTIBLE_STATUSES",
    "can_transition",
    "require_transition",
    # 任务快照
    "IngestionTask",
    "StaleIngestionLeaseException",
    # 端口
    "DocumentIngestionPipeline",
    "IngestionJobLifecycleService",
    "ParsedArtifactStore",
    "SavedArtifact",
    # 核心实现
    "ChunkProjectionOrchestrator",
    "DocumentBoundary",
    "DefaultDocumentIngestionPipeline",
    "IngestionMetrics",
    "ParsedArtifactStore",
    "SqlAlchemyIngestionJobLifecycleService",
    # 调度
    "IngestionWorker",
    "DocumentDeletionService",
    "DEFAULT_BATCH_LIMIT",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "run_deletion_cleanup_loop",
]
