"""对 DELETING 文档执行幂等清理,覆盖 ES 或对象存储的短暂失败。

对应 Java 版 `ragcore/ingestion/DocumentDeletionWorker.java`。
"""

from __future__ import annotations

import asyncio
import logging

from app.ragcore.ingestion.deletion_service import DocumentDeletionService

logger = logging.getLogger(__name__)

DEFAULT_BATCH_LIMIT: int = 20
DEFAULT_POLL_INTERVAL_SECONDS: float = 30.0


async def run_deletion_cleanup_loop(
    deletion_service: DocumentDeletionService,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
) -> None:
    """每 `poll_interval_seconds` 跑一次 `pending_deletion_ids` + `cleanup`,
    直到 `stop_event` 触发。"""
    stop_event = stop_event or asyncio.Event()
    while not stop_event.is_set():
        try:
            ids = await deletion_service.pending_deletion_ids(batch_limit)
            for doc_id in ids:
                ok = await deletion_service.cleanup(doc_id)
                if not ok:
                    logger.debug("文档删除补偿未完成,下一轮重试, documentId=%s", doc_id)
        except Exception as ex:  # noqa: BLE001
            logger.warning("文档删除补偿循环失败,下一周期重试: %s", ex)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except asyncio.TimeoutError:
            pass
