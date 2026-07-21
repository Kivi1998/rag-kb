"""摄取子包的可识别异常集合。"""

from __future__ import annotations


class StaleIngestionLeaseException(RuntimeError):
    """旧 Worker 的租约已被新 Worker 接管,必须立即停止对任务状态的任何写入。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
