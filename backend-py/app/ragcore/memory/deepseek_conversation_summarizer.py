"""DeepSeek 会话摘要压缩实现。对应 Java 版 `DeepSeekConversationSummarizer.java`。

调用失败由调用方(`SlidingWindowAssembler`)负责 fail-open,本类不向调用方抛出
异常中断问答主流程。
"""

from __future__ import annotations

from app.ragcore.generation.client import ChatCompletionClient
from app.ragcore.memory.chat_message import ChatMessage, ROLE_ASSISTANT, ROLE_USER
from app.ragcore.memory.conversation_summarizer import ConversationSummarizer

SYSTEM_PROMPT: str = (
    "你是对话摘要助手。把下面这段对话历史压缩成一段简洁的摘要,"
    "保留关键信息(讨论过的话题、结论、提到的具体名词),"
    "不要加入原文没有的内容,不要逐句翻译,直接输出摘要文本。"
)


class DeepSeekConversationSummarizer(ConversationSummarizer):
    def __init__(self, chat_completion_client: ChatCompletionClient) -> None:
        self._client = chat_completion_client

    async def summarize(self, messages_to_compress: list[ChatMessage]) -> str:
        if not messages_to_compress:
            return ""
        transcript = "\n".join(
            f"{'用户' if m.role == ROLE_USER else '助手'}: {m.content}"
            for m in messages_to_compress
        )
        # 摘要 LLM 是非流式单轮调用,与 ChatCompletionClient.complete 契约一致。
        return await self._client.complete(SYSTEM_PROMPT, transcript)
