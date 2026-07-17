package com.diit.ragkb.ragcore.intent;

/** 对已解析（指代消解后）的查询问题做检索意图分类。 */
public interface QueryIntentClassifier {

    /** 分类失败（超时/异常/输出不可解析）时返回 {@link QueryIntent#UNKNOWN}，不抛出异常。 */
    QueryIntent classify(String question);
}
