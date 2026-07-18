package com.diit.ragkb.controller;

import com.diit.ragkb.config.RagQueryProperties;
import com.diit.ragkb.model.QueryAuditStatus;
import com.diit.ragkb.ragcore.audit.QueryAuditSnapshot;
import com.diit.ragkb.ragcore.generation.GenerationMetrics;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.security.TenantContext;
import com.diit.ragkb.service.IntentTrainingSampleService;
import com.diit.ragkb.service.QueryAuditService;
import com.diit.ragkb.service.QueryService;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
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
    private final ObjectProvider<IntentTrainingSampleService> intentTrainingSampleProvider;

    @PostMapping(value = "/{kbId}/query", consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter query(@PathVariable UUID kbId, @Valid @RequestBody QueryRequest request,
                            HttpServletResponse response) {
        String traceId = UUID.randomUUID().toString();
        response.setHeader("X-RAG-Trace-Id", traceId);
        QueryService.PreparedQuery prepared;
        try {
            prepared = queryService.prepare(kbId, request.getSessionId(), request.getQuestion(), traceId);
        } catch (RuntimeException ex) {
            recordPreRetrievalFailure(traceId, kbId, ex);
            throw ex;
        }
        SseEmitter emitter = new SseEmitter(properties.getStreamTimeoutMs());
        CompletableFuture.runAsync(() -> writeStream(emitter, prepared), ragQueryExecutor);
        return emitter;
    }

    private void writeStream(SseEmitter emitter, QueryService.PreparedQuery prepared) {
        // 挂在 ragQueryExecutor 异步线程上执行，不占用 HTTP 请求线程；单独 try/catch，不能让训练
        // 样本落库失败被外层 catch 误判为本次生成失败（那会错误地给用户推一条"服务暂时不可用"）。
        try {
            recordIntentTrainingSample(prepared);
        } catch (RuntimeException ex) {
            log.warn("意图训练样本记录失败，不影响本次问答 traceId={}: {}", prepared.audit().traceId(), ex.getMessage());
        }
        long generationStartedAt = System.nanoTime();
        try (MDC.MDCCloseable ignored = MDC.putCloseable("ragTraceId", prepared.audit().traceId())) {
            GenerationMetrics metrics = queryService.stream(prepared, event -> send(emitter, event));
            send(emitter, QueryEvent.done());
            emitter.complete();
            long generationLatencyMs = elapsedMs(generationStartedAt);
            queryAuditService.recordSafely(prepared.audit(), resolveStatus(prepared, metrics), metrics,
                    generationLatencyMs, prepared.audit().retrievalLatencyMs() + generationLatencyMs, null);
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

    /**
     * 训练样本只关心"这句问题该分到哪类意图"，与本次查询最终是否被拒答/生成失败无关——
     * {@code predictedIntent} 在 {@code prepare()} 内部就已经固化，检索阶段随后拒答不影响
     * 这次分类本身的有效性，所以调用方在 {@code writeStream()} 里生成开始前就调用，不等生成
     * 完成。org/kb/member 取自 {@code audit()} 而非 {@code prepared} 顶层字段：拒答场景下
     * {@link QueryService.PreparedQuery#refused} 顶层的这几个字段是 null，只有 audit 快照
     * 始终带着真实的租户信息。{@code audit()} 在生产环境的 {@code prepare()} 返回值里从不为
     * null，这里仍做判空——纯防御性，避免测试用的裸构造 {@code PreparedQuery} 意外传进来时
     * 抛 NPE。
     */
    void recordIntentTrainingSample(QueryService.PreparedQuery prepared) {
        if (prepared.audit() == null) {
            return;
        }
        String predictedIntent = prepared.audit().predictedIntent();
        if (predictedIntent == null) {
            return;
        }
        IntentTrainingSampleService service = intentTrainingSampleProvider.getIfAvailable();
        if (service == null) {
            return;
        }
        service.recordSafely(prepared.audit().organizationId(), prepared.audit().knowledgeBaseId(),
                prepared.audit().memberId(), prepared.resolvedQuestion(), predictedIntent);
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

    /**
     * 审计状态判断需要同时看检索阶段拒答（{@code prepared.refusalReason()}）与生成阶段事实核验拒答
     * （{@code metrics.factVerificationRefusalReason()}）——后者发生在 {@code prepared} 固化之后，
     * 只看前者会把事实核验拒答误记为 COMPLETED。
     */
    static QueryAuditStatus resolveStatus(QueryService.PreparedQuery prepared, GenerationMetrics metrics) {
        boolean refused = prepared.refusalReason() != null || metrics.factVerificationRefusalReason() != null;
        return refused ? QueryAuditStatus.REFUSED : QueryAuditStatus.COMPLETED;
    }

    static Map<String, Object> payload(QueryEvent event) {
        return switch (event.type()) {
            case CHUNK -> Map.of("content", event.content());
            case SOURCE -> Map.of("citation", event.citation());
            case REFUSAL, ERROR, SELF_CHECK_WARNING -> Map.of("message", event.message());
            case DONE -> Map.of();
        };
    }

    @Data
    public static class QueryRequest {
        /** 空问题由 Retriever 走正常 refusal SSE，而不是 HTTP 400。 */
        @NotNull(message = "问题不能为空")
        private String question;
        /** 多轮对话会话标识，须由 {@code POST .../sessions} 预先创建；缺失或不属于当前成员 → 400/404。 */
        @NotNull(message = "sessionId 不能为空")
        private UUID sessionId;
    }
}
