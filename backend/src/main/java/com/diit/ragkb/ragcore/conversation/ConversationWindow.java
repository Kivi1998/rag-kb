package com.diit.ragkb.ragcore.conversation;

import java.util.List;

/**
 * 滑动窗口组装结果：{@code summary} 非空时代表触发了摘要压缩（替换掉最旧的部分消息），
 * {@code recentMessages} 是保留的原文（最近若干轮 + 关键事实消息，未被压缩）。
 */
public record ConversationWindow(String summary, List<ChatMessage> recentMessages) {

    public ConversationWindow {
        recentMessages = recentMessages == null ? List.of() : List.copyOf(recentMessages);
    }

    public boolean hasSummary() {
        return summary != null && !summary.isBlank();
    }
}
