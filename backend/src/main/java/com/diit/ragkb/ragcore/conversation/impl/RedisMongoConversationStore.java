package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.ragcore.conversation.ChatMessage;
import com.diit.ragkb.ragcore.conversation.ChatMessageDocument;
import com.diit.ragkb.ragcore.conversation.ChatMessageRepository;
import com.diit.ragkb.ragcore.conversation.ConversationStore;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * {@link ConversationStore} 的 Redis+MongoDB 实现。Redis 只保留最近
 * {@link #REDIS_WINDOW_SIZE} 条原始消息（有界，避免无限增长），MongoDB 保留全部历史。
 */
@Slf4j
public class RedisMongoConversationStore implements ConversationStore {

    private static final int REDIS_WINDOW_SIZE = 50;
    private static final long REDIS_KEY_TTL_SECONDS = 3 * 60 * 60L; // 略长于 IDLE 上限(2小时)，允许自然过期

    private final StringRedisTemplate memoryRedisTemplate;
    private final ChatMessageRepository chatMessageRepository;
    private final ObjectMapper objectMapper;

    public RedisMongoConversationStore(StringRedisTemplate memoryRedisTemplate,
                                       ChatMessageRepository chatMessageRepository, ObjectMapper objectMapper) {
        this.memoryRedisTemplate = Objects.requireNonNull(memoryRedisTemplate, "memoryRedisTemplate 不能为空");
        this.chatMessageRepository = Objects.requireNonNull(chatMessageRepository, "chatMessageRepository 不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
    }

    @Override
    public void appendMessage(UUID organizationId, UUID kbId, UUID memberId, UUID sessionId, ChatMessage message) {
        // 写直达：MongoDB 先写(持久化系统记录)，Redis 后写(热路径，允许失败不影响持久性)。
        chatMessageRepository.save(new ChatMessageDocument(sessionId, organizationId, kbId, memberId,
                message.role(), message.content(), message.keyFact(), message.createdAt()));
        try {
            String key = redisKey(sessionId);
            memoryRedisTemplate.opsForList().rightPush(key, serialize(message));
            memoryRedisTemplate.opsForList().trim(key, -REDIS_WINDOW_SIZE, -1);
            memoryRedisTemplate.expire(key, java.time.Duration.ofSeconds(REDIS_KEY_TTL_SECONDS));
        } catch (RuntimeException ex) {
            log.warn("会话记忆 Redis 写入失败，本轮消息已持久化到 MongoDB，不影响问答: sessionId={}", sessionId, ex);
        }
    }

    @Override
    public List<ChatMessage> recentRawMessages(UUID organizationId, UUID sessionId) {
        try {
            List<String> raw = memoryRedisTemplate.opsForList().range(redisKey(sessionId), 0, -1);
            if (raw == null || raw.isEmpty()) {
                return List.of();
            }
            List<ChatMessage> messages = new ArrayList<>(raw.size());
            for (String json : raw) {
                messages.add(deserialize(json));
            }
            return messages;
        } catch (RuntimeException ex) {
            log.warn("会话记忆 Redis 读取失败，本轮问答退化为无短期记忆的单轮问答: sessionId={}", sessionId, ex);
            return List.of();
        }
    }

    @Override
    public List<ChatMessage> archivedMessages(UUID organizationId, UUID memberId, UUID sessionId) {
        return chatMessageRepository
                .findBySessionIdAndOrganizationIdAndMemberIdOrderByCreatedAtAsc(sessionId, organizationId, memberId)
                .stream()
                .map(doc -> new ChatMessage(doc.getRole(), doc.getContent(), doc.isKeyFact(), doc.getCreatedAt()))
                .toList();
    }

    private String redisKey(UUID sessionId) {
        return "chat:session:" + sessionId + ":messages";
    }

    private String serialize(ChatMessage message) {
        try {
            return objectMapper.writeValueAsString(message);
        } catch (com.fasterxml.jackson.core.JsonProcessingException ex) {
            throw new IllegalStateException("序列化会话消息失败", ex);
        }
    }

    private ChatMessage deserialize(String json) {
        try {
            var node = objectMapper.readTree(json);
            return new ChatMessage(node.path("role").asText(), node.path("content").asText(),
                    node.path("keyFact").asBoolean(false), Instant.parse(node.path("createdAt").asText()));
        } catch (Exception ex) {
            throw new IllegalStateException("反序列化会话消息失败", ex);
        }
    }
}
