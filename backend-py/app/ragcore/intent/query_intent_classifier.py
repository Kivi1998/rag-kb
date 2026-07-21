"""对已解析(指代消解后)的查询问题做检索意图分类。

对应 Java 版 `ragcore/intent/QueryIntentClassifier.java`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ragcore.intent.query_intent import QueryIntent


@runtime_checkable
class QueryIntentClassifier(Protocol):
    """分类失败(超时/异常/输出不可解析)时返回 `QueryIntent.UNKNOWN`,不抛出异常。"""

    async def classify(self, question: str) -> QueryIntent: ...
