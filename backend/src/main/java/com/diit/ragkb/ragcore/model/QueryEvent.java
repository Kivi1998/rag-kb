package com.diit.ragkb.ragcore.model;

/**
 * 查询流的统一输出事件。
 *
 * <p>CHUNK 使用 content；SOURCE 使用 citation；REFUSAL、ERROR 使用 message；DONE 不携带业务负载。</p>
 */
public record QueryEvent(QueryEventType type, String content, Citation citation, String message) {

    public static QueryEvent chunk(String content) {
        return new QueryEvent(QueryEventType.CHUNK, content, null, null);
    }

    public static QueryEvent source(Citation citation) {
        return new QueryEvent(QueryEventType.SOURCE, null, citation, null);
    }

    public static QueryEvent refusal(String message) {
        return new QueryEvent(QueryEventType.REFUSAL, null, null, message);
    }

    public static QueryEvent done() {
        return new QueryEvent(QueryEventType.DONE, null, null, null);
    }

    public static QueryEvent error(String message) {
        return new QueryEvent(QueryEventType.ERROR, null, null, message);
    }
}
