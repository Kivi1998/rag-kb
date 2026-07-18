package com.diit.ragkb.ragcore.quickdocument;

import com.diit.ragkb.config.RagQuickDocumentProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.SetOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@SuppressWarnings("unchecked")
class RedisQuickDocumentStoreTest {

    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();

    @Test
    void saveWritesContentAndIndexWithConfiguredTtl() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        ValueOperations<String, String> valueOps = mock(ValueOperations.class);
        SetOperations<String, String> setOps = mock(SetOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        when(redisTemplate.opsForSet()).thenReturn(setOps);
        RagQuickDocumentProperties properties = new RagQuickDocumentProperties();
        properties.setTtlHours(2);
        RedisQuickDocumentStore store = new RedisQuickDocumentStore(redisTemplate, properties, objectMapper);
        UUID sessionId = UUID.randomUUID();
        QuickDocument document = new QuickDocument(UUID.randomUUID(), sessionId, "笔记.md", "正文", 2, Instant.now());

        store.save(document);

        verify(valueOps).set(eq("quickdoc:content:" + document.docId()), any(), eq(Duration.ofHours(2)));
        verify(setOps).add("quickdoc:session-index:" + sessionId, document.docId().toString());
        verify(redisTemplate).expire("quickdoc:session-index:" + sessionId, Duration.ofHours(2));
    }

    @Test
    void findAllBySessionSelfHealsStaleIndexEntries() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        ValueOperations<String, String> valueOps = mock(ValueOperations.class);
        SetOperations<String, String> setOps = mock(SetOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        when(redisTemplate.opsForSet()).thenReturn(setOps);
        RedisQuickDocumentStore store = new RedisQuickDocumentStore(redisTemplate, new RagQuickDocumentProperties(),
                objectMapper);
        UUID sessionId = UUID.randomUUID();
        UUID liveDocId = UUID.randomUUID();
        UUID staleDocId = UUID.randomUUID(); // 内容 key 已过期（TTL 到期），索引里还留着陈旧引用
        when(setOps.members("quickdoc:session-index:" + sessionId))
                .thenReturn(Set.of(liveDocId.toString(), staleDocId.toString()));
        QuickDocument liveDocument = new QuickDocument(liveDocId, sessionId, "活的.md", "内容", 2, Instant.now());
        when(valueOps.get("quickdoc:content:" + liveDocId)).thenReturn(serialize(liveDocument));
        when(valueOps.get("quickdoc:content:" + staleDocId)).thenReturn(null);

        List<QuickDocument> result = store.findAllBySession(sessionId);

        assertEquals(1, result.size());
        assertEquals(liveDocId, result.get(0).docId());
        verify(setOps).remove("quickdoc:session-index:" + sessionId, staleDocId.toString());
        verify(setOps, never()).remove("quickdoc:session-index:" + sessionId, liveDocId.toString());
    }

    @Test
    void touchRefreshesTtlForHitDocumentsAndSessionIndex() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        RagQuickDocumentProperties properties = new RagQuickDocumentProperties();
        properties.setTtlHours(2);
        RedisQuickDocumentStore store = new RedisQuickDocumentStore(redisTemplate, properties, objectMapper);
        UUID sessionId = UUID.randomUUID();
        UUID docId = UUID.randomUUID();

        store.touch(sessionId, List.of(docId));

        verify(redisTemplate).expire("quickdoc:content:" + docId, Duration.ofHours(2));
        verify(redisTemplate).expire("quickdoc:session-index:" + sessionId, Duration.ofHours(2));
    }

    @Test
    void touchWithEmptyDocIdsDoesNothing() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        RedisQuickDocumentStore store = new RedisQuickDocumentStore(redisTemplate, new RagQuickDocumentProperties(),
                objectMapper);

        store.touch(UUID.randomUUID(), List.of());

        verify(redisTemplate, times(0)).expire(any(), any());
    }

    private String serialize(QuickDocument document) {
        try {
            return objectMapper.writeValueAsString(document);
        } catch (Exception ex) {
            throw new RuntimeException(ex);
        }
    }
}
