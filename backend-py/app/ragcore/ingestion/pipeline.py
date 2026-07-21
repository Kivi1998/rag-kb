"""Worker 领取任务后的实际处理端口。

对应 Java 版 `ragcore/ingestion/DocumentIngestionPipeline.java`。
T102 只定义可靠的任务驱动和状态边界;T107 提供实现,把 Parser、Chunker、Embedding
和 ES ChunkIndex 串起来。该接口刻意不接受 HTTP DTO,防止后台任务继承请求上下文。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ragcore.ingestion.task import IngestionTask


@runtime_checkable
class DocumentIngestionPipeline(Protocol):
    async def process(self, task: IngestionTask) -> None: ...
