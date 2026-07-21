"""对应 repository/IngestionJobRepository.java。

多处方法(队列轮询、租约回收、统计)本来就不按 org_id 过滤 —— Worker 需要跨租户扫描任务队列,
这是 Java 版原始设计,每处都在方法注释里标注「未做租户过滤,继承自 Java 版原始行为」。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update

from app.models.enums import IngestionStatus
from app.models.ingestion_job import IngestionJob
from app.repositories.base import BaseRepository


class IngestionJobRepository(BaseRepository[IngestionJob]):
    model = IngestionJob

    async def find_first_by_document_id_order_by_created_at_desc(
        self, document_id: UUID
    ) -> IngestionJob | None:
        """对应 Java findFirstByDocumentIdOrderByCreatedAtDesc。

        未做租户过滤,继承自 Java 版原始行为:调用方通常已经通过 document 的 org_id 校验过
        归属,这里只按 document_id 取最近一条任务。
        """
        stmt = (
            select(IngestionJob)
            .where(IngestionJob.document_id == document_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_id_and_knowledge_base_id_and_org_id(
        self, id_: UUID, knowledge_base_id: UUID, org_id: UUID
    ) -> IngestionJob | None:
        """对应 Java findByIdAndKnowledgeBaseIdAndOrgId。"""
        stmt = select(IngestionJob).where(
            IngestionJob.id == id_,
            IngestionJob.kb_id == knowledge_base_id,
            IngestionJob.org_id == org_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_id_for_update(self, job_id: UUID) -> IngestionJob | None:
        """对应 Java findByIdForUpdate:@Lock(PESSIMISTIC_WRITE),阶段推进时锁定任务行,
        与租约回收/接管串行化。

        未做租户过滤,继承自 Java 版原始行为:按主键加锁,调用方负责在锁定前已校验归属。
        """
        stmt = select(IngestionJob).where(IngestionJob.id == job_id).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_status_order_by_created_at_asc(
        self, status: IngestionStatus, limit: int | None = None, offset: int = 0
    ) -> list[IngestionJob]:
        """对应 Java 两个重载 findByStatusOrderByCreatedAtAsc(status) /
        findByStatusOrderByCreatedAtAsc(status, Pageable)。`limit=None` 对应无 Pageable 的版本
        (取全部);传入 `limit` 对应带 Pageable 的分页版本。

        未做租户过滤,继承自 Java 版原始行为:摄取 Worker 按状态轮询队列,天然跨所有租户。
        """
        stmt = select(IngestionJob).where(IngestionJob.status == status).order_by(
            IngestionJob.created_at.asc()
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_status(self, status: IngestionStatus) -> int:
        """对应 Java countByStatus。

        未做租户过滤,继承自 Java 版原始行为:供 Worker/可观测性指标统计全局队列深度。
        """
        stmt = select(func.count()).select_from(IngestionJob).where(IngestionJob.status == status)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def find_by_status_in_and_lease_expires_at_before(
        self, statuses: list[IngestionStatus], expires_before: datetime
    ) -> list[IngestionJob]:
        """对应 Java findByStatusInAndLeaseExpiresAtBefore。

        未做租户过滤,继承自 Java 版原始行为:租约回收任务需要跨租户扫描所有过期租约。
        """
        stmt = select(IngestionJob).where(
            IngestionJob.status.in_(statuses), IngestionJob.lease_expires_at < expires_before
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_document_id(self, document_id: UUID) -> None:
        """对应 Java deleteByDocumentId。

        未做租户过滤,继承自 Java 版原始行为:调用方负责在删除前已校验 document 归属。
        """
        stmt = delete(IngestionJob).where(IngestionJob.document_id == document_id)
        await self.session.execute(stmt)

    async def claim_if_queued(
        self,
        job_id: UUID,
        expected_status: IngestionStatus,
        next_status: IngestionStatus,
        now: datetime,
        lease_owner: str,
        lease_expires_at: datetime,
    ) -> int:
        """原子领取任务,对应 Java claimIfQueued:避免多实例 Worker 同时处理一条 QUEUED 记录。
        返回 0 说明已被其他实例领取或状态已变化,返回 1 表示领取成功。
        """
        stmt = (
            update(IngestionJob)
            .where(IngestionJob.id == job_id, IngestionJob.status == expected_status)
            .values(
                status=next_status,
                attempt=IngestionJob.attempt + 1,
                started_at=now,
                updated_at=now,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                last_heartbeat_at=now,
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    async def heartbeat(
        self,
        job_id: UUID,
        lease_owner: str,
        attempt: int,
        active_statuses: list[IngestionStatus],
        now: datetime,
        lease_expires_at: datetime,
    ) -> int:
        """对应 Java heartbeat:续租,失败(返回 0)说明租约已被判定过期并被其他实例接管。"""
        stmt = (
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.lease_owner == lease_owner,
                IngestionJob.attempt == attempt,
                IngestionJob.status.in_(active_statuses),
                IngestionJob.lease_expires_at >= now,
            )
            .values(lease_expires_at=lease_expires_at, last_heartbeat_at=now, updated_at=now)
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    async def requeue_expired_lease(
        self, job_id: UUID, active_statuses: list[IngestionStatus], queued_status: IngestionStatus, now: datetime
    ) -> int:
        """对应 Java requeueExpiredLease:租约过期任务清空租约信息并迁回 QUEUED,允许重新领取。"""
        stmt = (
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.status.in_(active_statuses),
                IngestionJob.lease_expires_at < now,
            )
            .values(
                status=queued_status,
                lease_owner=None,
                lease_expires_at=None,
                last_heartbeat_at=None,
                started_at=None,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    async def fail_expired_lease(
        self,
        job_id: UUID,
        active_statuses: list[IngestionStatus],
        failed_status: IngestionStatus,
        error_message: str,
        now: datetime,
    ) -> int:
        """对应 Java failExpiredLease:超过最大重试次数的过期租约任务直接判失败,不再重新入队。"""
        stmt = (
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.status.in_(active_statuses),
                IngestionJob.lease_expires_at < now,
            )
            .values(
                status=failed_status,
                error_message=error_message,
                finished_at=now,
                lease_owner=None,
                lease_expires_at=None,
                last_heartbeat_at=None,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    async def mark_deleting_by_document_id(
        self, document_id: UUID, active_statuses: list[IngestionStatus], deleting_status: IngestionStatus, now: datetime
    ) -> int:
        """对应 Java markDeletingByDocumentId:删除请求优先取消未完成任务,正在执行的 Pipeline
        会在下一阶段迁移时停止。

        未做租户过滤,继承自 Java 版原始行为:按 document_id 过滤,调用方负责在删除前已校验
        document 归属。
        """
        stmt = (
            update(IngestionJob)
            .where(IngestionJob.document_id == document_id, IngestionJob.status.in_(active_statuses))
            .values(status=deleting_status, updated_at=now)
        )
        result = await self.session.execute(stmt)
        return result.rowcount
