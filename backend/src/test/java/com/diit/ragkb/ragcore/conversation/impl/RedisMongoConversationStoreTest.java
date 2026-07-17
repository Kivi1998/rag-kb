package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.ragcore.conversation.ChatMessage;
import com.diit.ragkb.ragcore.conversation.ChatMessageDocument;
import com.diit.ragkb.ragcore.conversation.ChatMessageRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/** 写直达行为 + Redis 不可达时的 fail-open 降级。 */
class RedisMongoConversationStoreTest {

    private StringRedisTemplate redisTemplate;
    private ListOperations<String, String> listOperations;
    private ChatMessageRepository repository;
    private RedisMongoConversationStore store;

    private final UUID orgId = UUID.randomUUID();
    private final UUID kbId = UUID.randomUUID();
    private final UUID memberId = UUID.randomUUID();
    private final UUID sessionId = UUID.randomUUID();

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        redisTemplate = mock(StringRedisTemplate.class);
        listOperations = mock(ListOperations.class);
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        repository = mock(ChatMessageRepository.class);
        ObjectMapper objectMapper = new ObjectMapper().registerModule(new JavaTimeModule());
        store = new RedisMongoConversationStore(redisTemplate, repository, objectMapper);
    }

    @Test
    void appendMessageWritesThroughToBothRedisAndMongo() {
        ChatMessage message = ChatMessage.user("那它过了还能退吗", Instant.now());

        store.appendMessage(orgId, kbId, memberId, sessionId, message);

        verify(repository, times(1)).save(any(ChatMessageDocument.class));
        verify(listOperations, times(1)).rightPush(anyString(), anyString());
        verify(listOperations, times(1)).trim(anyString(), eq(-50L), eq(-1L));
        verify(redisTemplate, times(1)).expire(anyString(), any(Duration.class));
    }

    @Test
    void redisUnavailableDegradesGracefullyOnWrite() {
        ChatMessage message = ChatMessage.user("问题", Instant.now());
        doThrow(new RuntimeException("Redis 连接失败")).when(listOperations).rightPush(anyString(), anyString());

        store.appendMessage(orgId, kbId, memberId, sessionId, message);

        // Mongo 写入仍然发生：写直达策略下持久化优先于热路径缓存。
        verify(repository, times(1)).save(any(ChatMessageDocument.class));
    }

    @Test
    void redisUnavailableDegradesGracefullyOnRead() {
        when(listOperations.range(anyString(), eq(0L), eq(-1L)))
                .thenThrow(new RuntimeException("Redis 连接失败"));

        List<ChatMessage> result = store.recentRawMessages(orgId, sessionId);

        assertTrue(result.isEmpty());
    }

    @Test
    void archivedMessagesQueriesMongoWithMemberIdScope() {
        // 回归测试：查询本身必须携带 memberId，不能只依赖调用方（ChatSessionService）预先做归属校验，
        // 否则未来绕过 Service 层直接调用本方法的路径会造成同组织内跨成员越权读取。
        ChatMessageDocument document = new ChatMessageDocument(sessionId, orgId, kbId, memberId, "user", "你好",
                false, Instant.now(), null);
        when(repository.findBySessionIdAndOrganizationIdAndMemberIdOrderByCreatedAtAsc(sessionId, orgId, memberId))
                .thenReturn(List.of(document));

        List<ChatMessage> result = store.archivedMessages(orgId, memberId, sessionId);

        assertEquals(1, result.size());
        assertEquals("你好", result.get(0).content());
        verify(repository, times(1))
                .findBySessionIdAndOrganizationIdAndMemberIdOrderByCreatedAtAsc(sessionId, orgId, memberId);
    }

    @Test
    void deleteSessionRemovesMongoMessagesAndRedisWindow() {
        store.deleteSession(orgId, memberId, sessionId);

        verify(repository, times(1))
                .deleteBySessionIdAndOrganizationIdAndMemberId(sessionId, orgId, memberId);
        verify(redisTemplate, times(1)).delete("chat:session:" + sessionId + ":messages");
    }

    @Test
    void deleteSessionToleratesRedisFailureSinceKeyHasTtl() {
        // Redis 是非权威缓存、且滑动窗口 key 本身有 TTL，删除失败不应让整个删除操作失败。
        when(redisTemplate.delete(anyString())).thenThrow(new RuntimeException("Redis 连接失败"));

        store.deleteSession(orgId, memberId, sessionId);

        verify(repository, times(1))
                .deleteBySessionIdAndOrganizationIdAndMemberId(sessionId, orgId, memberId);
    }

    @Test
    void recentRawMessagesDeserializesFromRedis() {
        ChatMessage message = ChatMessage.assistant("重疾险犹豫期过了还能退保吗", Instant.parse("2026-07-15T00:00:00Z"));
        String json = "{\"role\":\"assistant\",\"content\":\"重疾险犹豫期过了还能退保吗\",\"keyFact\":false,"
                + "\"createdAt\":\"2026-07-15T00:00:00Z\"}";
        when(listOperations.range(anyString(), eq(0L), eq(-1L))).thenReturn(List.of(json));

        List<ChatMessage> result = store.recentRawMessages(orgId, sessionId);

        assertEquals(1, result.size());
        assertEquals(message.content(), result.get(0).content());
    }
}
