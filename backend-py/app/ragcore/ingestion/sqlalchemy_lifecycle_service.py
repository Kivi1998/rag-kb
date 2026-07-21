"""摄取任务状态机的 SQLAlchemy 持久化实现。对应 Java 版
`IngestionJobLifecycleService.java` + 其使用的若干 repository 方法。

按 `IngestionJobLifecycleService` Protocol 形状提供 `claim` / `heartbeat` /
`advance` / `fail` / `record_parsed_artifact` / `recover_expired_leases` /
`retry` 七个方法,所有状态变化同时落 `ingestion_job` 与 `document` 两张表(对应
Java 版 `IngestionJobLifecycleService` 中 `updateDocumentStatus` 副作用)。

**session 设计**：本类不持有一个长生命周期 `AsyncSession`,而是在构造时接收一个
`session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]]` /
`Callable[[], AsyncContextManager[AsyncSession]]`(典型为 `SessionLocal`),每个
方法内部 `async with session_factory() as session: async with session.begin(): ...`
开短事务,完成后释放。Worker 里的 claim / heartbeat / advance / fail 跑在不同
asyncio task 上,各自需要独立 session 才能保证事务边界,共用一个 session 会导致
跨任务 await 串行化(AsyncSession 不是线程/任务安全的)。

**与 Java 版的差异**：
- Java 端所有方法都在一个事务里,本实现在每个方法内部独立事务;**调用方**不
  期望 `lifecycle.claim` + `pipeline.process(task)`(后者会调
  `record_parsed_artifact` / `advance`)在同一个事务里——`pipeline.process`
  本来就要在 claim 之后跑得很久,不可能共享事务。
- Java 端 `requireOwnedJob` 用 `SELECT ... FOR UPDATE` 锁;本实现主要靠
  `IngestionJobRepository.claim_if_queued` / `heartbeat` 已有的条件 UPDATE 完成
  fencing,只在 `advance` / `fail` 的 task 形态上额外做一次版本校验
  (attempt + lease_owner 仍属于本 Worker),不主动锁整行。
"""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional, Union
from uuid import UUID

from app.exceptions.errors import ResourceNotFoundException
from app.models.enums import IngestionStatus as DbIngestionStatus
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.ragcore.ingestion.exceptions import StaleIngestionLeaseException
from app.ragcore.ingestion.lifecycle_service import IngestionJobLifecycleService
from app.ragcore.ingestion.state_machine import require_transition
from app.ragcore.ingestion.status import ACTIVE_STATUSES, IngestionStatus
from app.ragcore.ingestion.task import IngestionTask, JobSnapshot
from app.repositories.ingestion_job_repository import IngestionJobRepository
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository

logger = logging.getLogger(__name__)

_MAX_ERROR_MESSAGE_LENGTH = 4_000
_RECOVER_BATCH_LIMIT = 100  # 单次事务处理条数上限;避免长事务


def _now_utc() -> datetime:
    """统一返回 tz-aware UTC `datetime`,与 DB `DateTime(timezone=True)` 对齐。"""
    return datetime.now(tz=timezone.utc)


def _db_status(value: IngestionStatus) -> DbIngestionStatus:
    """把协议层的 IngestionStatus 转成 DB 模型列使用的枚举;两者 value 字符串一致,
    但 Python 类不同,SQLAlchemy 列类型校验需要正确的类型。"""
    return DbIngestionStatus(value.value)


def _truncate_error(message: str) -> str:
    if len(message) <= _MAX_ERROR_MESSAGE_LENGTH:
        return message
    return message[:_MAX_ERROR_MESSAGE_LENGTH]


def _safe_error_message(cause: BaseException | None) -> str:
    if cause is None:
        return "摄取任务失败"
    message = str(cause) or cause.__class__.__name__
    if not message.strip():
        message = cause.__class__.__name__
    return _truncate_error(message)


