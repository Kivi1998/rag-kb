package com.diit.ragkb.ragcore.conversation;

import com.diit.ragkb.ragcore.model.Citation;

import java.time.Instant;
import java.util.List;

/** 一轮对话里的一条消息（用户提问或助手回答），跨 Redis/MongoDB/API 层复用的值对象。
 * citations 只有 assistant 角色、且这次字段上线后新产生的消息才会有值；user 消息和
 * 旧消息该字段为 null，前端按"没有引用"处理，不做历史回填。 */
public record ChatMessage(String role, String content, boolean keyFact, Instant createdAt, List<Citation> citations) {

    public ChatMessage {
        if (role == null || role.isBlank() || content == null || content.isBlank() || createdAt == null) {
            throw new IllegalArgumentException("role、content、createdAt 均不能为空");
        }
    }

    public static ChatMessage user(String content, Instant createdAt) {
        return new ChatMessage("user", content, false, createdAt, null);
    }

    public static ChatMessage assistant(String content, Instant createdAt) {
        return new ChatMessage("assistant", content, false, createdAt, null);
    }

    public static ChatMessage assistant(String content, Instant createdAt, List<Citation> citations) {
        return new ChatMessage("assistant", content, false, createdAt, citations);
    }
}
