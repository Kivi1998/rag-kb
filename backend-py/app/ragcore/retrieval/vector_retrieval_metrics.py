"""ES / Milvus 切流期间的低基数可观测指标。

对应 Java 版 `ragcore/retrieval/VectorRetrievalMetrics.java`。Java 版绑定 Micrometer,
本实现绑定 `prometheus_client`(已在 pyproject.toml 声明)。

为了避免任何指标依赖让单元测试跑不起来,所有 metric 都在调用时延迟创建;未提供
`prometheus_client` registry 时,所有方法都是 no-op。这是可选依赖,HybridRetriever
可以传 None。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class VectorRetrievalMetrics:
    """向量检索低基数可观测性指标包装器。无 registry 时全部方法静默 no-op。"""

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry
        self._latency: dict[tuple[str, str], Any] = {}
        self._fallback: dict[str, Any] = {}
        self._orphan: Any = None
        self._shadow_overlap: Any = None
        self._shadow_diff: Any = None

    def start_nanos(self) -> int:
        import time

        return time.monotonic_ns()

    def record_latency(self, source: str, started_nanos: int, success: bool) -> None:
        if self._registry is None:
            return
        try:
            from prometheus_client import Histogram  # type: ignore

            key = (source, "success" if success else "failure")
            histogram = self._latency.get(key)
            if histogram is None:
                histogram = Histogram(
                    "rag_vector_query_latency_seconds",
                    "向量查询端到端时延",
                    labelnames=["source", "outcome"],
                    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
                )
                self._latency[key] = histogram
            import time

            elapsed = max(0.0, (time.monotonic_ns() - started_nanos) / 1_000_000_000.0)
            histogram.labels(source=source, outcome="success" if success else "failure").observe(elapsed)
        except Exception:  # noqa: BLE001 - 指标失败不影响主流程
            logger.debug("vector latency 指标记录失败", exc_info=True)

    def record_fallback(self, path: str) -> None:
        if self._registry is None:
            return
        try:
            from prometheus_client import Counter  # type: ignore

            counter = self._fallback.get(path)
            if counter is None:
                counter = Counter(
                    "rag_vector_fallback_total",
                    "向量检索回退次数(按回退路径分类)",
                    labelnames=["path"],
                )
                self._fallback[path] = counter
            counter.labels(path=path).inc()
        except Exception:  # noqa: BLE001
            logger.debug("vector fallback 指标记录失败", exc_info=True)

    def record_orphans(self, count: int) -> None:
        if self._registry is None or count <= 0:
            return
        try:
            from prometheus_client import Counter  # type: ignore

            if self._orphan is None:
                self._orphan = Counter(
                    "rag_vector_orphan_hits_total",
                    "向量命中但 ES 正文缺失的孤儿 chunk 数",
                )
            self._orphan.inc(count)
        except Exception:  # noqa: BLE001
            logger.debug("vector orphan 指标记录失败", exc_info=True)

    def record_shadow_comparison(
        self,
        online: list[Any],
        shadow: list[Any],
    ) -> None:
        """对比 ES 主读与 Milvus 影子读 top-k 重合度,用于切流决策。"""
        if self._registry is None:
            return
        try:
            from prometheus_client import Histogram  # type: ignore

            if self._shadow_overlap is None:
                self._shadow_overlap = Histogram(
                    "rag_vector_shadow_topk_overlap_ratio",
                    "ES 主读与 Milvus 影子读 top-k 重合度",
                    buckets=(0.0, 0.25, 0.5, 0.75, 0.9, 1.0),
                )
            if self._shadow_diff is None:
                self._shadow_diff = Histogram(
                    "rag_vector_shadow_difference_count",
                    "ES 主读与 Milvus 影子读 top-k 差集大小",
                    buckets=(0, 1, 2, 4, 8, 16, 32, 64),
                )

            online_ids = {hit.chunk_id for hit in (online or [])}
            shadow_ids = {hit.chunk_id for hit in (shadow or [])}
            overlap = online_ids & shadow_ids
            denom = max(1, min(len(online_ids), len(shadow_ids)))
            self._shadow_overlap.observe(len(overlap) / denom)
            diff = online_ids ^ shadow_ids
            self._shadow_diff.observe(float(len(diff)))
        except Exception:  # noqa: BLE001
            logger.debug("vector shadow 指标记录失败", exc_info=True)
