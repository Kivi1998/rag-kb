package com.diit.ragkb.ragcore.intent;

/**
 * 领域无关、基于查询结构（而非知识库主题）的检索意图分类，用于驱动 RRF 融合权重。
 *
 * <p>{@code UNKNOWN} 是分类失败的内部哨兵值（超时/异常/输出不匹配任一合法标签），只在
 * 分类流程内部流转，写入 {@code rag_query_audit} 时映射为 {@code null}。</p>
 */
public enum QueryIntent {
    /** 精确检索型：含具体错误码/型号/参数名/专有名词/编号等精确定位信息。 */
    PRECISE_LOOKUP,
    /** 语义理解型：概念性、宽泛的"是什么/为什么/怎么样"式提问。 */
    SEMANTIC,
    /** 对比推理型：涉及比较多个实体/方法/方案。 */
    COMPARATIVE,
    /** 闲聊/超纲型：与知识库内容无关，或含糊到无法归入前三类。 */
    OUT_OF_SCOPE,
    /** 分类失败的内部哨兵值，从不写入审计表（映射为 null）。 */
    UNKNOWN
}
