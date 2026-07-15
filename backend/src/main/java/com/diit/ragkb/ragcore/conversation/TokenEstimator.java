package com.diit.ragkb.ragcore.conversation;

/**
 * 粗略 token 估算：中文字符按 1 token/字，其余字符按 4 字符/token 估算，
 * 不追求精确（不同模型分词器结果不同），只用于滑动窗口预算判断，够用即可。
 */
public final class TokenEstimator {

    private TokenEstimator() {
    }

    public static int estimate(String text) {
        if (text == null || text.isEmpty()) {
            return 0;
        }
        int cjkCount = 0;
        int otherCount = 0;
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (isCjk(c)) {
                cjkCount++;
            } else {
                otherCount++;
            }
        }
        return cjkCount + (int) Math.ceil(otherCount / 4.0);
    }

    private static boolean isCjk(char c) {
        return (c >= 0x4E00 && c <= 0x9FFF) || (c >= 0x3400 && c <= 0x4DBF);
    }
}
