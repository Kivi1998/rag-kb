"""低优先级定期清理:物理删除长期未访问且重要度低的画像条目。

对应 Java 版 `ragcore/conversation/impl/MemoryCleanupTask.java`。
纯空间优化,即使这个任务从未运行,检索结果依然正确(低权重条目本来就排不进
top-K)。

Python 版改用 `asyncio.create_task` 配合 sleep 循环,避免额外引入 APScheduler
等调度框架——本项目目前用 FastAPI 启动期 lifespan + 后台任务模式统一调度。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.ragcore.memory.memory_item_store import MemoryItemStore

logger = logging.getLogger(__name__)

CLEANUP_IMPORTANCE_THRESHOLD: float = 0.05
DEFAULT_INTERVAL_SECONDS: int = 24 * 60 * 60  # 24 小时


async def run_cleanup_loop(
    memory_item_store: MemoryItemStore,
    decay_half_life_days: int,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
) -> None:
    """每 `interval_seconds` 跑一次 `cleanup_stale`,直到 `stop_event` 触发。

    启动方式: 在 FastAPI lifespan 里 `asyncio.create_task(run_cleanup_loop(...))`,
    关闭时 `stop_event.set()` 通知退出。
    """
    stop_event = stop_event or asyncio.Event()
    while not stop_event.is_set():
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=3 * decay_half_life_days)
            deleted = await memory_item_store.cleanup_stale(
                cutoff, CLEANUP_IMPORTANCE_THRESHOLD
            )
            if deleted > 0:
                logger.info("画像记忆定期清理完成,删除 %d 条长期低权重条目", deleted)
        except Exception as ex:  # noqa: BLE001
            logger.warning("画像记忆定期清理失败,下一周期重试: %s", ex)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
