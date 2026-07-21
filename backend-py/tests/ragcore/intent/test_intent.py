"""`LlmQueryIntentClassifier` fail-open 行为 + QueryIntent 权重映射测试。

对照 Java 版 `ragcore/intent/LlmQueryIntentClassifier.java`。
关键行为:LLM 调用失败/超时/输出无法解析时,必须 fail-open 返回 `QueryIntent.UNKNOWN`,
不抛异常——这是冷启动路径,影响召回权重,绝不能阻断问答主流程。
"""

from __future__ import annotations

import pytest

from app.ragcore.generation.client import ChatCompletionClient
from app.ragcore.intent.llm_query_intent_classifier import LlmQueryIntentClassifier
from app.ragcore.intent.query_intent import QueryIntent, weights_for_intent


class _StubChatClient(ChatCompletionClient):
    """可控制 complete() 返回值与异常的 LLM stub。"""

    def __init__(self, response: str | None = None, raise_exc: Exception | None = None) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.last_system: str | None = None
        self.last_user: str | None = None
        self.call_count = 0

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        self.last_system = system_prompt
        self.last_user = user_prompt
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.response is None:
            raise RuntimeError("response not set")
        return self.response


class TestClassifierFailOpen:
    """LLM 失败/异常/无法解析输出时,fail-open 返回 UNKNOWN。"""

    @pytest.mark.asyncio
    async def test_llm_timeout_returns_unknown(self):
        classifier = LlmQueryIntentClassifier(_StubChatClient(raise_exc=TimeoutError("API timeout")))
        result = await classifier.classify("什么是 RAG?")
        assert result == QueryIntent.UNKNOWN

    @pytest.mark.asyncio
    async def test_llm_network_error_returns_unknown(self):
        classifier = LlmQueryIntentClassifier(_StubChatClient(raise_exc=ConnectionError("refused")))
        result = await classifier.classify("什么是 RAG?")
        assert result == QueryIntent.UNKNOWN

    @pytest.mark.asyncio
    async def test_unparseable_response_returns_unknown(self):
        """LLM 输出不在合法标签集合内 → UNKNOWN。"""
        classifier = LlmQueryIntentClassifier(_StubChatClient(response="我不太确定,这是闲聊"))
        result = await classifier.classify("什么是 RAG?")
        assert result == QueryIntent.UNKNOWN

    @pytest.mark.asyncio
    async def test_empty_response_returns_unknown(self):
        classifier = LlmQueryIntentClassifier(_StubChatClient(response=""))
        result = await classifier.classify("什么是 RAG?")
        assert result == QueryIntent.UNKNOWN

    @pytest.mark.asyncio
    async def test_whitespace_response_returns_unknown(self):
        classifier = LlmQueryIntentClassifier(_StubChatClient(response="   \n"))
        result = await classifier.classify("什么是 RAG?")
        assert result == QueryIntent.UNKNOWN

    @pytest.mark.asyncio
    async def test_none_response_returns_unknown(self):
        """LLM 返回 None 也不应抛——按空字符串处理。"""
        classifier = LlmQueryIntentClassifier(_StubChatClient(response=None))
        result = await classifier.classify("什么是 RAG?")
        assert result == QueryIntent.UNKNOWN

    @pytest.mark.asyncio
    async def test_blank_question_returns_unknown_without_llm_call(self):
        """空问题直接 UNKNOWN,不发 LLM 调用——避免无意义的 token 消耗。"""
        client = _StubChatClient(response="precise-lookup")
        classifier = LlmQueryIntentClassifier(client)
        assert await classifier.classify("") == QueryIntent.UNKNOWN
        assert await classifier.classify("   ") == QueryIntent.UNKNOWN
        assert client.call_count == 0


