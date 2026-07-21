"""AnswerGenerator / ChatCompletionClient 协议测试。

这两个类型目前只是 Protocol 定义（对应 Java 版 `AnswerGenerator.java` +
`ChatCompletionClient.java` 接口），没有内置实现类——`runtime_checkable` 令它们支持
结构化 isinstance 检查，这里验证协议的形状符合预期：具备正确方法签名的类被识别为实现了
协议，缺少方法的类不被识别。
"""

from __future__ import annotations

from typing import AsyncIterator

from app.ragcore.generation.client import AnswerGenerator, ChatCompletionClient
from app.ragcore.generation.metrics import GenerationMetrics
from app.ragcore.model import QueryEvent, QueryEventType, RetrievedChunk


class _FakeAnswerGenerator:
    def model_id(self) -> str:
        return "fake-model"

    async def stream_with_metrics(
        self,
        question: str,
        contexts: list[RetrievedChunk],
        metrics: GenerationMetrics,
        additional_system_context: str | None = None,
    ) -> AsyncIterator[QueryEvent]:
        yield QueryEvent(type=QueryEventType.DONE)


class _FakeChatCompletionClient:
    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        return "ok"


class _NotAGenerator:
    """缺少 stream_with_metrics，结构上不满足 AnswerGenerator 协议。"""

    def model_id(self) -> str:
        return "x"


class TestAnswerGeneratorProtocol:
    def test_structurally_compatible_class_is_recognized(self):
        assert isinstance(_FakeAnswerGenerator(), AnswerGenerator)

    def test_incomplete_class_is_not_recognized(self):
        assert not isinstance(_NotAGenerator(), AnswerGenerator)


class TestChatCompletionClientProtocol:
    def test_structurally_compatible_class_is_recognized(self):
        assert isinstance(_FakeChatCompletionClient(), ChatCompletionClient)

    def test_unrelated_class_is_not_recognized(self):
        class _Empty:
            pass

        assert not isinstance(_Empty(), ChatCompletionClient)
