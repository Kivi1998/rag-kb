package com.diit.ragkb.ragcore.generation;

/** 上游生成服务返回或可安全推导出的用量摘要；不包含回答正文。 */
public record GenerationMetrics(String model, Integer promptTokens, Integer completionTokens, long outputCharacters) {
    public GenerationMetrics {
        model = model == null || model.isBlank() ? "unknown" : model;
        if (promptTokens != null && promptTokens < 0 || completionTokens != null && completionTokens < 0
                || outputCharacters < 0) {
            throw new IllegalArgumentException("生成用量不能为负数");
        }
    }

    public static GenerationMetrics none() {
        return new GenerationMetrics("none", null, null, 0);
    }
}
