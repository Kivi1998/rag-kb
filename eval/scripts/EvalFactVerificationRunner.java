import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.config.RagModelProperties;
import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.embedding.OpenAiCompatibleEmbeddingClient;
import com.diit.ragkb.ragcore.generation.FactVerificationGate;
import com.diit.ragkb.ragcore.generation.GenerationMetrics;
import com.diit.ragkb.ragcore.generation.OpenAiCompatibleAnswerGenerator;
import com.diit.ragkb.ragcore.generation.PromptAssembler;
import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.rerank.OpenAiCompatibleRerankerClient;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.diit.ragkb.ragcore.retrieval.ElasticsearchHybridCandidateSource;
import com.diit.ragkb.ragcore.retrieval.HybridRetriever;
import com.diit.ragkb.ragcore.retrieval.RetrievalOptions;
import com.diit.ragkb.ragcore.retrieval.RetrievalResult;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.http.HttpHost;
import org.elasticsearch.client.RestClient;
import org.springframework.beans.factory.ObjectProvider;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/**
 * 对 no-retrieval-fact-verification 的 {@link FactVerificationGate} 跑真实端到端回归验证：
 * 真实检索（复用 {@code rag_chunks_eval_v3} 评测索引，不重建）+ 真实 DeepSeek 生成，
 * 统计 NO_RETRIEVAL 标注题的命中拒答比例，与抽样应答题的误伤比例。
 *
 * <p>用法（repo 根目录，需要 RAG_EMBEDDING_、RAG_RERANK_、RAG_GENERATION_ 前缀的环境变量齐全，
 * 且 {@code rag_chunks_eval_v3} 索引已由 {@code EvalRetrievalRunner} 建好）：
 * <pre>
 * java -cp "eval/scripts:$(cat /tmp/rag-cp.txt):backend/target/classes" EvalFactVerificationRunner \
 *   eval/datasets/eval-set-v2.jsonl \
 *   eval/predictions/no-retrieval-fact-verification-YYYYMMDD.jsonl
 * </pre></p>
 */
public final class EvalFactVerificationRunner {

    private static final String INDEX_NAME = "rag_chunks_eval_v3";
    private static final UUID ORG_ID = UUID.nameUUIDFromBytes("org-bdzdc".getBytes(StandardCharsets.UTF_8));
    private static final UUID KB_ID = UUID.nameUUIDFromBytes("kb-bdzdc".getBytes(StandardCharsets.UTF_8));
    private static final int TOP_K = 10;
    private static final int CANDIDATE_LIMIT = 50;

    /** 150 题评估集里全部 8 道 NO_RETRIEVAL 标注题（见 eval/datasets/eval-set-v2.jsonl）。 */
    private static final Set<String> NO_RETRIEVAL_IDS = Set.of(
            "q-136", "q-137", "q-138", "q-139", "q-140", "q-141", "q-142", "q-143");

    /**
     * 应答题（expect_refusal=false）里按 stride=5 抽样的 25 道，覆盖 easy/medium/hard 且分散在
     * 语料各章节，不用随机数以保证可复现：{@code ids[::5]}（125 道应答题里每隔 4 道取 1 道）。
     */
    private static final Set<String> ANSWERABLE_SAMPLE_IDS = new LinkedHashSet<>(List.of(
            "q-001", "q-006", "q-011", "q-016", "q-021", "q-026", "q-031", "q-036", "q-041", "q-046",
            "q-051", "q-056", "q-061", "q-066", "q-071", "q-076", "q-081", "q-086", "q-091", "q-096",
            "q-101", "q-106", "q-111", "q-116", "q-121"));

    private EvalFactVerificationRunner() {
    }

