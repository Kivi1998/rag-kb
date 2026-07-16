package com.diit.ragkb.ragcore.model;

import java.util.Objects;

/**
 * 查询流的统一输出事件。
 *
 * <p>CHUNK 使用 content；SOURCE 使用 citation；REFUSAL、ERROR、SELF_CHECK_WARNING 使用 message；
 * DONE 不携带业务负载。</p>
 */
public record QueryEvent(QueryEventType type, String content, Citation citation, String message) {

    public QueryEvent {
        Objects.requireNonNull(type, "type 不能为空");
    }

    /**
     * 返回可直接写入 SSE {@code event:} 头的小写事件名。
     */
    public String sseEventName() {
        return type.wireName();
    }

    public static QueryEvent chunk(String content) {
        return new QueryEvent(QueryEventType.CHUNK, content, null, null);
    }

    public static QueryEvent source(Citation citation) {
        return new QueryEvent(QueryEventType.SOURCE, null, citation, null);
    }

    public static QueryEvent refusal(String message) {
        return new QueryEvent(QueryEventType.REFUSAL, null, null, message);
    }

    public static QueryEvent selfCheckWarning(String message) {
        return new QueryEvent(QueryEventType.SELF_CHECK_WARNING, null, null, message);
    }

    public static QueryEvent done() {
        return new QueryEvent(QueryEventType.DONE, null, null, null);
    }

    public static QueryEvent error(String message) {
        return new QueryEvent(QueryEventType.ERROR, null, null, message);
    }
}
