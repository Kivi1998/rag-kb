package com.diit.ragkb.ragcore.nli;

/** 自然语言推理（NLI）客户端：判断 premise 是否蕴含 hypothesis。 */
public interface NliClient {

    NliVerdict check(String premise, String hypothesis);
}
