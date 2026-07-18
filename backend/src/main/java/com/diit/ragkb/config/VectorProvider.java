package com.diit.ragkb.config;

/** 知识库向量候选来源；外部请求不得覆盖该服务端配置。 */
public enum VectorProvider {
    ELASTICSEARCH,
    SHADOW,
    MILVUS
}
