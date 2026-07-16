package com.diit.ragkb.ragcore.conversation;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;
import java.util.UUID;

/** MongoDB {@code chat_messages} 集合：会话消息长期存档（写直达，与 Redis 滑动窗口同步写入）。 */
@Document(collection = "chat_messages")
public class ChatMessageDocument {

    @Id
    private String id;
    private UUID sessionId;
    private UUID organizationId;
    private UUID kbId;
    private UUID memberId;
    private String role;
    private String content;
    private boolean keyFact;
    private Instant createdAt;

    public ChatMessageDocument() {
    }

    public ChatMessageDocument(UUID sessionId, UUID organizationId, UUID kbId, UUID memberId, String role,
                              String content, boolean keyFact, Instant createdAt) {
        this.sessionId = sessionId;
        this.organizationId = organizationId;
        this.kbId = kbId;
        this.memberId = memberId;
        this.role = role;
        this.content = content;
        this.keyFact = keyFact;
        this.createdAt = createdAt;
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public UUID getSessionId() { return sessionId; }
    public void setSessionId(UUID sessionId) { this.sessionId = sessionId; }
    public UUID getOrganizationId() { return organizationId; }
    public void setOrganizationId(UUID organizationId) { this.organizationId = organizationId; }
    public UUID getKbId() { return kbId; }
    public void setKbId(UUID kbId) { this.kbId = kbId; }
    public UUID getMemberId() { return memberId; }
    public void setMemberId(UUID memberId) { this.memberId = memberId; }
    public String getRole() { return role; }
    public void setRole(String role) { this.role = role; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public boolean isKeyFact() { return keyFact; }
    public void setKeyFact(boolean keyFact) { this.keyFact = keyFact; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
}
