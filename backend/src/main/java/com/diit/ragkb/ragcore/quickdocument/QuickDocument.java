package com.diit.ragkb.ragcore.quickdocument;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

/** 会话内临时文档：不写入知识库，不参与切块/向量化/索引，只在 Redis 里按 TTL 存活。 */
public record QuickDocument(UUID docId, UUID sessionId, String filename, String content, int characterCount,
                            Instant createdAt) {
    public QuickDocument {
        Objects.requireNonNull(docId, "docId 不能为空");
        Objects.requireNonNull(sessionId, "sessionId 不能为空");
        Objects.requireNonNull(filename, "filename 不能为空");
        Objects.requireNonNull(content, "content 不能为空");
        Objects.requireNonNull(createdAt, "createdAt 不能为空");
    }
}