class TestClassifierHappyPath:
    @pytest.mark.asyncio
    async def test_recognizes_precise_lookup(self):
        classifier = LlmQueryIntentClassifier(_StubChatClient(response="precise-lookup"))
        assert await classifier.classify("NullPointerException 怎么排查?") == QueryIntent.PRECISE_LOOKUP

    @pytest.mark.asyncio
    async def test_recognizes_semantic(self):
        classifier = LlmQueryIntentClassifier(_StubChatClient(response="semantic"))
        assert await classifier.classify("为什么要用 L1 范数?") == QueryIntent.SEMANTIC

    @pytest.mark.asyncio
    async def test_recognizes_comparative(self):
        classifier = LlmQueryIntentClassifier(_StubChatClient(response="comparative"))
        assert await classifier.classify("RPCA 和 PCA 的区别?") == QueryIntent.COMPARATIVE

    @pytest.mark.asyncio
    async def test_recognizes_out_of_scope(self):
        classifier = LlmQueryIntentClassifier(_StubChatClient(response="out-of-scope"))
        assert await classifier.classify("今天天气怎么样?") == QueryIntent.OUT_OF_SCOPE

    @pytest.mark.asyncio
    async def test_tolerates_surrounding_punctuation(self):
        """LLM 偶尔会在标签前后加引号/换行,只取首个合法子串。"""
        classifier = LlmQueryIntentClassifier(_StubChatClient(response="\"precise-lookup\"\n"))
        assert await classifier.classify("x") == QueryIntent.PRECISE_LOOKUP

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        """label 校验不区分大小写。"""
        classifier = LlmQueryIntentClassifier(_StubChatClient(response="SEMANTIC"))
        assert await classifier.classify("x") == QueryIntent.SEMANTIC


class TestSystemPrompt:
    @pytest.mark.asyncio
    async def test_system_prompt_contains_labels(self):
        """system prompt 必须包含 4 个合法标签——这是 prompt 工程契约。"""
        client = _StubChatClient(response="semantic")
        classifier = LlmQueryIntentClassifier(client)
        await classifier.classify("x")
        assert "precise-lookup" in client.last_system
        assert "semantic" in client.last_system
        assert "comparative" in client.last_system
        assert "out-of-scope" in client.last_system

    @pytest.mark.asyncio
    async def test_user_prompt_includes_question(self):
        client = _StubChatClient(response="semantic")
        classifier = LlmQueryIntentClassifier(client)
        await classifier.classify("什么是 Embedding?")
        assert "什么是 Embedding?" in client.last_user


class TestWeightsForIntent:
    """QueryIntent → (bm25_weight, vector_weight) 映射契约。
    精确检索型(代码符号/错误码)依赖关键词命中,BM25 主导;
    语义/对比型依赖语义召回,向量主导;
    UNKNOWN/OUT_OF_SCOPE 维持等权(让 RRF 兜底排序而不是直接拒答)。"""

    def test_precise_lookup_boosts_bm25(self):
        bm25, vec = weights_for_intent(QueryIntent.PRECISE_LOOKUP)
        assert bm25 > vec
        assert bm25 == 1.2
        assert vec == 0.8

    def test_semantic_boosts_vector(self):
        bm25, vec = weights_for_intent(QueryIntent.SEMANTIC)
        assert vec > bm25
        assert bm25 == 0.7
        assert vec == 1.3

    def test_comparative_mild_vector_bias(self):
        bm25, vec = weights_for_intent(QueryIntent.COMPARATIVE)
        assert vec > bm25
        assert bm25 == 0.9
        assert vec == 1.1

    def test_out_of_scope_equal_weight(self):
        assert weights_for_intent(QueryIntent.OUT_OF_SCOPE) == (1.0, 1.0)

    def test_unknown_equal_weight(self):
        """UNKNOWN 是分类失败的内部哨兵值,等权重让 RRF 自然兜底。"""
        assert weights_for_intent(QueryIntent.UNKNOWN) == (1.0, 1.0)


class TestQueryIntentEnumContract:
    def test_all_intent_values_stable(self):
        """标签值是 LLM prompt 契约的一部分,改了就破坏跨语言评估集。"""
        assert QueryIntent.PRECISE_LOOKUP.value == "precise-lookup"
        assert QueryIntent.SEMANTIC.value == "semantic"
        assert QueryIntent.COMPARATIVE.value == "comparative"
        assert QueryIntent.OUT_OF_SCOPE.value == "out-of-scope"
        assert QueryIntent.UNKNOWN.value == "unknown"
