package com.diit.ragkb.ragcore.conversation;

import java.time.Instant;

/** 一轮对话里的一条消息（用户提问或助手回答），跨 Redis/MongoDB/API 层复用的值对象。 */
public record ChatMessage(String role, String content, boolean keyFact, Instant createdAt) {

    public ChatMessage {
        if (role == null || role.isBlank() || content == null || content.isBlank() || createdAt == null) {
            throw new IllegalArgumentException("role、content、createdAt 均不能为空");
        }
    }

    public static ChatMessage user(String content, Instant createdAt) {
        return new ChatMessage("user", content, false, createdAt);
    }

    public static ChatMessage assistant(String content, Instant createdAt) {
        return new ChatMessage("assistant", content, false, createdAt);
    }
}
