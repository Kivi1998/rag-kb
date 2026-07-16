package com.diit.ragkb.ragcore.generation;

/**
 * 上游生成服务返回或可安全推导出的用量摘要；不包含回答正文。
 *
 * <p>{@code factVerificationRefusalReason} 非空表示 {@link FactVerificationGate} 在生成阶段判定
 * 参考资料不包含具体答案（{@code found:false}），触发了事实核验拒答——调用方（{@code QueryController}）
 * 据此把审计状态记为 REFUSED，而不是 COMPLETED。</p>
 */
public record GenerationMetrics(String model, Integer promptTokens, Integer completionTokens, long outputCharacters,
                                 String factVerificationRefusalReason) {
    public GenerationMetrics {
        model = model == null || model.isBlank() ? "unknown" : model;
        if (promptTokens != null && promptTokens < 0 || completionTokens != null && completionTokens < 0
                || outputCharacters < 0) {
            throw new IllegalArgumentException("生成用量不能为负数");
        }
    }

    public GenerationMetrics(String model, Integer promptTokens, Integer completionTokens, long outputCharacters) {
        this(model, promptTokens, completionTokens, outputCharacters, null);
    }

    public GenerationMetrics withFactVerificationRefusalReason(String reason) {
        return new GenerationMetrics(model, promptTokens, completionTokens, outputCharacters, reason);
    }

    public static GenerationMetrics none() {
        return new GenerationMetrics("none", null, null, 0);
    }
}
