package com.diit.ragkb.controller;

import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.QueryEvent;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;

class QueryControllerTest {

    @Test
    void payloadExactlyMatchesFrontendFiveEventContract() {
        Citation citation = new Citation(UUID.randomUUID(), "设计.md", List.of("API"), "片段", 1, 2, 3, 0.9);
        assertEquals(java.util.Map.of("content", "正文"), QueryController.payload(QueryEvent.chunk("正文")));
        assertEquals(java.util.Map.of("citation", citation), QueryController.payload(QueryEvent.source(citation)));
        assertEquals(java.util.Map.of("message", "资料不足"), QueryController.payload(QueryEvent.refusal("资料不足")));
        assertEquals(java.util.Map.of(), QueryController.payload(QueryEvent.done()));
        assertEquals(java.util.Map.of("message", "系统繁忙"), QueryController.payload(QueryEvent.error("系统繁忙")));
    }
}
