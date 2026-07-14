import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.config.RagModelProperties;
import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.embedding.OpenAiCompatibleEmbeddingClient;
import com.diit.ragkb.ragcore.index.ElasticsearchChunkIndex;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.rerank.OpenAiCompatibleRerankerClient;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.diit.ragkb.ragcore.retrieval.ElasticsearchHybridCandidateSource;
import com.diit.ragkb.ragcore.retrieval.HybridRetriever;
import com.diit.ragkb.ragcore.retrieval.RetrievalOptions;
import com.diit.ragkb.ragcore.retrieval.RetrievalResult;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.http.HttpHost;
import org.elasticsearch.client.Request;
import org.elasticsearch.client.RestClient;
import org.springframework.beans.factory.ObjectProvider;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 用产品真实检索代码对评估集跑检索，输出 predicted JSONL。
 *
 * <p>复用生产类：{@link ElasticsearchChunkIndex}（入库）、
 * {@link ElasticsearchHybridCandidateSource} + {@link HybridRetriever}（检索）。
 * 数据源是 EvalCorpusIndexer dump 的 corpus-index.jsonl（V3 真实切块产物），
 * chunk_id 与评估集 ground_truth 完全一致，无需映射。</p>
 *
 * <p><b>Embedding 说明</b>：评测环境内网 Xinference 不可达时，本工具向 ES 写入占位
 * 单位向量（仅为通过索引层的维度校验），并给 HybridRetriever 注入一个必然抛
 * {@link ModelClientException} 的 EmbeddingClient——这会触发产品内建的
 * BM25-only 降级路径（与生产中 embedding 短暂不可用的行为一致）。
 * 因此本工具产出的指标是「V3 切分 + BM25 单路召回」的真实值，
 * 不包含 kNN 向量召回与 Rerank 的贡献。</p>
 *
 * <p>用法（repo 根目录）：
 * <pre>
 * java -cp "eval/scripts:$(cat /tmp/rag-cp.txt):backend/target/classes" EvalRetrievalRunner \
 *   eval/datasets/corpus-index.jsonl \
 *   eval/datasets/eval-set-2026Q3.jsonl \
 *   eval/predictions/predicted-v3-bm25-YYYYMMDD.jsonl
 * </pre></p>
 */
public final class EvalRetrievalRunner {

    private static final String INDEX_NAME = "rag_chunks_eval_v3";
    private static final int VECTOR_DIMS = 1024;
    private static final UUID ORG_ID = UUID.nameUUIDFromBytes("org-bdzdc".getBytes(StandardCharsets.UTF_8));
    private static final UUID KB_ID = UUID.nameUUIDFromBytes("kb-bdzdc".getBytes(StandardCharsets.UTF_8));
    private static final int TOP_K = 10;

    private EvalRetrievalRunner() {
    }

