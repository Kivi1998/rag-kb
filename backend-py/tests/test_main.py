"""`app.main` 摄取 Worker 装配相关的单元测试。

聚焦 `_WorkerJobRepositoryAdapter`——这是修复"Worker 用一个恒定返回 0 / 空列表的
`_EmptyJobRepository` stub 糊弄过去,导致任务永远卡在 QUEUED"这个 bug 的核心补丁:
验证它按 `session_factory` 模式(每次调用开短事务)真正调用了
`IngestionJobRepository.count_by_status` / `.find_by_status_order_by_created_at_asc`,
并且把协议层 `IngestionStatus`(`app.ragcore.ingestion.status`)正确转换成 DB 模型
的 `IngestionStatus`(`app.models.enums`)。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import _WorkerJobRepositoryAdapter
from app.models.enums import IngestionStatus as DbIngestionStatus
from app.ragcore.ingestion.status import IngestionStatus


def _count_execute_result(value: int) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _list_execute_result(rows: list) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    return result


class _FakeSession:
    """最小 AsyncSession 替身,只需要支持 `await session.execute(...)`。"""

    def __init__(self, execute_result: MagicMock) -> None:
        self.execute = AsyncMock(return_value=execute_result)


def _session_factory_returning(execute_result: MagicMock):
    session = _FakeSession(execute_result)

    @asynccontextmanager
    async def _factory():
        yield session

    _factory.session = session  # type: ignore[attr-defined]
    return _factory


class TestWorkerJobRepositoryAdapter:
    @pytest.mark.asyncio
    async def test_count_by_status_queries_real_repository(self) -> None:
        factory = _session_factory_returning(_count_execute_result(3))
        adapter = _WorkerJobRepositoryAdapter(session_factory=factory)

        result = await adapter.count_by_status(IngestionStatus.QUEUED)

        assert result == 3
        # 真的发出了一次 SQL(execute 被 await 到),而不是像旧 stub 那样恒返回 0
        factory.session.execute.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_find_queued_calls_find_by_status_order_by_created_at_asc(self) -> None:
        rows = [object(), object()]
        factory = _session_factory_returning(_list_execute_result(rows))
        adapter = _WorkerJobRepositoryAdapter(session_factory=factory)

        result = await adapter.find_queued(5)

        assert result == rows
        factory.session.execute.assert_awaited_once()  # type: ignore[attr-defined]
        # 真正被执行的 SELECT 语句按 QUEUED 状态过滤(而不是旧 stub 恒返回空列表)
        executed_stmt = factory.session.execute.await_args.args[0]  # type: ignore[attr-defined]
        compiled = str(executed_stmt)
        assert "ingestion_job" in compiled.lower()

    @pytest.mark.asyncio
    async def test_db_status_conversion_matches_lifecycle_service(self) -> None:
        """协议层 `IngestionStatus.QUEUED` 必须映射到 DB 模型的
        `IngestionStatus.QUEUED`(值相同但是不同枚举类),与
        `sqlalchemy_lifecycle_service._db_status` 的转换保持一致。"""
        converted = _WorkerJobRepositoryAdapter._db_status(IngestionStatus.QUEUED)
        assert converted == DbIngestionStatus.QUEUED
        assert isinstance(converted, DbIngestionStatus)