    public static void main(String[] args) throws Exception {
        Path evalSet = Path.of(args.length > 0 ? args[0] : "eval/datasets/eval-set-v2.jsonl");
        Path output = Path.of(args.length > 1 ? args[1]
                : "eval/predictions/no-retrieval-fact-verification-" + LocalDate.now() + ".jsonl");

        ObjectMapper mapper = new ObjectMapper();
        try (RestClient restClient = RestClient.builder(new HttpHost("localhost", 9200, "http")).build()) {
            RagElasticsearchProperties esProperties = new RagElasticsearchProperties();
            esProperties.setEnabled(true);
            esProperties.setEndpoint("http://localhost:9200");
            esProperties.setIndexName(INDEX_NAME);
            esProperties.setVectorDimensions(1024);

            EmbeddingClient embeddingClient = requireEmbeddingClient(mapper);
            RerankerClient reranker = requireReranker(mapper);
            PromptAssembler promptAssembler = new PromptAssembler();
            OpenAiCompatibleAnswerGenerator generator = requireGenerator(mapper, promptAssembler);

            ElasticsearchHybridCandidateSource candidateSource =
                    new ElasticsearchHybridCandidateSource(restClient, esProperties, mapper);
            HybridRetriever retriever = new HybridRetriever(candidateSource, embeddingClient, providerOf(reranker));
            RetrievalOptions options = new RetrievalOptions(CANDIDATE_LIMIT, TOP_K, true);

            List<ObjectNode> results = new ArrayList<>();
            int noRetrievalHits = 0;
            int answerableFalseRefusals = 0;
            int answerableRetrievalRefused = 0;

            for (String line : Files.readAllLines(evalSet, StandardCharsets.UTF_8)) {
                if (line.isBlank()) continue;
                JsonNode q = mapper.readTree(line);
                String id = q.path("id").asText();
                boolean isNoRetrieval = NO_RETRIEVAL_IDS.contains(id);
                boolean isAnswerableSample = ANSWERABLE_SAMPLE_IDS.contains(id);
                if (!isNoRetrieval && !isAnswerableSample) continue;
                String question = q.path("question").asText();

                long startedAt = System.nanoTime();
                RetrievalResult retrieval = retriever.retrieveWithDecision(ORG_ID, KB_ID, question, options);
                boolean factVerificationRefused = false;
                String answerSnippet = "";
                if (!retrieval.refused()) {
                    StringBuilder answer = new StringBuilder();
                    List<Citation> citations = List.of(); // 报告只关心是否拒答，不需要真实引用构造
                    FactVerificationGate gate = new FactVerificationGate(citations, event -> {
                        if (event.content() != null) answer.append(event.content());
                    });
                    generator.streamWithMetrics(question, retrieval.chunks(), null, gate.asConsumer());
                    gate.flush();
                    factVerificationRefused = gate.refusedByFactVerification();
                    answerSnippet = answer.length() > 80 ? answer.substring(0, 80) + "…" : answer.toString();
                }
                long elapsedMs = (System.nanoTime() - startedAt) / 1_000_000;

                if (isNoRetrieval && factVerificationRefused) noRetrievalHits++;
                if (isAnswerableSample) {
                    if (retrieval.refused()) answerableRetrievalRefused++;
                    else if (factVerificationRefused) answerableFalseRefusals++;
                }

                ObjectNode record = mapper.createObjectNode();
                record.put("id", id);
                record.put("category", isNoRetrieval ? "no_retrieval_labeled" : "answerable_sample");
                record.put("question", question);
                record.put("retrieval_refused", retrieval.refused());
                record.put("fact_verification_refused", factVerificationRefused);
                record.put("answer_snippet", answerSnippet);
                record.put("latency_ms", elapsedMs);
                results.add(record);
                System.out.println("[" + id + "] " + (isNoRetrieval ? "NO_RETRIEVAL" : "answerable")
                        + " retrieval_refused=" + retrieval.refused()
                        + " fact_verification_refused=" + factVerificationRefused
                        + " (" + elapsedMs + "ms)");
            }

            Files.createDirectories(output.getParent());
            Files.write(output, results.stream().map(ObjectNode::toString).toList(), StandardCharsets.UTF_8);

            int noRetrievalTotal = NO_RETRIEVAL_IDS.size();
            int answerableTotal = ANSWERABLE_SAMPLE_IDS.size();
            System.out.println();
            System.out.println("[summary] NO_RETRIEVAL 命中拒答 " + noRetrievalHits + "/" + noRetrievalTotal
                    + "（生成阶段事实核验）");
            System.out.println("[summary] 抽样应答题 " + answerableTotal + " 道："
                    + "检索阶段已拒答 " + answerableRetrievalRefused + "（不计入本机制误伤，属既有阈值行为）、"
                    + "事实核验误伤 " + answerableFalseRefusals);
            System.out.println("[done] 结果写入 " + output);
        }
    }

    private static EmbeddingClient requireEmbeddingClient(ObjectMapper mapper) {
        String endpoint = requireEnv("RAG_EMBEDDING_ENDPOINT");
        RagModelProperties.Embedding props = new RagModelProperties().getEmbedding();
        props.setEnabled(true);
        props.setEndpoint(endpoint);
        props.setModel(requireEnv("RAG_EMBEDDING_MODEL"));
        props.setApiKey(System.getenv("RAG_EMBEDDING_API_KEY"));
        props.setTimeoutMs(60_000);
        return new OpenAiCompatibleEmbeddingClient(props, mapper);
    }

    private static RerankerClient requireReranker(ObjectMapper mapper) {
        String endpoint = requireEnv("RAG_RERANK_ENDPOINT");
        RagModelProperties.Rerank props = new RagModelProperties().getRerank();
        props.setEnabled(true);
        props.setEndpoint(endpoint);
        props.setModel(requireEnv("RAG_RERANK_MODEL"));
        props.setApiKey(System.getenv("RAG_RERANK_API_KEY"));
        props.setTimeoutMs(60_000);
        return new OpenAiCompatibleRerankerClient(props, mapper);
    }

    private static OpenAiCompatibleAnswerGenerator requireGenerator(ObjectMapper mapper, PromptAssembler assembler) {
        String endpoint = requireEnv("RAG_GENERATION_ENDPOINT");
        RagModelProperties.Generation props = new RagModelProperties().getGeneration();
        props.setEnabled(true);
        props.setEndpoint(endpoint);
        props.setModel(requireEnv("RAG_GENERATION_MODEL"));
        props.setApiKey(System.getenv("RAG_GENERATION_API_KEY"));
        props.setTimeoutMs(60_000);
        return new OpenAiCompatibleAnswerGenerator(props, mapper, assembler);
    }

    private static String requireEnv(String key) {
        String value = System.getenv(key);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("缺少环境变量 " + key + "，本工具需要真实 embedding/rerank/生成服务，不做降级");
        }
        return value;
    }

    private static ObjectProvider<RerankerClient> providerOf(RerankerClient reranker) {
        return new ObjectProvider<>() {
            @Override public RerankerClient getObject(Object... a) { throw new UnsupportedOperationException(); }
            @Override public RerankerClient getObject() { throw new UnsupportedOperationException(); }
            @Override public RerankerClient getIfAvailable() { return reranker; }
            @Override public RerankerClient getIfUnique() { return reranker; }
        };
    }
}
