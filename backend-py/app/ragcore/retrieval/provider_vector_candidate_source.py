"""服务端固定的向量 Provider、影子读和回退链;调用方不能按请求覆盖模式。

对应 Java 版 `ragcore/retrieval/ProviderVectorCandidateSource.java`。
三模式(读 `settings.rag_vector_provider`):
  * `elasticsearch`: 直接走 ES kNN,失败时返回空列表(BM25-only 降级)。
  * `shadow`: ES 主读,异步触发 Milvus 影子读用于指标对比,影子读失败不影响主链路。
  * `milvus`: 主走 Milvus,失败时若 `rag_vector_fallback_to_es=true` 回退到 ES,
    ES 也失败时返回空列表(BM25-only 降级)。
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import cast

from app.ragcore.retrieval.vector_candidate_source import VectorCandidateSource
from app.ragcore.retrieval.vector_hit import VectorHit
from app.ragcore.retrieval.vector_retrieval_metrics import VectorRetrievalMetrics
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest

logger = logging.getLogger(__name__)

PROVIDER_ELASTICSEARCH: str = "elasticsearch"
PROVIDER_SHADOW: str = "shadow"
PROVIDER_MILVUS: str = "milvus"
VALID_PROVIDERS: frozenset[str] = frozenset({PROVIDER_ELASTICSEARCH, PROVIDER_SHADOW, PROVIDER_MILVUS})

FALLBACK_ES_TO_BM25: str = "elasticsearch_to_bm25"
FALLBACK_MILVUS_AND_ES_TO_BM25: str = "milvus_and_elasticsearch_to_bm25"
FALLBACK_SHADOW_TIMEOUT: str = "shadow_timeout_or_failure"


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """从 settings 派生的 Provider 路由器配置,避免在执行路径里反复读全局对象。"""

    provider: str
    fallback_to_elasticsearch: bool
    shadow_timeout_ms: int
    shadow_sample_rate: float


class ProviderVectorCandidateSource(VectorCandidateSource):
    """三模式切流与回退链实现。"""

    def __init__(
        self,
        elasticsearch_source: VectorCandidateSource,
        milvus_source: VectorCandidateSource | None,
        config: ProviderConfig,
        metrics: VectorRetrievalMetrics | None,
    ) -> None:
        self._es = elasticsearch_source
        self._milvus = milvus_source
        self._config = config
        self._metrics = metrics or VectorRetrievalMetrics(None)

        if config.provider not in VALID_PROVIDERS:
            raise ValueError(
                f"rag_vector_provider 取值非法: {config.provider!r},"
                f" 必须是 {sorted(VALID_PROVIDERS)} 之一"
            )
        if config.provider in (PROVIDER_SHADOW, PROVIDER_MILVUS) and milvus_source is None:
            raise ValueError(f"{config.provider} 模式必须提供 Milvus 向量候选源")

    # ---- VectorCandidateSource -------------------------------------------

    async def search(self, request: VectorSearchRequest) -> list[VectorHit]:
        provider = self._config.provider
        if provider == PROVIDER_ELASTICSEARCH:
            return await self._safe_elasticsearch(request, FALLBACK_ES_TO_BM25)
        if provider == PROVIDER_SHADOW:
            return await self._shadow(request)
        if provider == PROVIDER_MILVUS:
            return await self._primary_milvus(request)
        # 防御: 构造时已校验,此处不可达
        raise ValueError(f"未知的向量 Provider: {provider!r}")

    # ---- 模式实现 --------------------------------------------------------

    async def _primary_milvus(self, request: VectorSearchRequest) -> list[VectorHit]:
        if self._milvus is None:
            raise RuntimeError("ProviderVectorCandidateSource: milvus_source 未配置,无法切到 milvus 模式")
        milvus = cast(VectorCandidateSource, self._milvus)
        try:
            return await self._timed("milvus", milvus.search, request)
        except Exception as ex:  # noqa: BLE001 - 切流回退属于业务流,非致命
            if not self._config.fallback_to_elasticsearch:
                logger.warning("Milvus 向量检索失败且未开启 ES 回退: %s", ex)
                raise
            self._metrics.record_fallback("milvus_to_elasticsearch")
            logger.warning("Milvus 向量检索失败,回退 ES kNN: %s", ex)
            return await self._safe_elasticsearch(request, FALLBACK_MILVUS_AND_ES_TO_BM25)

    async def _shadow(self, request: VectorSearchRequest) -> list[VectorHit]:
        online = await self._safe_elasticsearch(request, FALLBACK_ES_TO_BM25)
        if self._milvus is None:
            return online
        milvus = cast(VectorCandidateSource, self._milvus)
        if random.random() >= self._config.shadow_sample_rate:
            return online

        # fire-and-forget;不要 await,会阻塞主链路返回 ES 结果。
        # 影子读本身若是同步阻塞调用,实现方应在自己的 Milvus 客户端里用
        # asyncio.to_thread / run_in_executor 包一层;本路由器不做线程池假设。
        async def _run_shadow() -> list[VectorHit] | None:
            try:
                return await asyncio.wait_for(
                    self._timed("milvus_shadow", milvus.search, request),
                    timeout=self._config.shadow_timeout_ms / 1000.0,
                )
            except Exception as ex:  # noqa: BLE001
                self._metrics.record_fallback(FALLBACK_SHADOW_TIMEOUT)
                logger.debug("Milvus 影子查询失败或超时: %s", ex)
                return None

        task = asyncio.create_task(_run_shadow())

        def _on_done(t: asyncio.Task) -> None:
            try:
                shadow = t.result()
                if shadow is not None:
                    self._metrics.record_shadow_comparison(online, shadow)
            except Exception as ex:  # noqa: BLE001 - 影子读异常仅记指标
                logger.debug("影子读结果处理失败: %s", ex)

        task.add_done_callback(_on_done)
        return online

    async def _safe_elasticsearch(
        self,
        request: VectorSearchRequest,
        failure_path: str,
    ) -> list[VectorHit]:
        try:
            return await self._timed("elasticsearch", self._es.search, request)
        except Exception as ex:  # noqa: BLE001
            self._metrics.record_fallback(failure_path)
            logger.warning("ES kNN 不可用,退化为 BM25-only: %s", ex)
            return []

    async def _timed(
        self,
        source: str,
        op: Any,
        request: VectorSearchRequest,
    ) -> list[VectorHit]:
        started = self._metrics.start_nanos()
        try:
            result = await op(request)
            self._metrics.record_latency(source, started, True)
            return list(result or [])
        except Exception as ex:
            self._metrics.record_latency(source, started, False)
            raise
