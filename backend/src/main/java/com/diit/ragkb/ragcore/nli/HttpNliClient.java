package com.diit.ragkb.ragcore.nli;

import com.diit.ragkb.config.RagNliProperties;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Objects;

/** 调用本机部署的 {@code nli-gateway}（`POST /nli`）。 */
public class HttpNliClient implements NliClient {

    private final RagNliProperties properties;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public HttpNliClient(RagNliProperties properties, ObjectMapper objectMapper) {
        this(properties, objectMapper, HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(requirePositiveTimeout(properties)))
                .version(HttpClient.Version.HTTP_1_1)
                .build());
    }

    HttpNliClient(RagNliProperties properties, ObjectMapper objectMapper, HttpClient httpClient) {
        this.properties = Objects.requireNonNull(properties, "nli 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
        this.httpClient = Objects.requireNonNull(httpClient, "httpClient 不能为空");
        if (properties.getEndpoint() == null || properties.getEndpoint().isBlank()) {
            throw new IllegalArgumentException("NLI endpoint 必须配置");
        }
        requirePositiveTimeout(properties);
    }

    @Override
    public NliVerdict check(String premise, String hypothesis) {
        try {
            String body = objectMapper.writeValueAsString(new NliRequest(premise, hypothesis));
            HttpRequest request = HttpRequest.newBuilder(URI.create(properties.getEndpoint()))
                    .timeout(Duration.ofMillis(properties.getTimeoutMs()))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new ModelClientException("NLI 服务返回 HTTP " + response.statusCode());
            }
            return parseResponse(response.body());
        } catch (IOException ex) {
            throw new ModelClientException("调用 NLI 服务失败", ex);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new ModelClientException("调用 NLI 服务被中断", ex);
        } catch (IllegalArgumentException ex) {
            throw new ModelClientException("NLI 服务配置或响应不合法", ex);
        }
    }

    private NliVerdict parseResponse(String responseBody) throws IOException {
        JsonNode root = objectMapper.readTree(responseBody);
        JsonNode label = root.path("label");
        JsonNode entailment = root.path("entailment_prob");
        JsonNode neutral = root.path("neutral_prob");
        JsonNode contradiction = root.path("contradiction_prob");
        if (!label.isTextual() || !entailment.isNumber() || !neutral.isNumber() || !contradiction.isNumber()) {
            throw new ModelClientException("NLI 响应缺少必要字段");
        }
        return new NliVerdict(label.asText(), entailment.asDouble(), neutral.asDouble(), contradiction.asDouble());
    }

    private static long requirePositiveTimeout(RagNliProperties properties) {
        if (properties.getTimeoutMs() <= 0) {
            throw new IllegalArgumentException("rag.nli.timeout-ms 必须大于 0");
        }
        return properties.getTimeoutMs();
    }

    private record NliRequest(String premise, String hypothesis) {
    }
}
