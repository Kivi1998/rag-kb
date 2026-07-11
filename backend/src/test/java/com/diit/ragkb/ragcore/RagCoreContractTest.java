package com.diit.ragkb.ragcore;

import com.diit.ragkb.ragcore.chunk.ChunkingOptions;
import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.IngestionStateMachine;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.model.QueryEventType;
import com.diit.ragkb.ragcore.retrieval.RetrievalOptions;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RagCoreContractTest {

    @Test
    void 应定义完整的入库生命周期() {
        assertEquals(List.of(
                IngestionStatus.QUEUED,
                IngestionStatus.PARSING,
                IngestionStatus.CHUNKING,
                IngestionStatus.EMBEDDING,
                IngestionStatus.INDEXING,
                IngestionStatus.READY,
                IngestionStatus.FAILED,
                IngestionStatus.DELETING
        ), List.of(IngestionStatus.values()));

        assertTrue(IngestionStateMachine.canTransition(IngestionStatus.QUEUED, IngestionStatus.PARSING));
        assertTrue(IngestionStateMachine.canTransition(IngestionStatus.FAILED, IngestionStatus.QUEUED));
        assertFalse(IngestionStateMachine.canTransition(IngestionStatus.READY, IngestionStatus.INDEXING));
        assertThrows(IllegalArgumentException.class,
                () -> IngestionStateMachine.requireTransition(IngestionStatus.DELETING, IngestionStatus.READY));
    }

    @Test
    void 应使用统一的查询流事件协议() {
        Citation citation = new Citation(UUID.randomUUID(), "设计说明.md", List.of("检索"), "片段", 1, null, null, 0.91);

        assertEquals(QueryEventType.CHUNK, QueryEvent.chunk("回答").type());
        assertEquals(citation, QueryEvent.source(citation).citation());
        assertEquals(QueryEventType.REFUSAL, QueryEvent.refusal("证据不足").type());
        assertEquals(QueryEventType.DONE, QueryEvent.done().type());
        assertEquals(QueryEventType.ERROR, QueryEvent.error("服务异常").type());
    }

    @Test
    void 查询流事件应映射为稳定的小写SSE事件名() {
        assertEquals("chunk", QueryEventType.CHUNK.wireName());
        assertEquals("source", QueryEventType.SOURCE.wireName());
        assertEquals("refusal", QueryEventType.REFUSAL.wireName());
        assertEquals("done", QueryEventType.DONE.wireName());
        assertEquals("error", QueryEventType.ERROR.wireName());

        assertEquals("chunk", QueryEvent.chunk("回答").sseEventName());
        assertEquals("source", QueryEvent.source(new Citation(
                UUID.randomUUID(), "设计说明.md", List.of(), "片段", null, null, null, 0.91)).sseEventName());
        assertEquals("refusal", QueryEvent.refusal("证据不足").sseEventName());
        assertEquals("done", QueryEvent.done().sseEventName());
        assertEquals("error", QueryEvent.error("服务异常").sseEventName());
    }

    @Test
    void 应拒绝无效的检索与切分参数() {
        assertThrows(IllegalArgumentException.class, () -> new ChunkingOptions(100, 100, true));
        assertThrows(IllegalArgumentException.class, () -> new RetrievalOptions(5, 6, true));
    }
}
