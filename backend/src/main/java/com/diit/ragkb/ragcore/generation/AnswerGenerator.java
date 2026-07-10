package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.List;
import java.util.function.Consumer;

/** 基于已检索上下文生成答案，按统一事件协议流式输出。 */
public interface AnswerGenerator {

    void stream(String question, List<RetrievedChunk> contexts, Consumer<QueryEvent> eventConsumer);
}
