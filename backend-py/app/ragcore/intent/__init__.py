"""查询意图分类子包。对应 Java 版 `ragcore/intent/` 包。

驱动 HybridRetriever 中 `RetrievalOptions` 的 bm25_weight / vector_weight
(见 `weights_for_intent`)。UNKNOWN 是分类失败哨兵,不应被当作真实意图。
"""

from app.ragcore.intent.llm_query_intent_classifier import LlmQueryIntentClassifier
from app.ragcore.intent.query_intent import QueryIntent, weights_for_intent
from app.ragcore.intent.query_intent_classifier import QueryIntentClassifier

__all__ = [
    "QueryIntent",
    "QueryIntentClassifier",
    "LlmQueryIntentClassifier",
    "weights_for_intent",
]
