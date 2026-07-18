package com.diit.ragkb.ragcore.quickdocument;

import com.diit.ragkb.config.RagQuickDocumentProperties;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Redis 存储：内容 key 独立 TTL（{@code quickdoc:content:{docId}}），会话索引用 Set
 * （{@code quickdoc:session-index:{sessionId}}）。Set 不支持单成员 TTL，采用"读时自愈"策略——
 * 每次 {@link #findAllBySession} 都会对索引里的 docId 做存在性检查，清理已过期内容对应的
 * 陈旧引用，不依赖索引 Set 自身 TTL 与内容 key 精确同步。
 */
@Slf4j
public class RedisQuickDocumentStore implements QuickDocumentStore {

    private final StringRedisTemplate redisTemplate;
    private final RagQuickDocumentProperties properties;
    private final ObjectMapper objectMapper;

    public RedisQuickDocumentStore(StringRedisTemplate redisTemplate, RagQuickDocumentProperties properties,
                                   ObjectMapper objectMapper) {
        this.redisTemplate = Objects.requireNonNull(redisTemplate, "redisTemplate 不能为空");
        this.properties = Objects.requireNonNull(properties, "properties 不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
    }

    @Override
    public void save(QuickDocument document) {
        Duration ttl = Duration.ofHours(properties.getTtlHours());
        redisTemplate.opsForValue().set(contentKey(document.docId()), serialize(document), ttl);
        String indexKey = sessionIndexKey(document.sessionId());
        redisTemplate.opsForSet().add(indexKey, document.docId().toString());
        redisTemplate.expire(indexKey, ttl);
    }

    @Override
    public List<QuickDocument> findAllBySession(UUID sessionId) {
        String indexKey = sessionIndexKey(sessionId);
        Set<String> docIds = redisTemplate.opsForSet().members(indexKey);
        if (docIds == null || docIds.isEmpty()) {
            return List.of();
        }
        List<QuickDocument> result = new ArrayList<>();
        for (String docId : docIds) {
            String raw = redisTemplate.opsForValue().get(contentKey(UUID.fromString(docId)));
            if (raw == null) {
                // 内容 key 已过期，索引里的引用是陈旧的，清理掉不影响本次调用结果。
                redisTemplate.opsForSet().remove(indexKey, docId);
                continue;
            }
            result.add(deserialize(raw));
        }
        return result;
    }

    @Override
    public void delete(UUID sessionId, UUID docId) {
        redisTemplate.delete(contentKey(docId));
        redisTemplate.opsForSet().remove(sessionIndexKey(sessionId), docId.toString());
    }

    @Override
    public void touch(UUID sessionId, List<UUID> docIds) {
        if (docIds == null || docIds.isEmpty()) {
            return;
        }
        Duration ttl = Duration.ofHours(properties.getTtlHours());
        for (UUID docId : docIds) {
            redisTemplate.expire(contentKey(docId), ttl);
        }
        redisTemplate.expire(sessionIndexKey(sessionId), ttl);
    }

    private String contentKey(UUID docId) {
        return "quickdoc:content:" + docId;
    }

    private String sessionIndexKey(UUID sessionId) {
        return "quickdoc:session-index:" + sessionId;
    }

    private String serialize(QuickDocument document) {
        try {
            return objectMapper.writeValueAsString(document);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("序列化临时文档失败", ex);
        }
    }

    private QuickDocument deserialize(String raw) {
        try {
            return objectMapper.readValue(raw, QuickDocument.class);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("反序列化临时文档失败", ex);
        }
    }
}
