package com.diit.ragkb.ragcore.conversation;

import java.time.Instant;
import java.util.UUID;

/**
 * 统一记忆索引（{@code rag_memory_v1}）里的一条记录。
 *
 * <p>{@code sessionId} 非空时代表短期会话内消息（{@link MemoryType#SESSION_MESSAGE}），
 * 为空时代表跨会话的长期画像条目（{@link MemoryType#PROFILE_ITEM}）。</p>
 */
public record MemoryRecord(
        String memoryId,
        UUID organizationId,
        UUID memberId,
        UUID sessionId,
        MemoryType type,
        String content,
        Instant createdAt
) {
    public MemoryRecord {
        if (organizationId == null || memberId == null || type == null || content == null || content.isBlank()) {
            throw new IllegalArgumentException("orgId、memberId、type、content 均不能为空");
        }
        if (type == MemoryType.PROFILE_ITEM && sessionId != null) {
            throw new IllegalArgumentException("画像条目(PROFILE_ITEM)不应携带 sessionId");
        }
        if (type == MemoryType.SESSION_MESSAGE && sessionId == null) {
            throw new IllegalArgumentException("会话消息(SESSION_MESSAGE)必须携带 sessionId");
        }
    }
}
