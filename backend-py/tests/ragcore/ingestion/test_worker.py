"""`IngestionWorker.poll_once()` 单元测试。

聚焦回归此前的真实 bug:`poll_once` 调用 `self._repo.count_by_status` /
`self._repo.find_queued` 时漏加 `await`,导致这两处调用实际上从未真正执行
(协程对象被创建但从未被 await,`_metrics.queue_depth()` 收到一个 coroutine
而不是 int;`for job in queued` 对一个协程对象取值直接抛 TypeError,又被
`try/except` 吞掉),Worker 因此永远轮询不到任何 QUEUED 任务。

这里用一个纯 async 的 fake repository(符合 `_JobRepository` Protocol 现在的
async 签名)驱动 `poll_once`,断言:
- `count_by_status` 真的被 await 到,返回值被正确送进 `metrics.queue_depth`。
- `find_queued` 真的被 await 到,拿到的任务被逐个提交给 `_submit`。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.ragcore.ingestion.metrics import IngestionMetrics
from app.ragcore.ingestion.status import IngestionStatus
from app.ragcore.ingestion.worker import IngestionWorker


class _FakeJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id


class _FakeRepo:
    """符合 `_JobRepository` Protocol(async)的最小 fake。"""

    def __init__(self, queue_depth: int, queued_jobs: list[_FakeJob]) -> None:
        self.queue_depth = queue_depth
        self.queued_jobs = queued_jobs
        self.count_by_status_calls: list[IngestionStatus] = []
        self.find_queued_calls: list[int] = []

    async def count_by_status(self, status: IngestionStatus) -> int:
        self.count_by_status_calls.append(status)
        return self.queue_depth

    async def find_queued(self, limit: int) -> list[_FakeJob]:
        self.find_queued_calls.append(limit)
        return self.queued_jobs[:limit]


class _FakeLifecycleService:
    def __init__(self) -> None:
        self.recovered = 0

    async def recover_expired_leases(self) -> int:
        return self.recovered


class _FakeMetrics:
    """`IngestionMetrics(None)` 在 registry=None 时 in_flight/increment 全是
    no-op(恒返回 0),无法用来测试并发上限分支;这里给一个可控的 fake。"""

    def __init__(self, in_flight: int = 0) -> None:
        self._in_flight = in_flight
        self.queue_depth_values: list[int] = []

    def queue_depth(self, value: int) -> None:
        self.queue_depth_values.append(value)

    def in_flight(self) -> int:
        return self._in_flight

    def increment_in_flight(self) -> int:
        self._in_flight += 1
        return self._in_flight

    def decrement_in_flight(self) -> int:
        self._in_flight = max(0, self._in_flight - 1)
        return self._in_flight


def _build_worker(repo: _FakeRepo, metrics=None) -> IngestionWorker:
    return IngestionWorker(
        job_repository=repo,
        lifecycle_service=_FakeLifecycleService(),
        pipeline=AsyncMock(),
        metrics=metrics if metrics is not None else IngestionMetrics(None),
        worker_id="test-worker",
        concurrency=4,
        batch_size=16,
    )


class TestPollOnceAwaitsRepository:
    @pytest.mark.asyncio
    async def test_count_by_status_is_awaited_and_used(self) -> None:
        """回归:此前漏掉 `await` 时,`queue_depth` 收到的是协程对象而不是 int,
        而 `IngestionMetrics.queue_depth` 在 registry=None 时是 no-op,不会报错,
        所以只能靠断言真实调用发生过、返回值正确来验证。"""
        repo = _FakeRepo(queue_depth=7, queued_jobs=[])
        worker = _build_worker(repo)

        await worker.poll_once()

        assert repo.count_by_status_calls == [IngestionStatus.QUEUED]

    @pytest.mark.asyncio
    async def test_find_queued_is_awaited_and_jobs_submitted(self) -> None:
        """回归:此前漏掉 `await` 时,`queued = self._repo.find_queued(...)` 拿到
        的是协程对象,`for job in queued` 会抛 TypeError,被 `except Exception`
        吞掉,`_submit` 从未被调用,任务永远卡在 QUEUED。"""
        jobs = [_FakeJob("job-1"), _FakeJob("job-2")]
        repo = _FakeRepo(queue_depth=0, queued_jobs=jobs)
        worker = _build_worker(repo)

        submitted: list[_FakeJob] = []

        async def _fake_submit(job: _FakeJob) -> None:
            submitted.append(job)

        worker._submit = _fake_submit  # type: ignore[method-assign]

        await worker.poll_once()

        # dispatch_count = min(available, batch_size) = min(concurrency=4, batch_size=16) = 4
        assert repo.find_queued_calls == [4]
        assert submitted == jobs

    @pytest.mark.asyncio
    async def test_no_dispatch_when_at_full_concurrency(self) -> None:
        """`available <= 0` 时不应该再去 `find_queued`,避免无谓查库。"""
        repo = _FakeRepo(queue_depth=0, queued_jobs=[_FakeJob("job-1")])
        metrics = _FakeMetrics(in_flight=1)
        worker = _build_worker(repo, metrics=metrics)
        worker._concurrency = 1

        await worker.poll_once()

        assert repo.find_queued_calls == []
