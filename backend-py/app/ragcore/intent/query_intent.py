"""检索意图枚举。对应 Java 版 `ragcore/intent/QueryIntent.java`。

`UNKNOWN` 是分类失败的内部哨兵值(超时/异常/输出不匹配任一合法标签),只在分类流程
内部流转,写入 `rag_query_audit` 时映射为 None。
"""

from __future__ import annotations

from enum import Enum


class QueryIntent(str, Enum):
    """领域无关、基于查询结构(而非知识库主题)的检索意图分类,用于驱动 RRF 融合权重。"""

    PRECISE_LOOKUP = "precise-lookup"
    """精确检索型: 含具体错误码/型号/参数名/专有名词/编号等精确定位信息。"""
    SEMANTIC = "semantic"
    """语义理解型: 概念性、宽泛的"是什么/为什么/怎么样"式提问。"""
    COMPARATIVE = "comparative"
    """对比推理型: 涉及比较多个实体/方法/方案的异同或优劣。"""
    OUT_OF_SCOPE = "out-of-scope"
    """闲聊/超纲型: 与知识库内容无关,或含糊到无法归入前三类。"""
    UNKNOWN = "unknown"
    """分类失败的内部哨兵值,从不写入审计表(映射为 None)。"""


def weights_for_intent(intent: QueryIntent) -> tuple[float, float]:
    """把意图分类结果映射为 (bm25_weight, vector_weight)。

    取值参考: 精确检索型(代码符号/错误码)依赖关键词命中,BM25 主导;
    语义型与对比型依赖语义召回,向量主导。`OUT_OF_SCOPE` / `UNKNOWN` 维持等权,
    让 RRF 自然给出兜底排序而不是直接拒答。
    """
    if intent == QueryIntent.PRECISE_LOOKUP:
        return (1.2, 0.8)
    if intent == QueryIntent.SEMANTIC:
        return (0.7, 1.3)
    if intent == QueryIntent.COMPARATIVE:
        return (0.9, 1.1)
    return (1.0, 1.0)
