"""为迁移前存量 Chunk 回填 `retrieval_ready`;显式调用,不在普通启动路径自动执行。

对应 Java 版 `ragcore/index/ElasticsearchVisibilityBackfill.java`。双端可见性闸门
(`retrieval_ready`)上线前写入 `rag_chunks_v1` 的存量 Chunk 没有该字段,一律视为已发布,
按需批量回填为 `true`,避免历史数据因为缺字段而在新的可见性校验下被误判为不可检索。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from elasticsearch import AsyncElasticsearch

from app.core.config import Settings
from app.core.config import settings as default_settings
from app.ragcore.index.exceptions import ElasticsearchIndexException

logger = logging.getLogger(__name__)

_MISSING_QUERY: dict = {"bool": {"must_not": [{"exists": {"field": "retrieval_ready"}}]}}


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """回填结果统计。对应 Java 版 `ElasticsearchVisibilityBackfill.BackfillResult`。"""

    dry_run: bool
    missing_before: int
    updated: int
    missing_after: int


class ElasticsearchVisibilityBackfill:
    """为存量 Chunk 回填 `retrieval_ready=true`。对应 Java 版同名类。"""

    def __init__(
        self,
        es_client: AsyncElasticsearch,
        cfg: Settings | None = None,
        index_name: str | None = None,
    ) -> None:
        self._es = es_client
        cfg = cfg or default_settings
        self._index_name = index_name or cfg.rag_es_index_name

    async def run(self, dry_run: bool, batch_size: int, max_attempts: int) -> BackfillResult:
        """执行(或仅统计)回填。对应 Java 版 `run(dryRun, batchSize, maxAttempts)`。

        `dry_run=True` 或当前无缺失字段的 Chunk 时,只统计不写入。
        """
        if batch_size <= 0 or max_attempts <= 0:
            raise ValueError("回填 batch_size 与 max_attempts 必须为正数")

        before = await self._count_missing()
        if dry_run or before == 0:
            return BackfillResult(dry_run, before, 0, before)

        await self._ensure_mapping()
        response = await self._perform_with_retry(batch_size, max_attempts)
        failures = response.get("failures") or []
        if failures:
            raise ElasticsearchIndexException("ES retrieval_ready 回填存在分项失败")
        updated = int(response.get("updated", 0))
        remaining = await self._count_missing()
        return BackfillResult(False, before, updated, remaining)

    # ---- 内部实现 --------------------------------------------------------

    async def _count_missing(self) -> int:
        try:
            response = await self._es.count(index=self._index_name, query=_MISSING_QUERY)
        except Exception as ex:  # noqa: BLE001 - 统一包装为可识别异常
            raise ElasticsearchIndexException("统计缺失 retrieval_ready 的 Chunk 失败") from ex
        return int(response.get("count", 0))

    async def _ensure_mapping(self) -> None:
        try:
            await self._es.indices.put_mapping(
                index=self._index_name, properties={"retrieval_ready": {"type": "boolean"}}
            )
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("创建 retrieval_ready mapping 失败") from ex

    async def _perform_with_retry(self, batch_size: int, max_attempts: int):
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await self._es.update_by_query(
                    index=self._index_name,
                    conflicts="proceed",
                    refresh=True,
                    scroll_size=batch_size,
                    script={"source": "ctx._source.retrieval_ready = true", "lang": "painless"},
                    query=_MISSING_QUERY,
                )
            except Exception as ex:  # noqa: BLE001
                last_error = ex
                logger.warning("ES retrieval_ready 回填第 %d/%d 次尝试失败", attempt, max_attempts, exc_info=ex)
        raise ElasticsearchIndexException("ES retrieval_ready 回填重试耗尽") from last_error
