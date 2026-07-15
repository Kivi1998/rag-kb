package com.diit.ragkb.ragcore.conversation;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;
import java.util.UUID;

/**
 * MongoDB {@code memory_items} 集合：用户画像条目（偏好/事实/长期目标），
 * 带 {@code importance}/{@code accessCount}/{@code lastAccessedAt} 供遗忘机制读时衰减计算。
 */
@Document(collection = "memory_items")
public class MemoryItemDocument {

    @Id
    private String id;
    private UUID memberId;
    private UUID organizationId;
    private String type;
    private String content;
    private double importance;
    private long accessCount;
    private Instant lastAccessedAt;
    private Instant createdAt;
    private UUID sourceSessionId;

    public MemoryItemDocument() {
    }

    public MemoryItemDocument(UUID memberId, UUID organizationId, String type, String content, double importance,
                             Instant createdAt, UUID sourceSessionId) {
        this.memberId = memberId;
        this.organizationId = organizationId;
        this.type = type;
        this.content = content;
        this.importance = importance;
        this.accessCount = 0;
        this.lastAccessedAt = createdAt;
        this.createdAt = createdAt;
        this.sourceSessionId = sourceSessionId;
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public UUID getMemberId() { return memberId; }
    public void setMemberId(UUID memberId) { this.memberId = memberId; }
    public UUID getOrganizationId() { return organizationId; }
    public void setOrganizationId(UUID organizationId) { this.organizationId = organizationId; }
    public String getType() { return type; }
    public void setType(String type) { this.type = type; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public double getImportance() { return importance; }
    public void setImportance(double importance) { this.importance = importance; }
    public long getAccessCount() { return accessCount; }
    public void setAccessCount(long accessCount) { this.accessCount = accessCount; }
    public Instant getLastAccessedAt() { return lastAccessedAt; }
    public void setLastAccessedAt(Instant lastAccessedAt) { this.lastAccessedAt = lastAccessedAt; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
    public UUID getSourceSessionId() { return sourceSessionId; }
    public void setSourceSessionId(UUID sourceSessionId) { this.sourceSessionId = sourceSessionId; }
}
