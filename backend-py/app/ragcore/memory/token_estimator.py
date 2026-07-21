"""粗略 token 估算:中文字符按 1 token/字,其余字符按 4 字符/token。

对应 Java 版 `ragcore/conversation/TokenEstimator.java`。
不追求精确(不同模型分词器结果不同),只用于滑动窗口预算判断,够用即可。
"""

from __future__ import annotations


def estimate(text: str | None) -> int:
    """中文字符按 1 token 计,其余按 4 字符计 token;空文本返回 0。"""
    if not text:
        return 0
    cjk_count = 0
    other_count = 0
    for ch in text:
        code = ord(ch)
        if (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF):
            cjk_count += 1
        else:
            other_count += 1
    return cjk_count + (other_count + 3) // 4
