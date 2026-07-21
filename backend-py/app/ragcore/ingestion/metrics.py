"""摄取链路低基数指标,供 Prometheus 告警与容量规划使用。

对应 Java 版 `ragcore/ingestion/IngestionMetrics.java`。
绑定 `prometheus_client` 替代 Micrometer;`registry=None` 时所有方法 no-op,
便于单元测试不依赖指标系统。
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class IngestionMetrics:
    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry
        self._in_flight: Any = None
        self._queue_depth: Any = None
        self._upload_initiated: Any = None
        self._upload_completed: Any = None
        self._upload_expired: Any = None
        self._stage_timers: dict[tuple[str, str], Any] = {}

    def _ensure_gauges(self) -> None:
        if self._registry is None or self._in_flight is not None:
            return
        from prometheus_client import Gauge

        in_flight_holder = {"value": 0}
        queue_holder = {"value": 0}

        self._in_flight = Gauge(
            "rag_ingestion_in_flight",
            "当前正在处理的摄取任务数",
        )
        self._queue_depth = Gauge(
            "rag_ingestion_queue_depth",
            "当前 QUEUED 状态的任务数",
        )

        def _set_in_flight(_h=in_flight_holder) -> None:
            self._in_flight.set(_h["value"])  # type: ignore[union-attr]

        def _set_queue(_h=queue_holder) -> None:
            self._queue_depth.set(_h["value"])  # type: ignore[union-attr]

        self._in_flight.set_function(lambda: float(in_flight_holder["value"]))  # type: ignore[union-attr]
        self._queue_depth.set_function(lambda: float(queue_holder["value"]))  # type: ignore[union-attr]
        # 暴露 mutator 给实例方法使用
        self._in_flight_holder = in_flight_holder
        self._queue_holder = queue_holder

    # ---- 任务计数器 ----------------------------------------------------

    def upload_initiated(self) -> None:
        self._upload_counter("initiated", self._upload_initiated, "rag_upload_sessions_total_initiated")

    def upload_completed(self) -> None:
        self._upload_counter("completed", self._upload_completed, "rag_upload_sessions_total_completed")

    def upload_expired(self) -> None:
        self._upload_counter("expired", self._upload_expired, "rag_upload_sessions_total_expired")

    def _upload_counter(self, result: str, slot: Any, name: str) -> None:
        if self._registry is None:
            return
        try:
            from prometheus_client import Counter

            counter = slot
            if counter is None:
                counter = Counter(
                    name,
                    "上传任务结果",
                    labelnames=["result"],
                )
                if result == "initiated":
                    self._upload_initiated = counter
                elif result == "completed":
                    self._upload_completed = counter
                else:
                    self._upload_expired = counter
            counter.labels(result=result).inc()
        except Exception:  # noqa: BLE001
            logger.debug("upload 计数器更新失败", exc_info=True)

    # ---- in-flight & queue --------------------------------------------

    def increment_in_flight(self) -> int:
        if self._registry is None:
            return 0
        self._ensure_gauges()
        new_value = self._in_flight_holder["value"] + 1
        self._in_flight_holder["value"] = new_value
        return new_value

    def decrement_in_flight(self) -> int:
        if self._registry is None:
            return 0
        self._ensure_gauges()
        new_value = max(0, self._in_flight_holder["value"] - 1)
        self._in_flight_holder["value"] = new_value
        return new_value

    def in_flight(self) -> int:
        if self._registry is None:
            return 0
        self._ensure_gauges()
        return self._in_flight_holder["value"]

    def queue_depth(self, value: int) -> None:
        if self._registry is None:
            return
        self._ensure_gauges()
        self._queue_holder["value"] = max(0, value)

    # ---- 阶段计时 ------------------------------------------------------

    def start_nanos(self) -> int:
        return time.monotonic_ns()

    def stage_finished(self, stage: str, started_nanos: int, success: bool) -> None:
        if self._registry is None:
            return
        try:
            from prometheus_client import Histogram

            key = (stage, "success" if success else "failure")
            timer = self._stage_timers.get(key)
            if timer is None:
                timer = Histogram(
                    "rag_ingestion_stage_duration_seconds",
                    "RAG 摄取各阶段耗时",
                    labelnames=["stage", "result"],
                    buckets=(
                        0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0,
                        10.0, 30.0, 60.0, 120.0, 300.0,
                    ),
                )
                self._stage_timers[key] = timer
            elapsed = max(0.0, (time.monotonic_ns() - started_nanos) / 1_000_000_000.0)
            timer.labels(stage=stage, result="success" if success else "failure").observe(elapsed)
        except Exception:  # noqa: BLE001
            logger.debug("stage timer 上报失败", exc_info=True)
