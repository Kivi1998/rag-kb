package com.diit.ragkb.ragcore.index;

/** Elasticsearch 索引创建、Bulk 写入或删除失败。 */
public class ElasticsearchIndexException extends RuntimeException {
    public ElasticsearchIndexException(String message) { super(message); }
    public ElasticsearchIndexException(String message, Throwable cause) { super(message, cause); }
}
