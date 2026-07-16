package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AnswerSelfCheckerTest {

    private final Citation citation = new Citation(UUID.randomUUID(), "doc.md", List.of(), "JWT 黑名单使用 Redis 存储。",
            null, null, null, 0.9);

    @Test
    void citedSentenceWithHighRelevanceIsNotFlagged() {
        RerankerClient reranker = highScoreReranker();
        AnswerSelfChecker checker = new AnswerSelfChecker(reranker);

        SelfCheckResult result = checker.check("JWT 黑名单存的是 Redis [资料1]。", List.of(citation));

        assertFalse(result.hasUnsupportedClaims());
    }

    @Test
    void citedSentenceWithLowRelevanceIsFlagged() {
        RerankerClient reranker = lowScoreReranker();
        AnswerSelfChecker checker = new AnswerSelfChecker(reranker);

        SelfCheckResult result = checker.check("JWT 黑名单其实存在 MySQL 里 [资料1]。", List.of(citation));

        assertTrue(result.hasUnsupportedClaims());
        assertTrue(result.unsupportedClaims().get(0).contains("相关性较低"));
    }

    @Test
    void substantiveSentenceWithoutCitationIsFlagged() {
        AnswerSelfChecker checker = new AnswerSelfChecker(highScoreReranker());

        SelfCheckResult result = checker.check("这是一句没有任何引用标记的实质性陈述句。", List.of(citation));

        assertTrue(result.hasUnsupportedClaims());
        assertTrue(result.unsupportedClaims().get(0).contains("未标注引用来源"));
    }

    @Test
    void shortTransitionSentenceWithoutCitationIsNotFlagged() {
        AnswerSelfChecker checker = new AnswerSelfChecker(highScoreReranker());

        SelfCheckResult result = checker.check("总结来说，JWT 黑名单存的是 Redis [资料1]。", List.of(citation));

        assertFalse(result.hasUnsupportedClaims(), "「总结来说，」很短，不应被当成未标注断言");
    }

    @Test
    void rerankerExceptionFailsOpenToNoProblems() {
        RerankerClient throwing = (query, candidates, topK) -> { throw new IllegalStateException("timeout"); };
        AnswerSelfChecker checker = new AnswerSelfChecker(throwing);

        SelfCheckResult result = checker.check("JWT 黑名单存的是 Redis [资料1]。", List.of(citation));

        assertFalse(result.hasUnsupportedClaims());
    }

    @Test
    void cleanAnswerAcrossMixedPunctuationProducesNoWarnings() {
        AnswerSelfChecker checker = new AnswerSelfChecker(highScoreReranker());

        SelfCheckResult result = checker.check(
                "JWT 黑名单存的是 Redis [资料1]！\nkey 用 token 的 jti [资料1]？\n总结。", List.of(citation));

        assertEquals(SelfCheckResult.none(), result);
    }

    private RerankerClient highScoreReranker() {
        return (query, candidates, topK) -> candidates.stream()
                .map(c -> withScore(c, 0.9)).toList();
    }

    private RerankerClient lowScoreReranker() {
        return (query, candidates, topK) -> candidates.stream()
                .map(c -> withScore(c, 0.02)).toList();
    }

    private RetrievedChunk withScore(RetrievedChunk candidate, double score) {
        return new RetrievedChunk(candidate.chunk(), candidate.bm25Rank(), candidate.vectorRank(),
                candidate.rrfScore(), score, score);
    }
}
