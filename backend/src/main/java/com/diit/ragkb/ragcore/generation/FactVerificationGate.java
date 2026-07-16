package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.List;
import java.util.function.Consumer;

/**
 * 拦截生成流首行的事实核验判断（{@code {"found": true|false}}），补上 rerank 阈值无法覆盖的
 * NO_RETRIEVAL 类拒答盲区：检索到的内容主题相关，但不包含问题的具体答案。
 *
 * <p>{@code SOURCE} 引用事件的发送被延迟到判定为 {@code found:true} 之后才转发，避免"已经展示引用
 * 来源却又拒答"的自相矛盾；判定为 {@code found:false} 时只发送一条固定文案的 {@code REFUSAL} 事件，
 * 丢弃已缓冲的内容与后续任何输出。首行缓冲超过 {@link #MAX_BUFFER_CHARS} 字符仍解析不出合法判断时
 * fail-open：把已缓冲内容当作正文透传，退化为本机制关闭前的原有行为，不引入新的拒答误伤。</p>
 *
 * <p>调用方在生成流结束后必须调用 {@link #flush()}：模型很可能整段输出就是判断行本身（prompt 要求
 * {@code found:false} 时不再输出其他内容），这时永远不会出现换行符、也可能不到 200 字符阈值，若不在
 * 流结束时补一次解析，内容会永远卡在缓冲区里、既不拒答也不透传。</p>
 */
public class FactVerificationGate {

    private static final int MAX_BUFFER_CHARS = 200;
    private static final String FIXED_REFUSAL_MESSAGE = "未在当前知识库中检索到该问题的具体答案";

    private enum Mode { BUFFERING, PASSTHROUGH, REFUSED }

    private final List<Citation> citations;
    private final Consumer<QueryEvent> downstream;
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final StringBuilder buffer = new StringBuilder();

    private Mode mode = Mode.BUFFERING;
    private boolean refusedByFactVerification = false;

    public FactVerificationGate(List<Citation> citations, Consumer<QueryEvent> downstream) {
        this.citations = citations;
        this.downstream = downstream;
    }

    public Consumer<QueryEvent> asConsumer() {
        return this::accept;
    }

    public boolean refusedByFactVerification() {
        return refusedByFactVerification;
    }

    /**
     * 生成流结束后必须调用：对仍处于缓冲状态（未遇到换行符、也未达到 200 字符阈值）的剩余内容做
     * 收尾解析——常见于模型整段输出恰好就是判断行本身、完全没有换行符的情况。
     */
    public void flush() {
        if (mode != Mode.BUFFERING) {
            return;
        }
        if (buffer.isEmpty()) {
            mode = Mode.PASSTHROUGH;
            flushCitations();
            return;
        }
        Boolean found = parseFound(buffer.toString().trim());
        if (found == null) {
            failOpen(buffer.toString());
        } else if (found) {
            mode = Mode.PASSTHROUGH;
            flushCitations();
        } else {
            mode = Mode.REFUSED;
            refusedByFactVerification = true;
            downstream.accept(QueryEvent.refusal(FIXED_REFUSAL_MESSAGE));
        }
    }

    private void accept(QueryEvent event) {
        if (mode == Mode.PASSTHROUGH) {
            downstream.accept(event);
            return;
        }
        if (mode == Mode.REFUSED) {
            return;
        }
        if (event.content() == null) {
            downstream.accept(event);
            return;
        }
        buffer.append(event.content());
        int newlineIndex = indexOfNewline(buffer);
        if (newlineIndex >= 0) {
            resolveFirstLine(newlineIndex);
        } else if (buffer.length() >= MAX_BUFFER_CHARS) {
            failOpen(buffer.toString());
        }
    }

    private void resolveFirstLine(int newlineIndex) {
        String line = buffer.substring(0, newlineIndex).trim();
        String rest = buffer.substring(newlineIndex + 1);
        Boolean found = parseFound(line);
        if (found == null) {
            failOpen(buffer.toString());
            return;
        }
        if (found) {
            mode = Mode.PASSTHROUGH;
            flushCitations();
            if (!rest.isEmpty()) {
                downstream.accept(QueryEvent.chunk(rest));
            }
        } else {
            mode = Mode.REFUSED;
            refusedByFactVerification = true;
            downstream.accept(QueryEvent.refusal(FIXED_REFUSAL_MESSAGE));
        }
    }

    private void failOpen(String content) {
        mode = Mode.PASSTHROUGH;
        flushCitations();
        downstream.accept(QueryEvent.chunk(content));
    }

    private void flushCitations() {
        citations.forEach(citation -> downstream.accept(QueryEvent.source(citation)));
    }

    private Boolean parseFound(String line) {
        try {
            JsonNode node = objectMapper.readTree(line);
            JsonNode foundNode = node.get("found");
            return foundNode != null && foundNode.isBoolean() ? foundNode.asBoolean() : null;
        } catch (Exception ex) {
            return null;
        }
    }

    private int indexOfNewline(StringBuilder text) {
        for (int i = 0; i < text.length(); i++) {
            if (text.charAt(i) == '\n') return i;
        }
        return -1;
    }
}
