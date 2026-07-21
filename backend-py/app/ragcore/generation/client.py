"""生成模型客户端协议。

对应 Java 版 `ragcore/generation/AnswerGenerator.java` + `ChatCompletionClient.java`。

Java 版 `AnswerGenerator` 用 `Consumer<QueryEvent>` 回调把事件推给调用方；Python 版按任务
要求改成 async generator（`yield QueryEvent`），配合 FastAPI `StreamingResponse` /
`EventSourceResponse` 更自然。用量统计（`GenerationMetrics`）通过调用方传入的可变实例原地
更新收集，详见 `metrics.py` 的说明。
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from app.ragcore.generation.metrics import GenerationMetrics
from app.ragcore.model import QueryEvent, RetrievedChunk


@runtime_checkable
class AnswerGenerator(Protocol):
    """基于已检索上下文生成答案，按统一事件协议流式输出。"""

    def model_id(self) -> str: ...

    def stream_with_metrics(
        self,
        question: str,
        contexts: list[RetrievedChunk],
        metrics: GenerationMetrics,
        additional_system_context: str | None = None,
    ) -> AsyncIterator[QueryEvent]:
        """流式产出 QueryEvent；`metrics` 在流结束（`async for` 正常耗尽）后携带最终用量统计。

        `additional_system_context` 非空时拼进 System Prompt（如用户画像背景信息），只影响
        生成风格，不影响 contexts 本身。
        """
        ...


@runtime_checkable
class ChatCompletionClient(Protocol):
    """非流式的单轮 Chat Completion 端口，供指代消解/摘要压缩/画像提炼这类"一次性、要完整结果"

    的辅助 LLM 调用复用，与面向用户的流式 `AnswerGenerator` 分开。
    """

    async def complete(self, system_prompt: str, user_prompt: str) -> str: ...