    public static void main(String[] args) throws Exception {
        Path corpusIndex = Path.of(args.length > 0 ? args[0] : "eval/datasets/corpus-index.jsonl");
        Path evalSet = Path.of(args.length > 1 ? args[1] : "eval/datasets/eval-set-2026Q3.jsonl");
        Path output = Path.of(args.length > 2 ? args[2] : "eval/predictions/predicted-v3-bm25.jsonl");

        ObjectMapper mapper = new ObjectMapper();
        try (RestClient restClient = RestClient.builder(new HttpHost("localhost", 9200, "http")).build()) {
            RagElasticsearchProperties properties = new RagElasticsearchProperties();
            properties.setEnabled(true);
            properties.setEndpoint("http://localhost:9200");
            properties.setIndexName(INDEX_NAME);
            properties.setVectorDimensions(VECTOR_DIMS);

            // ── 1. 组装模型客户端：环境变量配置齐 → 完整混合检索；否则 BM25-only 降级 ──
            EmbeddingClient embeddingClient = buildEmbeddingClient(mapper);
            RerankerClient reranker = buildReranker(mapper);
            boolean hybrid = embeddingClient != null;
            System.out.println("[mode] " + (hybrid
                    ? "完整混合检索（真实 embedding" + (reranker != null ? " + rerank）" : "，无 rerank）")
                    : "BM25-only（embedding 未配置/不可达）"));

            // ── 2. 重建独立评测索引（不触碰生产 rag_chunks_v1）──
            deleteIndexIfExists(restClient);
            List<Chunk> chunks = loadChunks(corpusIndex, mapper);
            System.out.println("[index] 读取 corpus-index：" + chunks.size() + " chunks");
            ElasticsearchChunkIndex chunkIndex = new ElasticsearchChunkIndex(restClient, properties, mapper);
            int batch = 32;
            for (int i = 0; i < chunks.size(); i += batch) {
                List<Chunk> slice = chunks.subList(i, Math.min(i + batch, chunks.size()));
                List<List<Float>> vectors;
                String modelVersion;
                if (hybrid) {
                    EmbeddingResult result = embeddingClient.embed(
                            slice.stream().map(Chunk::content).toList());
                    vectors = result.vectors();
                    modelVersion = result.modelVersion();
                } else {
                    vectors = java.util.Collections.nCopies(slice.size(), placeholderVector());
                    modelVersion = "eval-placeholder(BM25-only)";
                }
                chunkIndex.upsert(slice, vectors, modelVersion);
                System.out.println("[index] 已入库 " + Math.min(i + batch, chunks.size()) + "/" + chunks.size());
            }
            restClient.performRequest(new Request("POST", "/" + INDEX_NAME + "/_refresh"));
            System.out.println("[index] 已写入并 refresh 索引 " + INDEX_NAME);

            // ── 3. 组装产品检索链 ──
            ElasticsearchHybridCandidateSource candidateSource =
                    new ElasticsearchHybridCandidateSource(restClient, properties, mapper);
            EmbeddingClient queryEmbedding = hybrid ? embeddingClient : texts -> {
                throw new ModelClientException("评测环境 embedding 服务不可达（走 BM25-only 降级）");
            };
            HybridRetriever retriever = new HybridRetriever(candidateSource, queryEmbedding,
                    providerOf(reranker));
            RetrievalOptions options = new RetrievalOptions(50, TOP_K, reranker != null);

            // ── 4. 逐题检索 ──
            List<String> lines = Files.readAllLines(evalSet, StandardCharsets.UTF_8);
            List<String> outLines = new ArrayList<>();
            int refusals = 0;
            for (String line : lines) {
                if (line.isBlank()) {
                    continue;
                }
                JsonNode q = mapper.readTree(line);
                String id = q.path("id").asText();
                String question = q.path("question").asText();
                RetrievalResult result = retriever.retrieveWithDecision(ORG_ID, KB_ID, question, options);

                ObjectNode prediction = mapper.createObjectNode();
                prediction.put("id", id);
                ArrayNode ids = prediction.putArray("predicted_chunk_ids");
                if (result.refused()) {
                    refusals++;
                    prediction.put("predicted_refusal", true);
                    prediction.put("predicted_refusal_reason", "NO_RETRIEVAL");
                } else {
                    for (RetrievedChunk rc : result.chunks()) {
                        ids.add(rc.chunk().id());
                    }
                    prediction.put("predicted_refusal", false);
                    prediction.putNull("predicted_refusal_reason");
                }
                prediction.put("reranked", false);
                outLines.add(mapper.writeValueAsString(prediction));
                System.out.println("[query] " + id + " → "
                        + (result.refused() ? "拒答(" + result.refusalReason() + ")" : ids.size() + " chunks"));
            }
            Files.createDirectories(output.getParent());
            Files.write(output, outLines, StandardCharsets.UTF_8);
            System.out.println("[done] " + outLines.size() + " 条预测（其中拒答 " + refusals + "）→ " + output);
        }
    }

    private static void deleteIndexIfExists(RestClient restClient) {
        try {
            restClient.performRequest(new Request("DELETE", "/" + INDEX_NAME));
            System.out.println("[index] 已删除旧评测索引 " + INDEX_NAME);
        } catch (org.elasticsearch.client.ResponseException ex) {
            if (ex.getResponse().getStatusLine().getStatusCode() != 404) {
                throw new IllegalStateException("删除旧评测索引失败", ex);
            }
        } catch (IOException ex) {
            throw new IllegalStateException("删除旧评测索引失败", ex);
        }
    }

