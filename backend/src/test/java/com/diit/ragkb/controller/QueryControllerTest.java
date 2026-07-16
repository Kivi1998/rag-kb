package com.diit.ragkb.controller;

import com.diit.ragkb.model.QueryAuditStatus;
import com.diit.ragkb.ragcore.generation.GenerationMetrics;
import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.service.QueryService;
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

    @Test
    void factVerificationRefusalIsAuditedAsRefusedNotCompleted() {
        QueryService.PreparedQuery prepared = preparedQuery(null);
        GenerationMetrics metrics = new GenerationMetrics("deepseek-chat", 100, 20, 40)
                .withFactVerificationRefusalReason("NO_RETRIEVAL");

        assertEquals(QueryAuditStatus.REFUSED, QueryController.resolveStatus(prepared, metrics));
    }

    @Test
    void retrievalRefusalIsAuditedAsRefused() {
        QueryService.PreparedQuery prepared = preparedQuery("未在当前知识库中检索到足够依据");

        assertEquals(QueryAuditStatus.REFUSED, QueryController.resolveStatus(prepared, GenerationMetrics.none()));
    }

    @Test
    void normalAnswerIsAuditedAsCompleted() {
        QueryService.PreparedQuery prepared = preparedQuery(null);
        GenerationMetrics metrics = new GenerationMetrics("deepseek-chat", 100, 20, 40);

        assertEquals(QueryAuditStatus.COMPLETED, QueryController.resolveStatus(prepared, metrics));
    }

    private QueryService.PreparedQuery preparedQuery(String refusalReason) {
        return new QueryService.PreparedQuery("问题", "问题", null, UUID.randomUUID(), UUID.randomUUID(),
                UUID.randomUUID(), UUID.randomUUID(), List.of(), List.of(), refusalReason, null);
    }
}
