package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.model.QueryEventType;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class FactVerificationGateTest {

    private final Citation citation = new Citation(UUID.randomUUID(), "doc.md", List.of(), "片段", null, null, null,
            0.9);

    @Test
    void foundTrueSplitAcrossChunksFlushesSourceThenRemainingContent() {
        List<QueryEvent> received = new ArrayList<>();
        FactVerificationGate gate = new FactVerificationGate(List.of(citation), received::add);

        gate.asConsumer().accept(QueryEvent.chunk("{\"foun"));
        gate.asConsumer().accept(QueryEvent.chunk("d\": true}\n答案正文"));
        gate.asConsumer().accept(QueryEvent.chunk("继续输出"));

        assertFalse(gate.refusedByFactVerification());
        assertEquals(QueryEventType.SOURCE, received.get(0).type());
        assertEquals("答案正文", received.get(1).content());
        assertEquals("继续输出", received.get(2).content());
    }

    @Test
    void foundFalseDiscardsBufferAndEmitsOnlyRefusal() {
        List<QueryEvent> received = new ArrayList<>();
        FactVerificationGate gate = new FactVerificationGate(List.of(citation), received::add);

        gate.asConsumer().accept(QueryEvent.chunk("{\"found\": false}\n"));
        gate.asConsumer().accept(QueryEvent.chunk("被丢弃的后续内容"));

        assertTrue(gate.refusedByFactVerification());
        assertEquals(1, received.size());
        assertEquals(QueryEventType.REFUSAL, received.get(0).type());
        assertEquals("未在当前知识库中检索到该问题的具体答案", received.get(0).message());
    }

    @Test
    void bufferExceeds200CharsWithoutNewlineFailsOpen() {
        List<QueryEvent> received = new ArrayList<>();
        FactVerificationGate gate = new FactVerificationGate(List.of(citation), received::add);

        String longContent = "a".repeat(250);
        gate.asConsumer().accept(QueryEvent.chunk(longContent));

        assertFalse(gate.refusedByFactVerification());
        assertEquals(QueryEventType.SOURCE, received.get(0).type());
        assertEquals(longContent, received.get(1).content());
    }

    @Test
    void invalidJsonOnFirstLineFailsOpen() {
        List<QueryEvent> received = new ArrayList<>();
        FactVerificationGate gate = new FactVerificationGate(List.of(citation), received::add);

        gate.asConsumer().accept(QueryEvent.chunk("这不是 JSON，是正常作答开头\n后续正文"));

        assertFalse(gate.refusedByFactVerification());
        assertEquals(QueryEventType.SOURCE, received.get(0).type());
        assertEquals("这不是 JSON，是正常作答开头\n后续正文", received.get(1).content());
    }

    @Test
    void missingFoundFieldFailsOpen() {
        List<QueryEvent> received = new ArrayList<>();
        FactVerificationGate gate = new FactVerificationGate(List.of(citation), received::add);

        gate.asConsumer().accept(QueryEvent.chunk("{\"other\": 1}\n正文"));

        assertFalse(gate.refusedByFactVerification());
        assertEquals(QueryEventType.SOURCE, received.get(0).type());
        assertEquals("{\"other\": 1}\n正文", received.get(1).content());
    }
}
