"""`SqlAlchemyIngestionJobLifecycleService` 单元测试。

聚焦在**协议符合性 + 入参解析 + 状态机/边界保护**等纯逻辑分支;
完整 SQL 行为是 Flyway 集成测试范畴(需要真实 PostgreSQL),这里不做。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.ragcore.ingestion.exceptions import StaleIngestionLeaseException
from app.ragcore.ingestion.lifecycle_service import IngestionJobLifecycleService
from app.ragcore.ingestion.sqlalchemy_lifecycle_service import (
    SqlAlchemyIngestionJobLifecycleService,
    _db_status,
    _safe_error_message,
    _truncate_error,
)
from app.ragcore.ingestion.status import IngestionStatus
from app.ragcore.ingestion.task import IngestionTask


class _FakeAsyncCtx:
    """最小的 async context manager,用于 `session.begin()` 的返回值。"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _empty_execute_result() -> MagicMock:
    result = MagicMock()
    result.rowcount = 0
    result.scalar_one_or_none.return_value = None
    scalars = MagicMock()
    scalars.all.return_value = []
    result.scalars.return_value = scalars
    return result


@asynccontextmanager
async def _empty_session_cm():
    """最小 AsyncSession 替身:支持 `async with session.begin()` 与 `await session.execute(...)`。
    """
    begin = MagicMock(return_value=_FakeAsyncCtx())
    execute = AsyncMock(return_value=_empty_execute_result())
    session = MagicMock()
    session.begin = begin
    session.execute = execute
    yield session


def _build_service() -> SqlAlchemyIngestionJobLifecycleService:
    return SqlAlchemyIngestionJobLifecycleService(session_factory=_empty_session_cm)


# ---- 协议 / 构造 ---------------------------------------------------------


class TestProtocolConformance:
    def test_implements_lifecycle_service_protocol(self):
        """实现类必须能被 `runtime_checkable` Protocol 识别——HTTP router 与
        IngestionWorker 都是按 Protocol 装配的,这条契约断了整个链路就接不上。"""
        assert isinstance(_build_service(), IngestionJobLifecycleService)


class TestConstructorValidation:
    def test_session_factory_required(self):
        with pytest.raises(ValueError, match="session_factory"):
            SqlAlchemyIngestionJobLifecycleService(session_factory=None)  # type: ignore[arg-type]


# ---- 入参解析 ------------------------------------------------------------


class TestDbStatusConversion:
    def test_db_status_round_trip(self):
        """协议层 `IngestionStatus` 与 DB 列使用的枚举 value 必须一致。"""
        for status in IngestionStatus:
            assert _db_status(status).value == status.value


# ---- 错误消息处理 -------------------------------------------------------


class TestErrorMessageTruncation:
    def test_truncate_long_message(self):
        assert len(_truncate_error("x" * 5_000)) == 4_000

    def test_short_message_kept(self):
        assert _truncate_error("simple") == "simple"

    def test_safe_error_message_empty_cause(self):
        assert _safe_error_message(None) == "摄取任务失败"

    def test_safe_error_message_empty_str_uses_class_name(self):
        class _Empty:
            def __str__(self) -> str:
                return ""

        assert _safe_error_message(_Empty()) == "_Empty"

    def test_safe_error_message_long_truncated(self):
        cause = RuntimeError("x" * 10_000)
        assert len(_safe_error_message(cause)) == 4_000


# ---- 状态机保护 ----------------------------------------------------------


