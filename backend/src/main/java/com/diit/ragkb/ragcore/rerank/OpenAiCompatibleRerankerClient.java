package com.diit.ragkb.ragcore.rerank;

import com.diit.ragkb.config.RagModelProperties;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;

/** 兼容常见 Cross-Encoder 网关的 Rerank 协议客户端。 */
public class OpenAiCompatibleRerankerClient implements RerankerClient {

    private final RagModelProperties.Rerank properties;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public OpenAiCompatibleRerankerClient(RagModelProperties.Rerank properties, ObjectMapper objectMapper) {
        this(properties, objectMapper, HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(requirePositiveTimeout(properties)))
                // 强制 HTTP/1.1：部分本地模型网关（如 Xinference）不支持明文 h2c 升级协商。
                .version(HttpClient.Version.HTTP_1_1)
                .build());
    }

    OpenAiCompatibleRerankerClient(RagModelProperties.Rerank properties, ObjectMapper objectMapper,
                                   HttpClient httpClient) {
        this.properties = Objects.requireNonNull(properties, "rerank 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
        this.httpClient = Objects.requireNonNull(httpClient, "httpClient 不能为空");
        if (properties.getEndpoint() == null || properties.getEndpoint().isBlank()
                || properties.getModel() == null || properties.getModel().isBlank()) {
            throw new IllegalArgumentException("Rerank endpoint/model 必须配置");
        }
        requirePositiveTimeout(properties);
    }

    @Override
    public List<RetrievedChunk> rerank(String query, List<RetrievedChunk> candidates, int topK) {
        if (query == null || query.isBlank() || candidates == null || candidates.isEmpty() || topK <= 0) {
            return List.of();
        }
        try {
            List<String> documents = candidates.stream().map(candidate -> candidate.chunk().content()).toList();
            String body = objectMapper.writeValueAsString(new RerankRequest(properties.getModel(), query, documents, topK));
            HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(properties.getEndpoint()))
                    .timeout(Duration.ofMillis(properties.getTimeoutMs()))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body));
            if (properties.getApiKey() != null && !properties.getApiKey().isBlank()) {
                builder.header("Authorization", "Bearer " + properties.getApiKey());
            }
            HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new ModelClientException("Rerank 服务返回 HTTP " + response.statusCode());
            }
            return parseResponse(response.body(), candidates, topK);
        } catch (IOException ex) {
            throw new ModelClientException("调用 Rerank 服务失败", ex);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new ModelClientException("调用 Rerank 服务被中断", ex);
        } catch (IllegalArgumentException ex) {
            throw new ModelClientException("Rerank 服务配置或响应不合法", ex);
        }
    }

    private List<RetrievedChunk> parseResponse(String body, List<RetrievedChunk> candidates, int topK) throws IOException {
        JsonNode results = objectMapper.readTree(body).path("results");
        if (!results.isArray()) {
            throw new ModelClientException("Rerank 响应缺少 results 数组");
        }
        List<ScoredCandidate> scored = new ArrayList<>();
        for (JsonNode result : results) {
            int index = result.path("index").asInt(-1);
            JsonNode score = result.has("relevance_score") ? result.path("relevance_score") : result.path("score");
            if (index < 0 || index >= candidates.size() || !score.isNumber()) {
                throw new ModelClientException("Rerank 响应包含非法候选索引或分数");
            }
            RetrievedChunk old = candidates.get(index);
            scored.add(new ScoredCandidate(index, new RetrievedChunk(old.chunk(), old.bm25Rank(), old.vectorRank(),
                    old.rrfScore(), score.doubleValue(), score.doubleValue())));
        }
        return scored.stream().sorted(Comparator.comparingDouble(item -> -item.chunk().finalScore()))
                .limit(topK).map(ScoredCandidate::chunk).toList();
    }

    private static long requirePositiveTimeout(RagModelProperties.Endpoint properties) {
        if (properties.getTimeoutMs() <= 0) {
            throw new IllegalArgumentException("模型服务 timeout-ms 必须大于 0");
        }
        return properties.getTimeoutMs();
    }

    private record RerankRequest(String model, String query, List<String> documents, int top_n) { }

    private record ScoredCandidate(int index, RetrievedChunk chunk) { }
}
