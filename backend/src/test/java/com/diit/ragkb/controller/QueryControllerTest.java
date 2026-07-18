package com.diit.ragkb.controller;

import com.diit.ragkb.config.RagQueryProperties;
import com.diit.ragkb.model.QueryAuditStatus;
import com.diit.ragkb.ragcore.audit.QueryAuditSnapshot;
import com.diit.ragkb.ragcore.generation.GenerationMetrics;
import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.retrieval.RetrievalDiagnostics;
import com.diit.ragkb.service.IntentTrainingSampleService;
import com.diit.ragkb.service.QueryAuditService;
import com.diit.ragkb.service.QueryService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

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

    @Test
    void recordsTrainingSampleWhenIntentClassifiedAndServiceAvailable() {
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        QueryService.PreparedQuery prepared = preparedQueryWithIntent(orgId, kbId, memberId, "precise-lookup");
        IntentTrainingSampleService service = mock(IntentTrainingSampleService.class);
        QueryController controller = controller(service);

        controller.recordIntentTrainingSample(prepared);

        verify(service).recordSafely(eq(orgId), eq(kbId), eq(memberId), eq("问题"), eq("precise-lookup"));
    }

    @Test
    void doesNotRecordWhenPredictedIntentIsNull() {
        QueryService.PreparedQuery prepared = preparedQueryWithIntent(UUID.randomUUID(), UUID.randomUUID(),
                UUID.randomUUID(), null);
        IntentTrainingSampleService service = mock(IntentTrainingSampleService.class);
        QueryController controller = controller(service);

        controller.recordIntentTrainingSample(prepared);

        verify(service, never()).recordSafely(any(), any(), any(), any(), any());
    }

    @Test
    void doesNotRecordWhenTrainingDataServiceUnavailable() {
        // rag.intent-training-data.enabled=false 时 ObjectProvider 取不到 bean，方法应安全返回。
        QueryService.PreparedQuery prepared = preparedQueryWithIntent(UUID.randomUUID(), UUID.randomUUID(),
                UUID.randomUUID(), "semantic");
        QueryController controller = controller(null);

        controller.recordIntentTrainingSample(prepared);
        // 无异常即通过：没有可用的 service 时应直接返回，不抛 NPE。
    }

    @SuppressWarnings("unchecked")
    private QueryController controller(IntentTrainingSampleService intentTrainingSampleService) {
        ObjectProvider<IntentTrainingSampleService> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(intentTrainingSampleService);
        return new QueryController(mock(QueryService.class), mock(java.util.concurrent.ExecutorService.class),
                mock(RagQueryProperties.class), mock(QueryAuditService.class), provider);
    }

    private QueryService.PreparedQuery preparedQueryWithIntent(UUID orgId, UUID kbId, UUID memberId,
                                                                String predictedIntent) {
        QueryAuditSnapshot audit = new QueryAuditSnapshot("trace-1", orgId, kbId, memberId, 10, List.of(), List.of(),
                List.of(), RetrievalDiagnostics.empty(), false, null, predictedIntent);
        return new QueryService.PreparedQuery("问题", "问题", null, orgId, kbId, memberId, UUID.randomUUID(),
                List.of(), List.of(), null, audit);
    }
}