class TestFencingEnforced:
    """`_ensure_owned` 静态方法做 fencing:attempt / lease_owner / lease_expires_at
    任何一个不匹配都抛 StaleIngestionLeaseException,阻止旧 Worker 覆盖新 Worker
    已经接管的行。这是 Worker 安全的最后一道防线,必须严格。"""

    def _make_task(
        self,
        *,
        attempt: int = 1,
        lease_owner: str = "worker-1",
        lease_expires_at: datetime | None = None,
    ) -> IngestionTask:
        return IngestionTask(
            job_id=uuid4(),
            attempt=attempt,
            lease_owner=lease_owner,
            document_id=uuid4(),
            organization_id=uuid4(),
            knowledge_base_id=uuid4(),
            filename="doc.txt",
            content_type="text/plain",
            object_storage_path="key",
            parse_artifact_path=None,
            parser_version=None,
        )

    def _make_job_like(
        self,
        *,
        attempt: int,
        lease_owner: str | None,
        lease_expires_at: datetime | None,
    ):
        job = MagicMock()
        job.id = uuid4()
        job.attempt = attempt
        job.lease_owner = lease_owner
        job.lease_expires_at = lease_expires_at
        return job

    def test_ensure_owned_accepts_matching_lease(self):
        future = datetime.now(tz=timezone.utc) + timedelta(minutes=5)
        task = self._make_task(attempt=1, lease_owner="w1", lease_expires_at=future)
        job = self._make_job_like(attempt=1, lease_owner="w1", lease_expires_at=future)
        SqlAlchemyIngestionJobLifecycleService._ensure_owned(job, task)

    def test_attempt_mismatch_raises_stale(self):
        future = datetime.now(tz=timezone.utc) + timedelta(minutes=5)
        task = self._make_task(attempt=1, lease_owner="w1", lease_expires_at=future)
        job = self._make_job_like(attempt=2, lease_owner="w1", lease_expires_at=future)
        with pytest.raises(StaleIngestionLeaseException, match="attempt"):
            SqlAlchemyIngestionJobLifecycleService._ensure_owned(job, task)

    def test_lease_owner_mismatch_raises_stale(self):
        future = datetime.now(tz=timezone.utc) + timedelta(minutes=5)
        task = self._make_task(attempt=1, lease_owner="w1", lease_expires_at=future)
        job = self._make_job_like(attempt=1, lease_owner="w2", lease_expires_at=future)
        with pytest.raises(StaleIngestionLeaseException, match="lease_owner"):
            SqlAlchemyIngestionJobLifecycleService._ensure_owned(job, task)

    def test_expired_lease_raises_stale(self):
        past = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
        task = self._make_task(attempt=1, lease_owner="w1", lease_expires_at=past)
        job = self._make_job_like(attempt=1, lease_owner="w1", lease_expires_at=past)
        with pytest.raises(StaleIngestionLeaseException, match="已过期"):
            SqlAlchemyIngestionJobLifecycleService._ensure_owned(job, task)

    def test_no_lease_raises_stale(self):
        """lease_expires_at 是 None → 视为已过期(从未续租 / 已清空)。"""
        task = self._make_task(attempt=1, lease_owner="w1", lease_expires_at=None)
        job = self._make_job_like(attempt=1, lease_owner="w1", lease_expires_at=None)
        with pytest.raises(StaleIngestionLeaseException):
            SqlAlchemyIngestionJobLifecycleService._ensure_owned(job, task)


# ---- 入参校验 ------------------------------------------------------------


class TestClaimInputValidation:
    @pytest.mark.asyncio
    async def test_claim_rejects_non_uuid_string(self):
        """非 UUID 字符串在进入 SQL 之前先抛 ValueError。"""
        with pytest.raises(ValueError, match="UUID"):
            await _build_service().claim("not-a-uuid", worker_id="w1")


class TestRetryInputValidation:
    @pytest.mark.asyncio
    async def test_retry_rejects_non_uuid_string(self):
        with pytest.raises(ValueError, match="UUID"):
            await _build_service().retry("not-a-uuid")


class TestTargetValidation:
    @pytest.mark.asyncio
    async def test_advance_rejects_non_uuid_non_task(self):
        with pytest.raises(ValueError, match="UUID 或 IngestionTask"):
            await _build_service().advance("not-a-uuid", IngestionStatus.PARSING)

    @pytest.mark.asyncio
    async def test_fail_rejects_non_uuid_non_task(self):
        with pytest.raises(ValueError, match="UUID 或 IngestionTask"):
            await _build_service().fail("not-a-uuid", RuntimeError("x"))


# ---- recover_expired_leases 边界保护 --------------------------------------


class TestRecoverExpiredLeases:
    @pytest.mark.asyncio
    async def test_recover_returns_zero_when_no_candidates(self):
        """空 session 工厂 → SELECT 拉不到候选 → 返回 0。"""
        recovered = await _build_service().recover_expired_leases()
        assert recovered == 0
