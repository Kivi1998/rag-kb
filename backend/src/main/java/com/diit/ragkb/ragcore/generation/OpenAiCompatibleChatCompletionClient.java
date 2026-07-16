package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.config.RagModelProperties;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** OpenAI Chat Completions 兼容的非流式单轮调用（{@code stream:false}），复用现有 DeepSeek 生成端点配置。 */
public class OpenAiCompatibleChatCompletionClient implements ChatCompletionClient {

    private final RagModelProperties.Generation properties;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public OpenAiCompatibleChatCompletionClient(RagModelProperties.Generation properties, ObjectMapper objectMapper) {
        this(properties, objectMapper, HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(properties.getTimeoutMs()))
                .version(HttpClient.Version.HTTP_1_1)
                .build());
    }

    OpenAiCompatibleChatCompletionClient(RagModelProperties.Generation properties, ObjectMapper objectMapper,
                                        HttpClient httpClient) {
        this.properties = Objects.requireNonNull(properties, "generation 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
        this.httpClient = Objects.requireNonNull(httpClient, "httpClient 不能为空");
        if (properties.getEndpoint() == null || properties.getEndpoint().isBlank()
                || properties.getModel() == null || properties.getModel().isBlank()) {
            throw new IllegalArgumentException("Generation endpoint/model 必须配置");
        }
    }

    @Override
    public String complete(String systemPrompt, String userPrompt) {
        try {
            Map<String, Object> requestBody = new LinkedHashMap<>();
            requestBody.put("model", properties.getModel());
            requestBody.put("stream", false);
            requestBody.put("messages", List.of(
                    Map.of("role", "system", "content", systemPrompt),
                    Map.of("role", "user", "content", userPrompt)));
            String body = objectMapper.writeValueAsString(requestBody);
            HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(properties.getEndpoint()))
                    .timeout(Duration.ofMillis(properties.getTimeoutMs()))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));
            if (properties.getApiKey() != null && !properties.getApiKey().isBlank()) {
                builder.header("Authorization", "Bearer " + properties.getApiKey());
            }
            HttpRequest request = builder.build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new ModelClientException("生成服务返回 HTTP " + response.statusCode());
            }
            JsonNode root = objectMapper.readTree(response.body());
            JsonNode choices = root.path("choices");
            if (!choices.isArray() || choices.isEmpty()) {
                throw new ModelClientException("生成服务响应缺少 choices");
            }
            return choices.get(0).path("message").path("content").asText();
        } catch (IOException ex) {
            throw new ModelClientException("调用生成服务失败", ex);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new ModelClientException("调用生成服务被中断", ex);
        }
    }
}
