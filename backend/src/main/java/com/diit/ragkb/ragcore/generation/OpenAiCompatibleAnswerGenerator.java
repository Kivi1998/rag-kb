package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.config.RagModelProperties;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Objects;
import java.util.function.Consumer;

/** OpenAI Chat Completions 兼容的上游流式生成适配器。 */
public class OpenAiCompatibleAnswerGenerator implements AnswerGenerator {

    private final RagModelProperties.Generation properties;
    private final ObjectMapper objectMapper;
    private final PromptAssembler promptAssembler;
    private final HttpClient httpClient;

    public OpenAiCompatibleAnswerGenerator(RagModelProperties.Generation properties, ObjectMapper objectMapper,
                                           PromptAssembler promptAssembler) {
        this(properties, objectMapper, promptAssembler, HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(requirePositiveTimeout(properties))).build());
    }

    OpenAiCompatibleAnswerGenerator(RagModelProperties.Generation properties, ObjectMapper objectMapper,
                                    PromptAssembler promptAssembler, HttpClient httpClient) {
        this.properties = Objects.requireNonNull(properties, "generation 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
        this.promptAssembler = Objects.requireNonNull(promptAssembler, "promptAssembler 不能为空");
        this.httpClient = Objects.requireNonNull(httpClient, "httpClient 不能为空");
        if (properties.getEndpoint() == null || properties.getEndpoint().isBlank()
                || properties.getModel() == null || properties.getModel().isBlank()) {
            throw new IllegalArgumentException("Generation endpoint/model 必须配置");
        }
        requirePositiveTimeout(properties);
    }

    @Override
    public void stream(String question, List<RetrievedChunk> contexts, Consumer<QueryEvent> eventConsumer) {
        try {
            String body = objectMapper.writeValueAsString(new ChatCompletionRequest(properties.getModel(), List.of(
                    new ChatMessage("system", promptAssembler.systemPrompt()),
                    new ChatMessage("user", promptAssembler.userPrompt(question, contexts))), true, 0));
            HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(properties.getEndpoint()))
                    .timeout(Duration.ofMillis(properties.getTimeoutMs()))
                    .header("Content-Type", "application/json")
                    .header("Accept", "text/event-stream")
                    .POST(HttpRequest.BodyPublishers.ofString(body));
            if (properties.getApiKey() != null && !properties.getApiKey().isBlank()) {
                builder.header("Authorization", "Bearer " + properties.getApiKey());
            }
            HttpResponse<InputStream> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofInputStream());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new ModelClientException("Generation 服务返回 HTTP " + response.statusCode());
            }
            try (InputStream bodyStream = response.body()) {
                parseSse(bodyStream, objectMapper, eventConsumer);
            }
        } catch (IOException ex) {
            throw new ModelClientException("调用 Generation 服务失败", ex);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new ModelClientException("调用 Generation 服务被中断", ex);
        } catch (IllegalArgumentException ex) {
            throw new ModelClientException("Generation 服务配置或响应不合法", ex);
        }
    }

    static void parseSse(InputStream input, ObjectMapper objectMapper, Consumer<QueryEvent> eventConsumer) throws IOException {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (!line.startsWith("data:")) continue;
                String data = line.substring(5).trim();
                if ("[DONE]".equals(data)) return;
                JsonNode delta = objectMapper.readTree(data).path("choices").path(0).path("delta");
                JsonNode content = delta.path("content");
                if (content.isTextual() && !content.asText().isEmpty()) {
                    eventConsumer.accept(QueryEvent.chunk(content.asText()));
                }
            }
        }
    }

    private static long requirePositiveTimeout(RagModelProperties.Endpoint properties) {
        if (properties.getTimeoutMs() <= 0) {
            throw new IllegalArgumentException("模型服务 timeout-ms 必须大于 0");
        }
        return properties.getTimeoutMs();
    }

    private record ChatCompletionRequest(String model, List<ChatMessage> messages, boolean stream, int temperature) { }
    private record ChatMessage(String role, String content) { }
}
