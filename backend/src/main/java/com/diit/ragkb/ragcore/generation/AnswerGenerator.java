package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Consumer;

/** 基于已检索上下文生成答案，按统一事件协议流式输出。 */
public interface AnswerGenerator {

    void stream(String question, List<RetrievedChunk> contexts, Consumer<QueryEvent> eventConsumer);

    /** 默认实现保留旧适配器兼容性，并至少统计输出字符数。 */
    default GenerationMetrics streamWithMetrics(String question, List<RetrievedChunk> contexts,
                                                Consumer<QueryEvent> eventConsumer) {
        return streamWithMetrics(question, contexts, null, eventConsumer);
    }

    /**
     * {@code additionalSystemContext} 非空时拼进 System Prompt（如用户画像背景信息），
     * 只影响生成风格，不影响 contexts 本身。默认实现忽略该参数、退化为不带画像的普通生成，
     * 供不支持此能力的实现（如测试替身）安全兼容。
     */
    default GenerationMetrics streamWithMetrics(String question, List<RetrievedChunk> contexts,
                                                String additionalSystemContext, Consumer<QueryEvent> eventConsumer) {
        AtomicLong outputCharacters = new AtomicLong();
        stream(question, contexts, event -> {
            if (event.content() != null) outputCharacters.addAndGet(event.content().length());
            eventConsumer.accept(event);
        });
        return new GenerationMetrics(modelId(), null, null, outputCharacters.get());
    }

    default String modelId() {
        return "unknown";
    }
}
