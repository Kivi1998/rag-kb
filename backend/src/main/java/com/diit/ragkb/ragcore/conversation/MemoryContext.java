package com.diit.ragkb.ragcore.conversation;

/**
 * 一次问答里，记忆子系统准备好的上下文：{@code resolvedQuestion} 用于检索（指代消解后），
 * {@code profileSystemContext} 仅用于生成阶段的 System 上下文注入（可能为空字符串）。
 */
public record MemoryContext(String resolvedQuestion, String profileSystemContext) {

    public boolean hasProfileContext() {
        return profileSystemContext != null && !profileSystemContext.isBlank();
    }
}
