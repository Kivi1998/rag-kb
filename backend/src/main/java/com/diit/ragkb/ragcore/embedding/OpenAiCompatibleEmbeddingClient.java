package com.diit.ragkb.ragcore.embedding;

import com.diit.ragkb.config.RagModelProperties;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import com.diit.ragkb.ragcore.model.ModelClientException;
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

/** OpenAI `/v1/embeddings` 兼容客户端，支持本地模型网关和云端兼容服务。 */
public class OpenAiCompatibleEmbeddingClient implements EmbeddingClient {

    private final RagModelProperties.Embedding properties;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public OpenAiCompatibleEmbeddingClient(RagModelProperties.Embedding properties, ObjectMapper objectMapper) {
        this(properties, objectMapper, HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(requirePositiveTimeout(properties)))
                .build());
    }

    OpenAiCompatibleEmbeddingClient(RagModelProperties.Embedding properties, ObjectMapper objectMapper,
                                    HttpClient httpClient) {
        this.properties = Objects.requireNonNull(properties, "embedding 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
        this.httpClient = Objects.requireNonNull(httpClient, "httpClient 不能为空");
        validate(properties);
    }

    @Override
    public EmbeddingResult embed(List<String> texts) {
        if (texts == null || texts.isEmpty()) {
            return new EmbeddingResult(properties.getModel(), List.of());
        }
        if (texts.stream().anyMatch(text -> text == null || text.isBlank())) {
            throw new IllegalArgumentException("Embedding 输入不能包含空文本");
        }

        List<List<Float>> allVectors = new ArrayList<>(texts.size());
        String modelVersion = properties.getModel();
        int batchSize = properties.getBatchSize();
        for (int start = 0; start < texts.size(); start += batchSize) {
            int end = Math.min(start + batchSize, texts.size());
            BatchResponse response = embedBatch(texts.subList(start, end));
            allVectors.addAll(response.vectors());
            if (response.modelVersion() != null && !response.modelVersion().isBlank()) {
                modelVersion = response.modelVersion();
            }
        }
        return new EmbeddingResult(modelVersion, allVectors);
    }

    private BatchResponse embedBatch(List<String> texts) {
        String body;
        try {
            body = objectMapper.writeValueAsString(new EmbeddingRequest(properties.getModel(), texts));
        } catch (IOException ex) {
            throw new ModelClientException("序列化 Embedding 请求失败", ex);
        }
        IOException lastIoError = null;
        for (int attempt = 1; attempt <= properties.getMaxAttempts(); attempt++) {
            try {
                HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(properties.getEndpoint()))
                        .timeout(Duration.ofMillis(properties.getTimeoutMs()))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(body));
                if (properties.getApiKey() != null && !properties.getApiKey().isBlank()) {
                    builder.header("Authorization", "Bearer " + properties.getApiKey());
                }
                HttpResponse<String> response = httpClient.send(
                        builder.build(), HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() < 200 || response.statusCode() >= 300) {
                    if (isRetryableStatus(response.statusCode()) && attempt < properties.getMaxAttempts()) {
                        backoff(attempt);
                        continue;
                    }
                    throw new ModelClientException("Embedding 服务返回 HTTP " + response.statusCode());
                }
                return parseResponse(response.body(), texts.size());
            } catch (IOException ex) {
                lastIoError = ex;
                if (attempt < properties.getMaxAttempts()) {
                    backoff(attempt);
                    continue;
                }
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
                throw new ModelClientException("调用 Embedding 服务被中断", ex);
            } catch (IllegalArgumentException ex) {
                throw new ModelClientException("Embedding 服务配置或响应不合法", ex);
            }
        }
        throw new ModelClientException("调用 Embedding 服务失败", lastIoError);
    }

    private boolean isRetryableStatus(int status) {
        return status == 429 || status >= 500;
    }

    private void backoff(int completedAttempt) {
        long delay = Math.min(5_000L, properties.getRetryBackoffMs() * completedAttempt);
        if (delay <= 0) return;
        try {
            Thread.sleep(delay);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new ModelClientException("Embedding 重试等待被中断", ex);
        }
    }

    private BatchResponse parseResponse(String body, int expectedSize) throws IOException {
        JsonNode root = objectMapper.readTree(body);
        JsonNode data = root.path("data");
        if (!data.isArray() || data.size() != expectedSize) {
            throw new ModelClientException("Embedding 响应数量与请求不一致");
        }
        List<VectorItem> items = new ArrayList<>(expectedSize);
        for (JsonNode node : data) {
            int index = node.path("index").asInt(-1);
            JsonNode embedding = node.path("embedding");
            if (index < 0 || index >= expectedSize || !embedding.isArray() || embedding.isEmpty()) {
                throw new ModelClientException("Embedding 响应缺少合法 index 或向量");
            }
            List<Float> vector = new ArrayList<>(embedding.size());
            for (JsonNode value : embedding) {
                if (!value.isNumber()) {
                    throw new ModelClientException("Embedding 向量包含非数值元素");
                }
                vector.add(value.floatValue());
            }
            items.add(new VectorItem(index, vector));
        }
        items.sort(Comparator.comparingInt(VectorItem::index));
        for (int i = 0; i < items.size(); i++) {
            if (items.get(i).index() != i) {
                throw new ModelClientException("Embedding 响应 index 不连续或重复");
            }
        }
        return new BatchResponse(root.path("model").asText(properties.getModel()),
                items.stream().map(VectorItem::vector).toList());
    }

    private static void validate(RagModelProperties.Embedding properties) {
        if (properties.getEndpoint() == null || properties.getEndpoint().isBlank()
                || properties.getModel() == null || properties.getModel().isBlank()
                || properties.getBatchSize() <= 0
                || properties.getMaxAttempts() < 1 || properties.getMaxAttempts() > 10
                || properties.getRetryBackoffMs() < 0 || properties.getRetryBackoffMs() > 60_000) {
            throw new IllegalArgumentException("Embedding endpoint/model/batch-size/max-attempts/retry-backoff-ms 配置不合法");
        }
        requirePositiveTimeout(properties);
    }

    private static long requirePositiveTimeout(RagModelProperties.Endpoint properties) {
        if (properties.getTimeoutMs() <= 0) {
            throw new IllegalArgumentException("模型服务 timeout-ms 必须大于 0");
        }
        return properties.getTimeoutMs();
    }

    private record EmbeddingRequest(String model, List<String> input) { }

    private record VectorItem(int index, List<Float> vector) { }

    private record BatchResponse(String modelVersion, List<List<Float>> vectors) { }
}
