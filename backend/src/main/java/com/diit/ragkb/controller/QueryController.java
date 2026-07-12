package com.diit.ragkb.controller;

import com.diit.ragkb.config.RagQueryProperties;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.service.QueryService;
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

    @PostMapping(value = "/{kbId}/query", consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter query(@PathVariable UUID kbId, @Valid @RequestBody QueryRequest request) {
        QueryService.PreparedQuery prepared = queryService.prepare(kbId, request.getQuestion());
        SseEmitter emitter = new SseEmitter(properties.getStreamTimeoutMs());
        CompletableFuture.runAsync(() -> writeStream(emitter, prepared), ragQueryExecutor);
        return emitter;
    }

    private void writeStream(SseEmitter emitter, QueryService.PreparedQuery prepared) {
        try {
            queryService.stream(prepared, event -> send(emitter, event));
            send(emitter, QueryEvent.done());
            emitter.complete();
        } catch (Exception ex) {
            log.warn("知识库 SSE 问答失败: {}", ex.getMessage());
            try {
                send(emitter, QueryEvent.error("问答服务暂时不可用，请稍后重试"));
            } catch (RuntimeException ignored) {
                // 客户端已断开时无需再次尝试写入。
            }
            emitter.complete();
        }
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
