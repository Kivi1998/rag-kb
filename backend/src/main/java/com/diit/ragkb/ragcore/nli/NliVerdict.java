package com.diit.ragkb.ragcore.nli;

/** 单次 NLI（自然语言推理）判定结果：premise 是否蕴含 hypothesis 的三分类概率。 */
public record NliVerdict(String label, double entailmentProb, double neutralProb, double contradictionProb) {
}
