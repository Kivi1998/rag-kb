package com.diit.ragkb.ragcore.conversation;

import java.util.List;

/**
 * 一次问答里，记忆子系统准备好的上下文：{@code resolvedQuestion} 用于检索（指代消解后），
 * {@code profileSystemContext} 仅用于生成阶段的 System 上下文注入（可能为空字符串）。
 *
 * <p>{@code resolvedQuestionVector} 是画像检索时已经算好的 {@code resolvedQuestion} 向量，
 * 供检索阶段直接复用，避免同一句 resolvedQuestion 被检索链路再次调用 Embedding；
 * 画像向量化失败（fail-open）或没有画像子系统时为 {@code null}，检索阶段会退回自己算。</p>
 */
public record MemoryContext(String resolvedQuestion, String profileSystemContext, List<Float> resolvedQuestionVector) {

    public boolean hasProfileContext() {
        return profileSystemContext != null && !profileSystemContext.isBlank();
    }
}
