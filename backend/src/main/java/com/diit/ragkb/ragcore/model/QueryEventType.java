package com.diit.ragkb.ragcore.model;

/** SSE 查询流事件类型。 */
public enum QueryEventType {
    CHUNK("chunk"),
    SOURCE("source"),
    REFUSAL("refusal"),
    DONE("done"),
    ERROR("error");

    private final String wireName;

    QueryEventType(String wireName) {
        this.wireName = wireName;
    }

    /**
     * SSE 事件头使用的小写稳定名称。
     *
     * <p>对外协议必须调用此方法，不能依赖 {@link #name()} 的 Java 枚举名称。</p>
     */
    public String wireName() {
        return wireName;
    }
}
