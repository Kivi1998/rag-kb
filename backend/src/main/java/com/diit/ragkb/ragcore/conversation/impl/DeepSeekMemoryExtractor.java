package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.ragcore.conversation.MemoryExtractor;
import com.diit.ragkb.ragcore.conversation.MemoryItemStore;
import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.generation.ChatCompletionClient;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * 从一轮问答提炼候选画像条目（PREFERENCE/FACT/GOAL），语义去重后写入长期记忆。
 * 所有异常在内部捕获记录，绝不向调用方传播——这是异步增强，不应影响已返回给用户的回答。
 */
@Slf4j
public class DeepSeekMemoryExtractor implements MemoryExtractor {

    private static final String SYSTEM_PROMPT = "从下面这轮问答里提炼值得长期记住的用户偏好/事实/长期目标"
            + "（没有就返回空数组，不要为了凑数编造）。严格按以下 JSON 格式输出，不要有其他文字：\n"
            + "{\"items\":[{\"type\":\"PREFERENCE|FACT|GOAL\",\"content\":\"一句话描述\",\"importance\":0.0到1.0之间的数字}]}";

    private final ChatCompletionClient chatCompletionClient;
    private final EmbeddingClient embeddingClient;
    private final MemoryItemStore memoryItemStore;
    private final ObjectMapper objectMapper;

    public DeepSeekMemoryExtractor(ChatCompletionClient chatCompletionClient, EmbeddingClient embeddingClient,
                                   MemoryItemStore memoryItemStore, ObjectMapper objectMapper) {
        this.chatCompletionClient = Objects.requireNonNull(chatCompletionClient, "chatCompletionClient 不能为空");
        this.embeddingClient = Objects.requireNonNull(embeddingClient, "embeddingClient 不能为空");
        this.memoryItemStore = Objects.requireNonNull(memoryItemStore, "memoryItemStore 不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
    }

    @Override
    public void extractAndStore(UUID organizationId, UUID memberId, UUID sessionId, String question, String answer) {
        try {
            String userPrompt = "用户问题：" + question + "\n助手回答：" + answer;
            String response = chatCompletionClient.complete(SYSTEM_PROMPT, userPrompt);
            JsonNode root = parseJson(response);
            JsonNode items = root.path("items");
            if (!items.isArray() || items.isEmpty()) {
                return;
            }
            for (JsonNode item : items) {
                processCandidate(organizationId, memberId, sessionId, item);
            }
        } catch (RuntimeException ex) {
            log.warn("画像提炼失败，不影响本轮已返回的回答: sessionId={}", sessionId, ex);
        }
    }

    private void processCandidate(UUID organizationId, UUID memberId, UUID sessionId, JsonNode item) {
        String type = item.path("type").asText("");
        String content = item.path("content").asText("");
        double importance = item.path("importance").isNumber() ? item.path("importance").asDouble() : 0.5;
        if (content.isBlank() || !isValidType(type)) {
            return;
        }
        EmbeddingResult embedding = embeddingClient.embed(List.of(content));
        if (embedding.vectors().isEmpty()) {
            return;
        }
        List<Float> vector = embedding.vectors().get(0);
        var existing = memoryItemStore.findSimilarExisting(organizationId, memberId, vector);
        if (existing.isPresent()) {
            log.debug("画像条目语义去重，跳过: memberId={}, content={}", memberId, content);
            return;
        }
        memoryItemStore.createItem(organizationId, memberId, type, content, importance, vector, sessionId);
    }

    private boolean isValidType(String type) {
        return "PREFERENCE".equals(type) || "FACT".equals(type) || "GOAL".equals(type);
    }

    private JsonNode parseJson(String response) {
        try {
            String cleaned = response == null ? "{}" : response.strip();
            if (cleaned.startsWith("```")) {
                cleaned = cleaned.replaceAll("^```(?:json)?\\s*", "").replaceAll("```\\s*$", "");
            }
            return objectMapper.readTree(cleaned);
        } catch (Exception ex) {
            throw new IllegalStateException("画像提炼响应解析失败", ex);
        }
    }
}
