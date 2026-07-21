"""DeepSeek 指代消解实现。对应 Java 版 `DeepSeekCoreferenceResolver.java`。

窄范围指代消解: prompt 严格限定"只做指代/省略补全,禁止改写技术术语、错误码、
配置项等专有名词"。调用失败或超时时 fail-open,直接返回原始问题,不阻断问答主流程。
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.ragcore.generation.client import ChatCompletionClient
from app.ragcore.memory.chat_message import ChatMessage, ROLE_ASSISTANT, ROLE_USER
from app.ragcore.memory.coreference_resolver import CoreferenceResolver

logger = logging.getLogger(__name__)

SYSTEM_PROMPT: str = (
    "你的唯一任务是指代消解:结合对话历史,把用户最新问题里的代词"
    "(它/这个/那个/上面说的 等)或省略部分补全,"
    "使其成为一句不看历史也能理解的独立问题。"
    "严格禁止:不要改写、翻译或润色任何技术术语、类名、错误码、配置项、专有名词;"
    "如果问题本身不含任何指代,原样输出,不做任何改动。"
    "只输出补全后的问题,不要输出解释。"
)


class DeepSeekCoreferenceResolver(CoreferenceResolver):
    def __init__(self, chat_completion_client: ChatCompletionClient) -> None:
        self._client = chat_completion_client

    async def resolve(self, question: str, history: Iterable[ChatMessage]) -> str:
        history_list = list(history or [])
        if not history_list:
            return question
        try:
            transcript = "\n".join(
                f"{'用户' if m.role == ROLE_USER else '助手'}: {m.content}"
                for m in history_list
            )
            user_prompt = f"对话历史:\n{transcript}\n\n用户最新问题:{question}"
            resolved = await self._client.complete(SYSTEM_PROMPT, user_prompt)
            if not resolved or not resolved.strip():
                return question
            return resolved.strip()
        except Exception as ex:  # noqa: BLE001 - fail-open,绝不抛出
            logger.warning("指代消解调用失败,退回原始问题继续检索: %s", ex)
            return question
