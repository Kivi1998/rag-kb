"""`AnswerSelfChecker` 测试。

对照 Java 版 `ragcore/generation/AnswerSelfChecker.java`:覆盖三种句子情况(带标记/
不带标记/带标记但 rerank 分数低)与三种 fail-open 路径(未启用/Reranker 异常/调用结果空),
是本模块"两道闸第二道"最关键的兜底测试。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.ragcore.generation.answer_self_checker import AnswerSelfChecker
from app.ragcore.generation.self_check_result import SelfCheckResult
from app.ragcore.model import Chunk, Citation, RetrievedChunk
from app.ragcore.rerank.thresholds import MIN_RERANK_SCORE


def _citation(document_id=None, snippet="snippet", name="doc.txt", idx: int = 0) -> Citation:
    return Citation(
        document_id=document_id or uuid4(),
        document_name=name,
        heading_path=("章",),
        snippet=snippet,
        page_no=1,
        line_start=1,
        line_end=2,
        score=0.5,
    )


class _StubReranker:
    """可控的 Reranker stub:不依赖 httpx,直接返回预设分数/异常,验证 SelfChecker 的判定逻辑。

    `scores` 既可以是按 candidates 顺序给出分数的 list,也可以是按 chunk.content 给出分数的
    dict——多句混合测试里同一句的 candidates 各有不同 snippet,需要按内容给不同分数才能验证
    "只拦低分句、不拦高分句"的逐句判定。
    """

    def __init__(
        self,
        scores: list[float] | dict[str, float] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._scores = scores
        self._exc = exc
        self.calls: list[tuple[str, list[RetrievedChunk]]] = []

    async def rerank(self, query: str, candidates: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, candidates))
        if self._exc is not None:
            raise self._exc
        indexed = list(enumerate(candidates))
        indexed.sort(key=lambda pair: -self._score_for(pair[0], pair[1]))
        reranked: list[RetrievedChunk] = []
        for original_index, candidate in indexed[:top_k]:
            score = self._score_for(original_index, candidate)
            reranked.append(
                RetrievedChunk(
                    chunk=candidate.chunk,
                    bm25_rank=candidate.bm25_rank,
                    vector_rank=candidate.vector_rank,
                    rrf_score=candidate.rrf_score,
                    rerank_score=score,
                    final_score=score,
                )
            )
        return reranked

    def _score_for(self, original_index: int, candidate: RetrievedChunk) -> float:
        if self._scores is None:
            return 0.0
        if isinstance(self._scores, dict):
            return self._scores.get(candidate.chunk.content, 0.0)
        if original_index < len(self._scores):
            return self._scores[original_index]
        return 0.0


class TestDisabledFailOpen:
    """`reranker_client=None`(未启用 Rerank)时必须直接跳过,返回 `SelfCheckResult.none()`。"""

    async def test_disabled_returns_none_for_text_with_no_citations(self):
        checker = AnswerSelfChecker(reranker_client=None)
        result = await checker.check("这是一段没有任何引用标记的正文。", [_citation()])
        assert result is not None
        assert result.has_unsupported_claims is False
        assert result.unsupported_claims == ()

    async def test_disabled_returns_none_for_text_with_citations(self):
        checker = AnswerSelfChecker(reranker_client=None)
        result = await checker.check("这句话有引用 [资料1]。", [_citation()])
        assert result.has_unsupported_claims is False

    def test_enabled_property_false_when_reranker_is_none(self):
        assert AnswerSelfChecker(None).enabled is False

    def test_enabled_property_true_when_reranker_present(self):
        assert AnswerSelfChecker(_StubReranker()).enabled is True


class TestEmptyInput:
    async def test_blank_text_returns_none(self):
        checker = AnswerSelfChecker(_StubReranker())
        result = await checker.check("   ", [_citation()])
        assert result == SelfCheckResult.none()

    async def test_none_text_returns_none(self):
        checker = AnswerSelfChecker(_StubReranker())
        result = await checker.check(None, [_citation()])
        assert result == SelfCheckResult.none()


class TestUnsupportedClaimsNoCitation:
    """无引用标记的实质性句子直接判定为疑似未标注断言。"""

    async def test_substantive_sentence_without_citation_is_unsupported(self):
        checker = AnswerSelfChecker(_StubReranker())
        result = await checker.check("这是一段没有任何引用标记的实质性内容。", [_citation()])
        assert result.has_unsupported_claims is True
        assert len(result.unsupported_claims) == 1
        assert "未标注引用来源" in result.unsupported_claims[0]

    async def test_short_sentence_without_citation_is_ignored(self):
        """长度 < 6 字符的句子不视为"实质性断言",不计入未支撑。"""
        checker = AnswerSelfChecker(_StubReranker())
        result = await checker.check("你好。", [_citation()])
        assert result.has_unsupported_claims is False

    async def test_reranker_not_called_when_no_citation_markers(self):
        """无引用标记时不应调 Reranker(节省配额)——Java 版同样。"""
        reranker = _StubReranker()
        checker = AnswerSelfChecker(reranker)
        await checker.check("这是一段没有任何引用标记的实质性内容。", [_citation()])
        assert reranker.calls == []


class TestSupportedClaimsWithCitation:
    """带引用标记且 rerank 分数 >= 阈值时,句子视为被支撑。"""

    async def test_cited_sentence_with_high_score_is_supported(self):
        reranker = _StubReranker(scores=[MIN_RERANK_SCORE + 0.1])
        checker = AnswerSelfChecker(reranker)

        c = _citation(snippet="参考资料原文内容")
        result = await checker.check("回答正文 [资料1]。", [c])

        assert result.has_unsupported_claims is False
        # Reranker 应当被调用,候选来自对应的 citation
        assert len(reranker.calls) == 1
        _query, candidates = reranker.calls[0]
        assert len(candidates) == 1
        assert candidates[0].chunk.content == "参考资料原文内容"

    async def test_cited_sentence_at_exact_threshold_is_supported(self):
        """`>=` 阈值:等于阈值时视为支撑,这是 Java 版同款边界。"""
        reranker = _StubReranker(scores=[MIN_RERANK_SCORE])
        checker = AnswerSelfChecker(reranker)

        result = await checker.check("回答 [资料1]。", [_citation()])

        assert result.has_unsupported_claims is False


class TestUnsupportedClaimsWithLowScore:
    """带引用标记但 rerank 分数 < 阈值时,句子计入"标注了引用但相关性较低"。"""

    async def test_cited_sentence_below_threshold_is_unsupported(self):
        reranker = _StubReranker(scores=[MIN_RERANK_SCORE - 0.01])
        checker = AnswerSelfChecker(reranker)

        c = _citation()
        result = await checker.check("回答正文 [资料1]。", [c])

        assert result.has_unsupported_claims is True
        assert len(result.unsupported_claims) == 1
        assert "标注了引用" in result.unsupported_claims[0]
        assert "相关性较低" in result.unsupported_claims[0]

    async def test_final_score_none_treated_as_unsupported(self):
        """Reranker 异常返回 final_score=None 时,视为无支撑,不会抛异常。"""
        # 通过返回一个 final_score=None 的 RetrievedChunk 来模拟
        class _NoneFinalScoreReranker:
            async def rerank(self, query, candidates, top_k):
                return [
                    RetrievedChunk(
                        chunk=candidates[0].chunk,
                        rerank_score=None,
                        final_score=None,
                    )
                ]

        checker = AnswerSelfChecker(_NoneFinalScoreReranker())
        result = await checker.check("回答 [资料1]。", [_citation()])
        assert result.has_unsupported_claims is True


class TestCitationIndexOutOfRange:
    """引用编号越界(找不到对应 citation)时,视为"无法判断"返回 True,不误伤。"""

    async def test_out_of_range_index_treated_as_supported(self):
        """编号 5 但 citations 只有 1 个时,该句不计入未支撑。"""
        reranker = _StubReranker()
        checker = AnswerSelfChecker(reranker)

        result = await checker.check("回答 [资料5]。", [_citation()])

        assert result.has_unsupported_claims is False
        # 候选列表为空时不应调 Reranker
        assert reranker.calls == []

    async def test_zero_index_ignored(self):
        """编号 0 不合法(Java 版 `index < 1` 过滤):candidates 为空时回退返回 True
        (无法判断则不误伤),与"完全无标记"分支的"长度足够视为未支撑"语义不同。

        这一点与 Java 版完全一致:Java 看到 `[资料N]` 模式就进入 `isSupportedByCitations`,
        里面的 `index < 1 || index > citations.size()` 跳过,不重新回到"无标记"分支。
        """
        reranker = _StubReranker()
        checker = AnswerSelfChecker(reranker)
        result = await checker.check("回答 [资料0]。", [_citation()])
        # 编号 0 越界 → 候选列表为空 → 视为支撑(无法判断则不报错)
        assert result.has_unsupported_claims is False
        # 同时确认没调过 Reranker(空候选短路)
        assert reranker.calls == []


class TestMultiSentence:
    """多句混合:同时存在带/不带标记的句子,需要逐句独立判断。"""

    async def test_mixed_supported_and_unsupported_sentences(self):
        # 两句各引一个 citation,按 chunk.content 给不同分数:第一份高分(支撑),
        # 第二份低分(不支撑)。验证"只拦低分句、不拦高分句"的逐句判定。
        reranker = _StubReranker(scores={"第一份资料内容": 0.5, "第二份资料内容": 0.01})
        checker = AnswerSelfChecker(reranker)

        c1 = _citation(snippet="第一份资料内容", idx=0)
        c2 = _citation(snippet="第二份资料内容", idx=1)
        answer = "第一句有引用支撑 [资料1]。第二句也标了引用但其实不支撑 [资料2]。"

        result = await checker.check(answer, [c1, c2])

        assert result.has_unsupported_claims is True
        assert len(result.unsupported_claims) == 1
        assert "第二句" in result.unsupported_claims[0]
        assert "标注了引用" in result.unsupported_claims[0]

    async def test_multiple_markers_in_one_sentence(self):
        """一句里有多个 `[资料N]`,Reranker 用所有对应 citation 当候选。"""
        reranker = _StubReranker(scores={"资料1内容": 0.5, "资料2内容": 0.5})
        checker = AnswerSelfChecker(reranker)

        c1 = _citation(snippet="资料1内容", idx=0)
        c2 = _citation(snippet="资料2内容", idx=1)
        result = await checker.check("这一句引用了两个资料 [资料1][资料2]。", [c1, c2])

        assert result.has_unsupported_claims is False
        # 候选应为 2 个
        assert len(reranker.calls) == 1
        _query, candidates = reranker.calls[0]
        assert len(candidates) == 2

    async def test_chinese_punctuation_sentence_split(self):
        """中文全角标点 `。！？` 都应当作句末分隔。"""
        reranker = _StubReranker(scores={"snippet": 0.5})
        checker = AnswerSelfChecker(reranker)

        c = _citation()
        result = await checker.check("第一句有引用 [资料1]！第二句有引用 [资料1]？第三句也有 [资料1]。", [c])

        assert result.has_unsupported_claims is False


class TestExceptionFailOpen:
    """Reranker 调用异常必须被吞掉,返回 `SelfCheckResult.none()`——不阻塞主问答流程。"""

    async def test_runtime_error_is_swallowed(self):
        checker = AnswerSelfChecker(_StubReranker(exc=RuntimeError("rerank failed")))
        result = await checker.check("回答 [资料1]。", [_citation()])
        assert result == SelfCheckResult.none()
        assert result.has_unsupported_claims is False

    async def test_model_client_exception_is_swallowed(self):
        from app.ragcore.model import ModelClientException

        checker = AnswerSelfChecker(_StubReranker(exc=ModelClientException("upstream 500")))
        result = await checker.check("回答 [资料1]。", [_citation()])
        assert result == SelfCheckResult.none()

    async def test_timeout_error_is_swallowed(self):
        import asyncio

        checker = AnswerSelfChecker(_StubReranker(exc=asyncio.TimeoutError()))
        result = await checker.check("回答 [资料1]。", [_citation()])
        assert result == SelfCheckResult.none()

    async def test_empty_rerank_result_treated_as_unsupported(self):
        """Reranker 异常返回空列表时,本句视为无支撑(避免漏报),不抛异常。"""
        class _EmptyReranker:
            async def rerank(self, query, candidates, top_k):
                return []

        checker = AnswerSelfChecker(_EmptyReranker())
        result = await checker.check("回答 [资料1]。", [_citation()])
        assert result.has_unsupported_claims is True


class TestSyntheticChunk:
    """验证 `_synthetic_chunk` 字段映射(从 Citation 构造用于 Reranker 的 RetrievedChunk)。"""

    def test_synthetic_chunk_id_prefixes_with_self_check(self):
        # 通过间接路径验证:让 Reranker 拿到 candidate,看 candidate.chunk.id 的前缀
        received: dict = {}

        class _CaptureReranker:
            async def rerank(self, query, candidates, top_k):
                received["candidates"] = candidates
                return candidates

        doc_id = uuid4()
        c = Citation(
            document_id=doc_id,
            document_name="需求.docx",
            heading_path=("章1",),
            snippet="片段",
            page_no=3,
            line_start=10,
            line_end=20,
            score=0.5,
        )
        checker = AnswerSelfChecker(_CaptureReranker())
        import asyncio

        asyncio.get_event_loop().run_until_complete(checker.check("回答 [资料1]。", [c]))
        chunk = received["candidates"][0].chunk
        assert chunk.id.startswith("self-check-")
        assert str(doc_id) in chunk.id
        assert chunk.content == "片段"
        assert chunk.heading_path == ("章1",)
        assert chunk.page_no == 3
        assert chunk.line_start == 10
        assert chunk.line_end == 20
        # language/content_hash 是 Java 版的固定值,这里照搬
        assert chunk.language == "zh"
        assert chunk.content_hash == "self-check"


class TestThreshold:
    """确保复用的是 `app.ragcore.rerank.thresholds.MIN_RERANK_SCORE`,不是别的字面量。"""

    def test_uses_canonical_threshold(self):
        from app.ragcore.generation import answer_self_checker as module

        assert module.MIN_RERANK_SCORE == MIN_RERANK_SCORE
