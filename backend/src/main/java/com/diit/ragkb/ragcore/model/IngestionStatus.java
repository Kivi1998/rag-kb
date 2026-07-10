package com.diit.ragkb.ragcore.model;

/**
 * 文档入库状态机。
 *
 * <p>状态只允许按队列、解析、切分、向量化、索引、就绪的顺序向前推进；任一处理中状态均可进入
 * {@link #FAILED}，删除请求进入 {@link #DELETING}。</p>
 */
public enum IngestionStatus {
    QUEUED,
    PARSING,
    CHUNKING,
    EMBEDDING,
    INDEXING,
    READY,
    FAILED,
    DELETING
}
