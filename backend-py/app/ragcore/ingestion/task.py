"""跨事务传递给后台 Pipeline 的不可变任务快照。

对应 Java 版 `ragcore/ingestion/IngestionTask.java`。
禁止携带 JPA 懒加载实体——以 dataclass(frozen)传递,确保 Worker 不会通过它触碰
懒加载代理。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.ragcore.ingestion.status import IngestionStatus


@dataclass(frozen=True, slots=True)
class IngestionTask:
    job_id: UUID
    attempt: int
    lease_owner: str
    document_id: UUID
    organization_id: UUID
    knowledge_base_id: UUID
    filename: str
    content_type: str | None
    object_storage_path: str
    parse_artifact_path: str | None
    parser_version: str | None


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """管理端点(如重试)返回值的不可变快照,原因同 `IngestionTask`:
    短事务 session 一关闭,返回原始 ORM 实体会导致调用方任一属性访问都触发
    懒加载 → DetachedInstanceError。"""

    id: UUID
    document_id: UUID
    kb_id: UUID
    status: IngestionStatus
    error_message: str | None
    max_attempts: int
    attempt: int
    created_at: datetime
    updated_at: datetime
