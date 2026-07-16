import com.diit.ragkb.config.RagModelProperties;
import com.diit.ragkb.ragcore.generation.AnswerSelfChecker;
import com.diit.ragkb.ragcore.generation.SelfCheckResult;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.rerank.OpenAiCompatibleRerankerClient;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 对 {@link AnswerSelfChecker} 跑真实回归验证：no-retrieval-fact-verification 的做法是用人工
 * 标注的真实问题，本次没有先例数据集，改用从真实语料（rag_chunks_eval_v3 索引对应的"本科毕设"
 * 语料）里摘取的 3 段真实资料原文，人工构造"准确复述"与"标了引用但内容对不上"的句子各 3 条，
 * 跑真实硅基流动 Reranker 打分，统计命中率/误伤率。
 *
 * <p>用法（repo 根目录，需要 RAG_RERANK_* 环境变量）：
 * <pre>
 * java -cp "eval/scripts:$(cat /tmp/rag-cp.txt):backend/target/classes" EvalAnswerSelfCheckerRunner
 * </pre></p>
 */
public final class EvalAnswerSelfCheckerRunner {

    private EvalAnswerSelfCheckerRunner() {
    }

    public static void main(String[] args) {
        String endpoint = requireEnv("RAG_RERANK_ENDPOINT");
        ObjectMapper mapper = new ObjectMapper();
        RagModelProperties.Rerank props = new RagModelProperties().getRerank();
        props.setEnabled(true);
        props.setEndpoint(endpoint);
        props.setModel(requireEnv("RAG_RERANK_MODEL"));
        props.setApiKey(System.getenv("RAG_RERANK_API_KEY"));
        props.setTimeoutMs(60_000);
        RerankerClient reranker = new OpenAiCompatibleRerankerClient(props, mapper);
        AnswerSelfChecker checker = new AnswerSelfChecker(reranker);

        // 三段真实资料原文（来自 rag_chunks_eval_v3 索引，"中国地质大学（北京）2020届本科生毕业设计"语料）。
        Citation svdDefinition = citation("其中，U是m×m阶酉矩阵；Σ是半正定m×n阶对角矩阵；而V*，即V的共轭转置，是n×n阶酉矩阵。"
                + "这样的分解就称作M的奇异值分解。Σ对角线上的元素Σi为M的奇异值，通常奇异值由大而小排列。");
        Citation chenSacchi = citation("Chen和Sacchi（2014）认为奇异值分解（SVD）这种矩阵分解技术是非稳健的，当地震数据中混有"
                + "不符合高斯分布的异常值噪声时，SVD无法有效压制不稳定的异常值噪声，于是提出了一种基于随机QR分解的稳健"
                + "奇异谱分析方法，以在有效压制随机噪声的同时压制不稳定的异常值噪声。");
        Citation rpcaNorms = citation("为使问题可解，我们使用由矩阵S中所有元素绝对值之和定义的L1范数来代替L0范数。同时，我们"
                + "考虑用L的核范数代替低秩约束，其中L的核模定义为矩阵L的所有非零奇异值的和。可以证明L1范数是L0范数"
                + "最严格的凸松弛（Donoho，2006）。同理，核范数是对低秩约束的紧凸松弛（Fazel，2002）。");
        List<Citation> citations = List.of(svdDefinition, chenSacchi, rpcaNorms);

        // 3 条准确复述（预期不拒答）+ 3 条标了引用但内容对不上的句子（预期被标记）。
        record Case(String label, String sentence, boolean expectFlagged) { }
        List<Case> cases = List.of(
                new Case("supported-1(SVD定义)", "奇异值分解把矩阵M分解成U、Σ和V三个矩阵，U和V均为酉矩阵，Σ为对角矩阵[资料1]。", false),
                new Case("unsupported-1(SVD定义@硬件环境)", "这次奇异值分解计算在配备32GB内存的服务器上完成[资料1]。", true),
                new Case("supported-2(Chen-Sacchi)", "Chen和Sacchi在2014年指出SVD对不符合高斯分布的异常值噪声处理并不稳健[资料2]。", false),
                new Case("unsupported-2(Chen-Sacchi@RPCA范数,张冠李戴)", "该方法用L1范数约束异常值噪声，用核范数约束低秩数据[资料2]。", true),
                new Case("supported-3(RPCA范数)", "该方法用L1范数代替L0范数、用核范数代替低秩约束，因为核范数是低秩约束的凸松弛[资料3]。", false),
                new Case("unsupported-3(RPCA范数@迭代耗时)", "本文RPCA迭代1500次后收敛，耗时约10分钟[资料3]。", true)
        );

        int correct = 0;
        System.out.println("[case] label | expectFlagged | actualFlagged | rawScore | 判定详情");
        for (Case c : cases) {
            SelfCheckResult result = checker.check(c.sentence(), citations);
            boolean actualFlagged = result.hasUnsupportedClaims();
            boolean hit = actualFlagged == c.expectFlagged();
            if (hit) correct++;
            Double rawScore = rawSupportScore(reranker, c.sentence(), citations);
            System.out.println("[" + (hit ? "OK" : "MISS") + "] " + c.label() + " | expect=" + c.expectFlagged()
                    + " actual=" + actualFlagged + " | rawScore=" + rawScore + " | " + result.unsupportedClaims());
        }
        System.out.println();
        System.out.println("[summary] " + correct + "/" + cases.size() + " 命中预期");
    }

    /** 诊断用：直接调用 Reranker 拿到句子与其引用的全部资料之间的原始分数，供分析误判原因。 */
    private static Double rawSupportScore(RerankerClient reranker, String sentence, List<Citation> citations) {
        java.util.regex.Matcher matcher = java.util.regex.Pattern.compile("\\[资料(\\d+)]").matcher(sentence);
        List<RetrievedChunk> candidates = new java.util.ArrayList<>();
        while (matcher.find()) {
            int index = Integer.parseInt(matcher.group(1));
            if (index < 1 || index > citations.size()) continue;
            Citation citation = citations.get(index - 1);
            Chunk chunk = new Chunk("diag-" + citation.documentId(), null, null, citation.documentId(), 0,
                    citation.snippet(), citation.headingPath(), citation.documentName(), citation.pageNo(),
                    citation.lineStart(), citation.lineEnd(), "zh", "diag", Map.of());
            candidates.add(new RetrievedChunk(chunk, null, null, null, null, null));
        }
        if (candidates.isEmpty()) return null;
        List<RetrievedChunk> reranked = reranker.rerank(sentence, candidates, candidates.size());
        return reranked.isEmpty() ? null : reranked.get(0).finalScore();
    }

    private static Citation citation(String snippet) {
        return new Citation(UUID.randomUUID(), "2020届本科生毕业设计.docx", List.of(), snippet, null, null, null, null);
    }

    private static String requireEnv(String key) {
        String value = System.getenv(key);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("缺少环境变量 " + key + "，本工具需要真实 Reranker 服务，不做降级");
        }
        return value;
    }
}