SessionFactoryT = Callable[[], Union[AbstractAsyncContextManager, Awaitable]]


class SqlAlchemyIngestionJobLifecycleService(IngestionJobLifecycleService):
    def __init__(self, session_factory: Callable[[], AbstractAsyncContextManager]) -> None:
        if session_factory is None:
            raise ValueError("session_factory 不能为空")
        self._session_factory = session_factory

    # ---- claim -------------------------------------------------------

    async def claim(
        self,
        job_id: object,
        worker_id: str | None = None,
        lease_duration: Optional[timedelta] = None,
    ) -> Optional[IngestionTask]:
        if not isinstance(job_id, UUID):
            try:
                job_id = UUID(str(job_id))
            except (TypeError, ValueError) as ex:
                raise ValueError(f"job_id 必须是 UUID,实际收到: {job_id!r}") from ex
        lease_duration = lease_duration or timedelta(minutes=30)
        owner = worker_id or "legacy-worker"
        now = _now_utc()
        lease_expires_at = now + lease_duration

        async with self._session_factory() as session:  # type: ignore[func-returns-value]
            async with session.begin():
                job_repo = IngestionJobRepository(session)
                updated = await job_repo.claim_if_queued(
                    job_id=job_id,
                    expected_status=_db_status(IngestionStatus.QUEUED),
                    next_status=_db_status(IngestionStatus.PARSING),
                    now=now,
                    lease_owner=owner,
                    lease_expires_at=lease_expires_at,
                )
                if updated == 0:
                    return None
                job = await job_repo.find_by_id(job_id)
                if job is None:
                    raise ResourceNotFoundException("摄取任务不存在")
                document = await self._load_document(session, job.document_id)
                document.status = _db_status(IngestionStatus.PARSING)
                return self._to_task(job, document, owner)

    # ---- heartbeat ---------------------------------------------------

    async def heartbeat(
        self, task: IngestionTask, lease_duration: timedelta
    ) -> bool:
        if lease_duration is None:
            lease_duration = timedelta(minutes=30)
        now = _now_utc()
        new_expires_at = now + lease_duration

        async with self._session_factory() as session:  # type: ignore[func-returns-value]
            async with session.begin():
                job_repo = IngestionJobRepository(session)
                updated = await job_repo.heartbeat(
                    job_id=task.job_id,
                    lease_owner=task.lease_owner,
                    attempt=task.attempt,
                    active_statuses=[_db_status(s) for s in ACTIVE_STATUSES],
                    now=now,
                    lease_expires_at=new_expires_at,
                )
                return updated == 1

    # ---- advance -----------------------------------------------------

    async def advance(
        self, target: "object | IngestionTask", next_status: IngestionStatus
    ) -> object:
        if isinstance(target, IngestionTask):
            return await self._advance_owned(target, next_status)
        if not isinstance(target, UUID):
            try:
                target = UUID(str(target))
            except (TypeError, ValueError) as ex:
                raise ValueError(f"target 必须是 UUID 或 IngestionTask,实际收到: {target!r}") from ex
        async with self._session_factory() as session:  # type: ignore[func-returns-value]
            async with session.begin():
                job_repo = IngestionJobRepository(session)
                job = await job_repo.find_by_id(target)
                if job is None:
                    raise ResourceNotFoundException("摄取任务不存在")
                require_transition(IngestionStatus(job.status.value), next_status)
                job.status = _db_status(next_status)
                if next_status == IngestionStatus.READY:
                    job.finished_at = _now_utc()
                    job.error_message = None
                    self._clear_lease(job)
                document = await self._load_document(session, job.document_id)
                document.status = _db_status(next_status)
                return job

    async def _advance_owned(
        self, task: IngestionTask, next_status: IngestionStatus
    ) -> IngestionJob:
        async with self._session_factory() as session:  # type: ignore[func-returns-value]
            async with session.begin():
                job_repo = IngestionJobRepository(session)
                job = await job_repo.find_by_id_for_update(task.job_id)
                if job is None:
                    raise ResourceNotFoundException("摄取任务不存在")
                self._ensure_owned(job, task)
                require_transition(IngestionStatus(job.status.value), next_status)
                job.status = _db_status(next_status)
                if next_status == IngestionStatus.READY:
                    job.finished_at = _now_utc()
                    job.error_message = None
                    self._clear_lease(job)
                document = await self._load_document(session, job.document_id)
                document.status = _db_status(next_status)
                return job

    # ---- fail --------------------------------------------------------

    async def fail(
        self, target: "object | IngestionTask", cause: BaseException
    ) -> object:
        if isinstance(target, IngestionTask):
            return await self._fail_owned(target, cause)
        if not isinstance(target, UUID):
            try:
                target = UUID(str(target))
            except (TypeError, ValueError) as ex:
                raise ValueError(f"target 必须是 UUID 或 IngestionTask,实际收到: {target!r}") from ex
        async with self._session_factory() as session:  # type: ignore[func-returns-value]
            async with session.begin():
                job_repo = IngestionJobRepository(session)
                job = await job_repo.find_by_id_for_update(target)
                if job is None:
                    raise ResourceNotFoundException("摄取任务不存在")
                self._apply_failure(job, cause)
                document = await self._load_document(session, job.document_id)
                self._apply_document_failure(document, job)
                return job

    async def _fail_owned(
        self, task: IngestionTask, cause: BaseException
    ) -> IngestionJob:
        async with self._session_factory() as session:  # type: ignore[func-returns-value]
            async with session.begin():
                job_repo = IngestionJobRepository(session)
                job = await job_repo.find_by_id_for_update(task.job_id)
                if job is None:
                    raise ResourceNotFoundException("摄取任务不存在")
                self._ensure_owned(job, task)
                self._apply_failure(job, cause)
                document = await self._load_document(session, job.document_id)
                self._apply_document_failure(document, job)
                return job

    # ---- record_parsed_artifact --------------------------------------

    async def record_parsed_artifact(
        self,
        target: "object | IngestionTask",
        artifact_path: str,
        parser_name: str,
        parser_version: str,
    ) -> None:
        if not isinstance(target, IngestionTask):
            try:
                target = UUID(str(target))
            except (TypeError, ValueError) as ex:
                raise ValueError(f"target 必须是 IngestionTask 或 UUID,实际收到: {target!r}") from ex
        async with self._session_factory() as session:  # type: ignore[func-returns-value]
            async with session.begin():
                job_repo = IngestionJobRepository(session)
                if isinstance(target, IngestionTask):
                    job = await job_repo.find_by_id_for_update(target.job_id)
                    if job is None:
                        raise ResourceNotFoundException("摄取任务不存在")
                    self._ensure_owned(job, target)
                else:
                    job = await job_repo.find_by_id_for_update(target)
                    if job is None:
                        raise ResourceNotFoundException("摄取任务不存在")
                document = await self._load_document(session, job.document_id)
                document.parse_artifact_path = artifact_path
                document.parser_name = parser_name
                document.parser_version = parser_version
                document.parsed_at = _now_utc()

    # ---- recover_expired_leases --------------------------------------

    async def recover_expired_leases(self) -> int:
        """扫描已过期的活跃任务;达到 max_attempts 的转 FAILED,其余清租约回 QUEUED。

        实现要点：
        - 一次事务内最多处理 `_RECOVER_BATCH_LIMIT` 条,避免长事务(任务多时逐步收敛)。
        - 先 `find_by_status_in_and_lease_expires_at_before` 拉一批,再逐条用条件 UPDATE
          把租约改写;条件不满足(rowcount=0)说明被其他 Worker 抢走,自然跳过。
        - 任何子任务抛 StaleIngestionLeaseException 一律吞掉并当作"已处理"——这
          里做的是清理工作,而不是争抢写入,被接管是预期行为。
        """
        now = _now_utc()
        recovered = 0

        async with self._session_factory() as session:  # type: ignore[func-returns-value]
            async with session.begin():
                job_repo = IngestionJobRepository(session)
                candidates = await job_repo.find_by_status_in_and_lease_expires_at_before(
                    [_db_status(s) for s in ACTIVE_STATUSES], now
                )
                candidates = candidates[:_RECOVER_BATCH_LIMIT]
                for job in candidates:
                    try:
                        if job.attempt >= job.max_attempts:
                            message = "摄取 Worker 租约过期,已达到最大尝试次数"
                            updated = await job_repo.fail_expired_lease(
                                job_id=job.id,
                                active_statuses=[_db_status(s) for s in ACTIVE_STATUSES],
                                failed_status=_db_status(IngestionStatus.FAILED),
                                error_message=message,
                                now=now,
                            )
                            if updated == 1:
                                # 同步内存中的 job / document 状态;SQLAlchemy ORM 对象在
                                # session 关闭后不会自动反映已经通过条件 UPDATE 落库的变化,
                                # 这里显式改 in-memory 副本便于测试与同事务内的后续读取一致。
                                job.status = _db_status(IngestionStatus.FAILED)
                                job.error_message = message
                                job.finished_at = now
                                job.lease_owner = None
                                job.lease_expires_at = None
                                job.last_heartbeat_at = None
                                document = await self._load_document(session, job.document_id)
                                document.status = _db_status(IngestionStatus.FAILED)
                                document.last_error = message
                                document.last_error_at = now
                                recovered += 1
                        else:
                            updated = await job_repo.requeue_expired_lease(
                                job_id=job.id,
                                active_statuses=[_db_status(s) for s in ACTIVE_STATUSES],
                                queued_status=_db_status(IngestionStatus.QUEUED),
                                now=now,
                            )
                            if updated == 1:
                                job.status = _db_status(IngestionStatus.QUEUED)
                                job.lease_owner = None
                                job.lease_expires_at = None
                                job.last_heartbeat_at = None
                                job.started_at = None
                                document = await self._load_document(session, job.document_id)
                                document.status = _db_status(IngestionStatus.QUEUED)
                                recovered += 1
                    except StaleIngestionLeaseException:
                        # 被并发 Worker 接管,本轮跳过
                        logger.debug("租约回收时被接管,跳过 jobId=%s", job.id)
                        continue
                    except Exception as ex:  # noqa: BLE001
                        logger.warning(
                            "租约回收失败,jobId=%s: %s", job.id, ex
                        )
                        continue
        if recovered:
            logger.info("已回收 %d 个过期摄取任务租约", recovered)
        return recovered

    # ---- retry -------------------------------------------------------

    async def retry(self, job_id: object) -> JobSnapshot:
        if not isinstance(job_id, UUID):
            try:
                job_id = UUID(str(job_id))
            except (TypeError, ValueError) as ex:
                raise ValueError(f"job_id 必须是 UUID,实际收到: {job_id!r}") from ex
        async with self._session_factory() as session:  # type: ignore[func-returns-value]
            async with session.begin():
                job_repo = IngestionJobRepository(session)
                job = await job_repo.find_by_id_for_update(job_id)
                if job is None:
                    raise ResourceNotFoundException("摄取任务不存在")
                if IngestionStatus(job.status.value) != IngestionStatus.FAILED:
                    raise ValueError("仅失败的摄取任务可以重试")
                if job.attempt >= job.max_attempts:
                    raise ValueError("摄取任务已达到最大重试次数")
                require_transition(IngestionStatus.FAILED, IngestionStatus.QUEUED)
                job.status = _db_status(IngestionStatus.QUEUED)
                job.error_message = None
                job.started_at = None
                job.finished_at = None
                self._clear_lease(job)
                document = await self._load_document(session, job.document_id)
                document.status = _db_status(IngestionStatus.QUEUED)
                document.retry_count = (document.retry_count or 0) + 1
                document.last_error = None
                document.last_error_at = None
            # session.begin() 块退出时已 commit;此时 session 仍未关闭,显式 refresh
            # 拿到 DB 端 onupdate 生成的真实 updated_at,再把值抽成 dataclass——不能像
            # `advance`/`fail` 那样直接 `return job`:调用方会在 session 关闭后访问
            # job.updated_at,任何属性访问触发懒加载都会抛 DetachedInstanceError。
            await session.refresh(job)
            return JobSnapshot(
                id=job.id,
                document_id=job.document_id,
                kb_id=job.kb_id,
                status=IngestionStatus(job.status.value),
                error_message=job.error_message,
                max_attempts=job.max_attempts,
                attempt=job.attempt,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )

    # ---- helpers -----------------------------------------------------

    @staticmethod
    def _to_task(
        job: IngestionJob, document: KnowledgeDocument, owner_fallback: str
    ) -> IngestionTask:
        return IngestionTask(
            job_id=job.id,
            attempt=job.attempt,
            lease_owner=job.lease_owner or owner_fallback,
            document_id=job.document_id,
            organization_id=job.org_id,
            knowledge_base_id=job.kb_id,
            filename=document.name or "",
            content_type=document.content_type,
            object_storage_path=document.object_storage_path or "",
            parse_artifact_path=document.parse_artifact_path,
            parser_version=document.parser_version,
        )

    @staticmethod
    def _clear_lease(job: IngestionJob) -> None:
        job.lease_owner = None
        job.lease_expires_at = None
        job.last_heartbeat_at = None

    @staticmethod
    def _ensure_owned(job: IngestionJob, task: IngestionTask) -> None:
        """fencing: 检查 attempt + lease_owner + 租约未过期,任一不匹配就抛
        StaleIngestionLeaseException,阻止旧 Worker 写覆盖新 Worker 已接管的行。"""
        if job.attempt != task.attempt:
            raise StaleIngestionLeaseException(
                f"摄取任务 attempt 已变更(本任务={task.attempt}, 当前={job.attempt}): "
                f"jobId={task.job_id}"
            )
        if job.lease_owner != task.lease_owner:
            raise StaleIngestionLeaseException(
                f"摄取任务 lease_owner 已变更(本任务={task.lease_owner}, "
                f"当前={job.lease_owner}): jobId={task.job_id}"
            )
        if job.lease_expires_at is None or job.lease_expires_at <= _now_utc():
            raise StaleIngestionLeaseException(
                f"摄取任务租约已过期(本任务 expires_at={job.lease_expires_at}): "
                f"jobId={task.job_id}"
            )

    @staticmethod
    def _apply_failure(job: IngestionJob, cause: BaseException) -> None:
        # DELETING 优先级更高 —— 删除请求已下达,旧 Worker 不能改回 FAILED
        if job.status == _db_status(IngestionStatus.DELETING):
            return
        if job.status != _db_status(IngestionStatus.FAILED):
            require_transition(
                IngestionStatus(job.status.value), IngestionStatus.FAILED
            )
            job.status = _db_status(IngestionStatus.FAILED)
        message = _safe_error_message(cause)
        job.error_message = message
        job.finished_at = _now_utc()
        SqlAlchemyIngestionJobLifecycleService._clear_lease(job)

    @staticmethod
    def _apply_document_failure(
        document: KnowledgeDocument, job: IngestionJob
    ) -> None:
        document.status = _db_status(IngestionStatus.FAILED)
        document.last_error = job.error_message
        document.last_error_at = job.finished_at

    @staticmethod
    async def _load_document(
        session, document_id: UUID
    ) -> KnowledgeDocument:
        doc_repo = KnowledgeDocumentRepository(session)
        document = await doc_repo.find_by_id(document_id)
        if document is None:
            raise ResourceNotFoundException("文档不存在")
        return document
