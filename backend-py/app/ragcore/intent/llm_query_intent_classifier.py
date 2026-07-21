"""用 LLM Prompt 做检索意图粗分类(冷启动路径)。对应 Java 版 `ragcore/intent/LlmQueryIntentClassifier.java`。

实现未经过任何真实准确率验证,调用失败或输出不可解析时 fail-open 返回
`QueryIntent.UNKNOWN`,不重试、不阻断问答主流程。
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.ragcore.generation.client import ChatCompletionClient
from app.ragcore.intent.query_intent import QueryIntent
from app.ragcore.intent.query_intent_classifier import QueryIntentClassifier

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """你是一个检索意图分类器。给定用户的一个检索问题，判断它属于以下四类中的哪一类：

- precise-lookup：问题包含具体的错误码、型号、参数名、专有名词、编号等精确定位信息，
  用户在找一个具体、明确存在的东西
- semantic：问题是概念性的、宽泛的"是什么/为什么/怎么样"式提问，没有具体定位信息
- comparative：问题涉及比较两个或以上的实体、方法、方案的异同或优劣
- out-of-scope：问题与文档内容无关（闲聊、问候、与知识库主题无关的话题），
  或者问题含糊到无法归入前三类

只输出上面四个标签中的一个（precise-lookup / semantic / comparative / out-of-scope），
不要输出任何解释、标点、引号或其他文字。

示例：
问题：NullPointerException 怎么排查？
输出：precise-lookup

问题：为什么要用 L1 范数代替 L0 范数？
输出：semantic

问题：RPCA 和 PCA 的区别是什么？
输出：comparative

问题：今天天气怎么样？
输出：out-of-scope"""


_VALID_LABELS: dict[str, QueryIntent] = {
    "precise-lookup": QueryIntent.PRECISE_LOOKUP,
    "semantic": QueryIntent.SEMANTIC,
    "comparative": QueryIntent.COMPARATIVE,
    "out-of-scope": QueryIntent.OUT_OF_SCOPE,
}


def _parse(raw: str | None) -> QueryIntent:
    if raw is None:
        return QueryIntent.UNKNOWN
    label = raw.strip().lower()
    if not label:
        return QueryIntent.UNKNOWN
    # 容忍 LLM 在标签前后偶尔加的标点/引号/换行,仅取首个合法子串
    for key, intent in _VALID_LABELS.items():
        if key in label:
            return intent
    return QueryIntent.UNKNOWN


class LlmQueryIntentClassifier(QueryIntentClassifier):
    def __init__(self, chat_completion_client: ChatCompletionClient) -> None:
        self._client = chat_completion_client

    async def classify(self, question: str) -> QueryIntent:
        if not question or not question.strip():
            return QueryIntent.UNKNOWN
        user_prompt = f"问题：{question.strip()}\n输出："
        try:
            raw = await self._client.complete(_SYSTEM_PROMPT, user_prompt)
        except Exception as ex:  # noqa: BLE001 - fail-open 永不抛出
            logger.warning("查询意图分类调用失败,回退为 UNKNOWN: %s", ex)
            return QueryIntent.UNKNOWN
        intent = _parse(raw)
        if intent == QueryIntent.UNKNOWN:
            logger.warning(
                "查询意图分类输出无法解析,回退为 UNKNOWN, rawOutputLength=%d",
                0 if raw is None else len(raw),
            )
        return intent


__all__: Sequence[str] = ("LlmQueryIntentClassifier",)
