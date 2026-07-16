package com.diit.ragkb.ragcore.generation;

import java.util.List;

/** {@link AnswerSelfChecker} 的核查结果；{@code unsupportedClaims} 为空表示没有发现问题。 */
public record SelfCheckResult(List<String> unsupportedClaims) {

    public SelfCheckResult {
        unsupportedClaims = unsupportedClaims == null ? List.of() : List.copyOf(unsupportedClaims);
    }

    public boolean hasUnsupportedClaims() {
        return !unsupportedClaims.isEmpty();
    }

    public static SelfCheckResult none() {
        return new SelfCheckResult(List.of());
    }

    /** 拼成追加在 {@code done} 之前的提醒文案；调用方需先检查 {@link #hasUnsupportedClaims()}。 */
    public String buildWarningMessage() {
        StringBuilder message = new StringBuilder("⚠️ 自检提示：以下内容未在参考资料中找到明确支撑，请以资料原文为准核实：");
        for (String claim : unsupportedClaims) {
            message.append("\n- ").append(claim);
        }
        return message.toString();
    }
}
