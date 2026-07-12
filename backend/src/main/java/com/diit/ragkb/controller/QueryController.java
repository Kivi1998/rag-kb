package com.diit.ragkb.controller;

import com.diit.ragkb.config.RagQueryProperties;
import com.diit.ragkb.model.QueryAuditStatus;
import com.diit.ragkb.ragcore.audit.QueryAuditSnapshot;
import com.diit.ragkb.ragcore.generation.GenerationMetrics;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.security.TenantContext;
import com.diit.ragkb.service.QueryAuditService;
import com.diit.ragkb.service.QueryService;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.slf4j.MDC;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;

/** 知识库流式问答接口；事件 data 仅包含前端契约定义的业务字段。 */
@Slf4j
@RestController
@RequestMapping("/api/v1/knowledge-bases")
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "rag.query", name = "enabled", havingValue = "true")
public class QueryController {

    private final QueryService queryService;
    @Qualifier("ragQueryExecutor")
    private final ExecutorService ragQueryExecutor;
    private final RagQueryProperties properties;
    private final QueryAuditService queryAuditService;

    @PostMapping(value = "/{kbId}/query", consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter query(@PathVariable UUID kbId, @Valid @RequestBody QueryRequest request,
                            HttpServletResponse response) {
        String traceId = UUID.randomUUID().toString();
        response.setHeader("X-RAG-Trace-Id", traceId);
        QueryService.PreparedQuery prepared;
        try {
            prepared = queryService.prepare(kbId, request.getQuestion(), traceId);
        } catch (RuntimeException ex) {
            recordPreRetrievalFailure(traceId, kbId, ex);
            throw ex;
        }
        SseEmitter emitter = new SseEmitter(properties.getStreamTimeoutMs());
        CompletableFuture.runAsync(() -> writeStream(emitter, prepared), ragQueryExecutor);
        return emitter;
    }

    private void writeStream(SseEmitter emitter, QueryService.PreparedQuery prepared) {
        long generationStartedAt = System.nanoTime();
        try (MDC.MDCCloseable ignored = MDC.putCloseable("ragTraceId", prepared.audit().traceId())) {
            GenerationMetrics metrics = queryService.stream(prepared, event -> send(emitter, event));
            send(emitter, QueryEvent.done());
            emitter.complete();
            long generationLatencyMs = elapsedMs(generationStartedAt);
            queryAuditService.recordSafely(prepared.audit(), prepared.refusalReason() == null
                    ? QueryAuditStatus.COMPLETED : QueryAuditStatus.REFUSED, metrics, generationLatencyMs,
                    prepared.audit().retrievalLatencyMs() + generationLatencyMs, null);
        } catch (Exception ex) {
            QueryAuditStatus status = isClientDisconnected(ex) ? QueryAuditStatus.CANCELLED : QueryAuditStatus.FAILED;
            log.warn("知识库 SSE 问答失败 traceId={} status={} errorCode={}", prepared.audit().traceId(), status,
                    errorCode(ex));
            long generationLatencyMs = elapsedMs(generationStartedAt);
            queryAuditService.recordSafely(prepared.audit(), status, GenerationMetrics.none(), generationLatencyMs,
                    prepared.audit().retrievalLatencyMs() + generationLatencyMs, errorCode(ex));
            try {
                send(emitter, QueryEvent.error("问答服务暂时不可用，请稍后重试"));
            } catch (RuntimeException ignored) {
                // 客户端已断开时无需再次尝试写入。
            }
            emitter.complete();
        }
    }

    private long elapsedMs(long startedAtNanos) {
        return java.util.concurrent.TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAtNanos);
    }

    private void recordPreRetrievalFailure(String traceId, UUID knowledgeBaseId, RuntimeException exception) {
        UUID organizationId = TenantContext.getOrgId();
        UUID memberId = TenantContext.getMemberId();
        if (organizationId == null || memberId == null) {
            log.warn("RAG 查询在租户上下文建立前失败 traceId={} errorCode={}", traceId, errorCode(exception));
            return;
        }
        queryAuditService.recordSafely(QueryAuditSnapshot.beforeRetrieval(traceId, organizationId, knowledgeBaseId,
                memberId), QueryAuditStatus.FAILED, GenerationMetrics.none(), 0, 0, errorCode(exception));
    }

    private boolean isClientDisconnected(Throwable exception) {
        Throwable current = exception;
        while (current != null) {
            if (current instanceof IOException) return true;
            current = current.getCause();
        }
        return false;
    }

    private String errorCode(Throwable exception) {
        Throwable current = exception;
        while (current != null) {
            if (current instanceof ModelClientException) return "MODEL_UNAVAILABLE";
            if (current instanceof IOException) return "CLIENT_DISCONNECTED";
            current = current.getCause();
        }
        return "QUERY_INTERNAL_ERROR";
    }

    private void send(SseEmitter emitter, QueryEvent event) {
        try {
            emitter.send(SseEmitter.event().name(event.sseEventName()).data(payload(event), MediaType.APPLICATION_JSON));
        } catch (IOException ex) {
            throw new IllegalStateException("SSE 客户端连接已断开", ex);
        }
    }

    static Map<String, Object> payload(QueryEvent event) {
        return switch (event.type()) {
            case CHUNK -> Map.of("content", event.content());
            case SOURCE -> Map.of("citation", event.citation());
            case REFUSAL, ERROR -> Map.of("message", event.message());
            case DONE -> Map.of();
        };
    }

    @Data
    public static class QueryRequest {
        /** 空问题由 Retriever 走正常 refusal SSE，而不是 HTTP 400。 */
        @NotNull(message = "问题不能为空")
        private String question;
        /** 首期接口兼容前端历史字段；当前不参与 Prompt，避免扩张上下文和泄露旧轮次。 */
        private List<ChatTurn> history = List.of();
        /** 首期固定关闭 LLM Query Rewrite，防止类名、错误码、配置 key 被改写。 */
        private Boolean rewrite;
    }

    @Data
    public static class ChatTurn {
        private String role;
        private String content;
    }
}
