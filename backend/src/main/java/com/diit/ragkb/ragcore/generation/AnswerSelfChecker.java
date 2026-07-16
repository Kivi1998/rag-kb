package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import lombok.extern.slf4j.Slf4j;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 生成后自检：独立于生成模型之外，用现有 Reranker 对正文逐句核查是否有资料支撑，
 * 补上"两道闸"里缺失的第二道——只靠 prompt 约束（第一道）不够，因为模型偶尔会
 * 自信地越界，让同一个模型自查自己说服力有限。
 *
 * <p>不引入新的 LLM 调用：带 {@code [资料N]} 标记的句子，把句子本身当 query、标记
 * 对应的资料原文当候选，复用 {@link RerankerClient} 打分；没有任何引用标记的实质性
 * 句子直接判定为疑似未标注断言，不占用 Reranker 调用。Reranker 调用异常时整体核查
 * 视为"无问题"，不影响已经生成并展示给用户的正文。</p>
 *
 * <p>已知局限：Reranker 衡量的是语义相关性，不是严格的事实蕴含判断；复用检索阶段
 * 已校准的 {@code MIN_SUPPORT_SCORE} 只是起步值，不代表对这个新场景也最优——
 * 真实回归验证会摸底实际命中率/误伤率。</p>
 */
@Slf4j
public class AnswerSelfChecker {

    private static final Pattern SENTENCE_BOUNDARY = Pattern.compile("(?<=[。！？\\n])");
    private static final Pattern CITATION_MARKER = Pattern.compile("\\[资料(\\d+)]");
    private static final int MIN_SUBSTANTIVE_SENTENCE_LENGTH = 6;

    /** 复用 {@code HybridRetriever.MIN_RERANK_SCORE} 同一个已校准数值，见类注释的局限说明。 */
    private static final double MIN_SUPPORT_SCORE = 0.06;

    private final RerankerClient rerankerClient;

    public AnswerSelfChecker(RerankerClient rerankerClient) {
        this.rerankerClient = rerankerClient;
    }

    public SelfCheckResult check(String answerText, List<Citation> citations) {
        if (answerText == null || answerText.isBlank()) {
            return SelfCheckResult.none();
        }
        List<String> unsupportedClaims = new ArrayList<>();
        try {
            for (String rawSentence : SENTENCE_BOUNDARY.split(answerText)) {
                String sentence = rawSentence.trim();
                if (sentence.isEmpty()) {
                    continue;
                }
                List<Integer> citedIndexes = extractCitationIndexes(sentence);
                if (citedIndexes.isEmpty()) {
                    if (sentence.length() >= MIN_SUBSTANTIVE_SENTENCE_LENGTH) {
                        unsupportedClaims.add(sentence + "（未标注引用来源）");
                    }
                    continue;
                }
                if (!isSupportedByCitations(sentence, citedIndexes, citations)) {
                    unsupportedClaims.add(sentence + "（标注了引用，但相关性较低）");
                }
            }
        } catch (RuntimeException ex) {
            log.warn("生成后自检调用 Reranker 失败，本轮跳过自检: {}", ex.getMessage());
            return SelfCheckResult.none();
        }
        return new SelfCheckResult(unsupportedClaims);
    }

    private boolean isSupportedByCitations(String sentence, List<Integer> citedIndexes, List<Citation> citations) {
        List<RetrievedChunk> candidates = new ArrayList<>();
        for (Integer index : citedIndexes) {
            if (index < 1 || index > citations.size()) {
                continue;
            }
            candidates.add(syntheticChunk(citations.get(index - 1)));
        }
        if (candidates.isEmpty()) {
            // 引用编号越界找不到对应资料时，没有依据判断"不支撑"，避免误伤。
            return true;
        }
        List<RetrievedChunk> reranked = rerankerClient.rerank(sentence, candidates, candidates.size());
        return !reranked.isEmpty() && reranked.get(0).finalScore() != null
                && reranked.get(0).finalScore() >= MIN_SUPPORT_SCORE;
    }

    private RetrievedChunk syntheticChunk(Citation citation) {
        Chunk chunk = new Chunk("self-check-" + citation.documentId(), null, null, citation.documentId(), 0,
                citation.snippet(), citation.headingPath(), citation.documentName(), citation.pageNo(),
                citation.lineStart(), citation.lineEnd(), "zh", "self-check", Map.of());
        return new RetrievedChunk(chunk, null, null, null, null, null);
    }

    private List<Integer> extractCitationIndexes(String sentence) {
        List<Integer> indexes = new ArrayList<>();
        Matcher matcher = CITATION_MARKER.matcher(sentence);
        while (matcher.find()) {
            indexes.add(Integer.parseInt(matcher.group(1)));
        }
        return indexes;
    }
}