    private static List<Chunk> loadChunks(Path corpusIndex, ObjectMapper mapper) throws IOException {
        List<Chunk> chunks = new ArrayList<>();
        for (String line : Files.readAllLines(corpusIndex, StandardCharsets.UTF_8)) {
            if (line.isBlank()) {
                continue;
            }
            JsonNode n = mapper.readTree(line);
            Map<String, String> metadata = new LinkedHashMap<>();
            n.path("metadata").fields().forEachRemaining(e -> metadata.put(e.getKey(), e.getValue().asText()));
            List<String> headingPath = new ArrayList<>();
            n.path("heading_path").forEach(h -> headingPath.add(h.asText()));
            chunks.add(new Chunk(
                    n.path("chunk_id").asText(),
                    ORG_ID,
                    KB_ID,
                    UUID.fromString(n.path("document_id").asText()),
                    n.path("ordinal").asInt(),
                    n.path("content").asText(),
                    headingPath,
                    n.path("document_name").asText(),
                    n.path("page_no").isNumber() ? n.path("page_no").asInt() : null,
                    n.path("line_start").isNumber() ? n.path("line_start").asInt() : null,
                    n.path("line_end").isNumber() ? n.path("line_end").asInt() : null,
                    n.path("language").asText("zh"),
                    n.path("content_hash").asText(),
                    metadata));
        }
        return chunks;
    }

    /** 占位向量：仅为通过索引层维度校验；BM25 查询路径不读取该字段。 */
    private static List<Float> placeholderVector() {
        List<Float> v = new ArrayList<>(VECTOR_DIMS);
        v.add(1.0f);
        for (int i = 1; i < VECTOR_DIMS; i++) {
            v.add(0.0f);
        }
        return List.copyOf(v);
    }

    /** 从 RAG_EMBEDDING_* 环境变量构造真实 embedding 客户端；配置不全返回 null（BM25-only）。 */
    private static EmbeddingClient buildEmbeddingClient(ObjectMapper mapper) {
        String endpoint = System.getenv("RAG_EMBEDDING_ENDPOINT");
        String model = System.getenv("RAG_EMBEDDING_MODEL");
        if (endpoint == null || endpoint.isBlank() || model == null || model.isBlank()) {
            return null;
        }
        RagModelProperties.Embedding props = new RagModelProperties().getEmbedding();
        props.setEnabled(true);
        props.setEndpoint(endpoint);
        props.setModel(model);
        props.setApiKey(System.getenv("RAG_EMBEDDING_API_KEY"));
        props.setTimeoutMs(60_000);
        return new OpenAiCompatibleEmbeddingClient(props, mapper);
    }

    /** 从 RAG_RERANK_* 环境变量构造真实 rerank 客户端；配置不全返回 null（跳过重排）。 */
    private static RerankerClient buildReranker(ObjectMapper mapper) {
        String endpoint = System.getenv("RAG_RERANK_ENDPOINT");
        String model = System.getenv("RAG_RERANK_MODEL");
        if (endpoint == null || endpoint.isBlank() || model == null || model.isBlank()) {
            return null;
        }
        RagModelProperties.Rerank props = new RagModelProperties().getRerank();
        props.setEnabled(true);
        props.setEndpoint(endpoint);
        props.setModel(model);
        props.setApiKey(System.getenv("RAG_RERANK_API_KEY"));
        props.setTimeoutMs(60_000);
        return new OpenAiCompatibleRerankerClient(props, mapper);
    }

    private static ObjectProvider<RerankerClient> providerOf(RerankerClient reranker) {
        return new ObjectProvider<>() {
            @Override
            public RerankerClient getObject(Object... a) {
                throw new UnsupportedOperationException();
            }

            @Override
            public RerankerClient getObject() {
                throw new UnsupportedOperationException();
            }

            @Override
            public RerankerClient getIfAvailable() {
                return reranker;
            }

            @Override
            public RerankerClient getIfUnique() {
                return reranker;
            }
        };
    }
}
