"""轻量数据库任务表 Worker。

对应 Java 版 `ragcore/ingestion/IngestionWorker.java`。
多个实例可并行轮询,实际领取由条件更新保证一次只有一个实例成功。
T107 注入实际 Pipeline 后才会创建此调度入口,避免将尚未接入索引的文档错误标记 READY。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Awaitable, Callable, Optional, Protocol

from app.ragcore.ingestion.exceptions import StaleIngestionLeaseException
from app.ragcore.ingestion.lifecycle_service import IngestionJobLifecycleService
from app.ragcore.ingestion.metrics import IngestionMetrics
from app.ragcore.ingestion.pipeline import DocumentIngestionPipeline
from app.ragcore.ingestion.status import IngestionStatus

logger = logging.getLogger(__name__)


class _QueuedJob(Protocol):
    """`jobRepository.findByStatusOrderByCreatedAtAsc` 返回的最小投影。"""

    @property
    def id(self) -> object: ...


class _JobRepository(Protocol):
    async def count_by_status(self, status: IngestionStatus) -> int: ...
    async def find_queued(self, limit: int) -> list[_QueuedJob]: ...


class IngestionWorker:
    def __init__(
        self,
        job_repository: _JobRepository,
        lifecycle_service: IngestionJobLifecycleService,
        pipeline: DocumentIngestionPipeline,
        metrics: IngestionMetrics,
        worker_id: str,
        concurrency: int = 4,
        batch_size: int = 16,
        lease_duration_ms: int = 30 * 60 * 1000,
        poll_interval_seconds: float = 1.0,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        self._repo = job_repository
        self._lifecycle = lifecycle_service
        self._pipeline = pipeline
        self._metrics = metrics
        self._worker_id = worker_id
        self._concurrency = max(1, concurrency)
        self._batch_size = max(1, batch_size)
        self._lease_duration = timedelta(milliseconds=lease_duration_ms)
        self._poll_interval = poll_interval_seconds
        self._stop = stop_event or asyncio.Event()

    async def run(self) -> None:
        """长循环: 周期轮询 + 处理 + 心跳。FastAPI lifespan 里 `asyncio.create_task(self.run())` 启动。"""
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except Exception as ex:  # noqa: BLE001
                logger.warning("摄取 worker 轮询异常,下一周期重试: %s", ex)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()

    async def poll_once(self) -> None:
        recovered = await self._lifecycle.recover_expired_leases()
        if recovered:
            logger.warning("已恢复 %d 个过期摄取任务租约", recovered)
        try:
            self._metrics.queue_depth(
                await self._repo.count_by_status(IngestionStatus.QUEUED)
            )
        except Exception as ex:  # noqa: BLE001
            logger.debug("queue depth 采集失败: %s", ex)
        available = self._concurrency - self._metrics.in_flight()
        if available <= 0:
            return
        dispatch_count = min(available, self._batch_size)
        try:
            queued = await self._repo.find_queued(dispatch_count)
        except Exception as ex:  # noqa: BLE001
            logger.debug("find_queued 失败: %s", ex)
            return
        for job in queued:
            await self._submit(job)

    async def _submit(self, job: _QueuedJob) -> None:
        self._metrics.increment_in_flight()
        try:
            await self._process(job)
        finally:
            self._metrics.decrement_in_flight()

    async def _process(self, job: _QueuedJob) -> None:
        task = await self._lifecycle.claim(
            job.id, self._worker_id, self._lease_duration
        )
        if task is None:
            return  # 已被其他 Worker 抢先
        heartbeat_task = self._start_heartbeat(task)
        try:
            await self._pipeline.process(task)
        except StaleIngestionLeaseException as ex:
            logger.warning(
                "摄取任务租约已被接管,旧 Worker 停止写入: jobId=%s, attempt=%d, workerId=%s",
                task.job_id, task.attempt, task.lease_owner,
            )
        except Exception as ex:  # noqa: BLE001
            logger.warning(
                "摄取任务失败: jobId=%s, documentId=%s, attempt=%d: %s",
                task.job_id, task.document_id, task.attempt, ex,
            )
            await self._fail_if_still_owned(task, ex)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    def _start_heartbeat(self, task) -> asyncio.Task:
        interval = max(1.0, self._lease_duration.total_seconds() / 3.0)

        async def _beat() -> None:
            try:
                while True:
                    await asyncio.sleep(interval)
                    try:
                        ok = await self._lifecycle.heartbeat(task, self._lease_duration)
                        if not ok:
                            logger.warning(
                                "摄取任务续租失败,任务可能已被取消或接管, jobId=%s",
                                task.job_id,
                            )
                            return
                    except Exception as ex:  # noqa: BLE001
                        logger.warning("摄取任务心跳异常: %s", ex)
            except asyncio.CancelledError:
                return

        return asyncio.create_task(_beat())

    async def _fail_if_still_owned(self, task, cause: BaseException) -> None:
        try:
            await self._lifecycle.fail(task, cause)
        except StaleIngestionLeaseException:
            logger.warning(
                "任务失败时租约已被接管,不覆盖新 Worker 状态, jobId=%s", task.job_id
            )
