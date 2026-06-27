package com.diit.ragkb.controller;

import com.diit.ragkb.dto.QueryChunkEvent;
import com.diit.ragkb.dto.QueryRequest;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.security.TenantContext;
import com.diit.ragkb.service.KnowledgeBaseService;
import com.diit.ragkb.service.QueryService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.UUID;
import java.util.concurrent.RejectedExecutionException;

/**
 * 问答控制器(需认证+租户上下文)
 *
 * POST /api/v1/knowledge-bases/{kbId}/query
 * Accept: text/event-stream
 *
 * 校验阶段(同步):参数校验 + 租户校验 → 失败直接返回 HTTP 错误码
 * 推流阶段(异步):创建 SseEmitter → 委托 QueryService → 立即返回 emitter
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/knowledge-bases/{kbId}")
@RequiredArgsConstructor
public class QueryController {

    private final KnowledgeBaseService knowledgeBaseService;
    private final QueryService queryService;

    /**
     * 流式问答
     *
     * @param kbId 知识库 ID
     * @param req  问答请求(question + topN)
     * @return SseEmitter(立即返回,后续推流在异步线程中执行)
     */
    @PostMapping(value = "/query", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter query(@PathVariable UUID kbId,
                            @Valid @RequestBody QueryRequest req) {
        // 同步阶段:租户校验(跨租户 → 404)
        KnowledgeBase kb = knowledgeBaseService.getByIdAndCurrentOrg(kbId);
        UUID orgId = TenantContext.getOrgId();

        // 创建 SseEmitter(超时 5 分钟,与流式 RestTemplate 超时对齐)
        SseEmitter emitter = new SseEmitter(300_000L);

        // 设置超时回调:完成 emitter 避免僵尸线程
        emitter.onTimeout(() -> {
            log.warn("SseEmitter 超时,kbId={}", kbId);
            emitter.complete();
        });

        // 设置完成回调:记录日志
        emitter.onCompletion(() ->
            log.debug("SseEmitter 完成,kbId={}", kbId)
        );

        // 委托异步服务,处理线程池满的情况
        try {
            queryService.query(kbId, orgId, req, emitter);
        } catch (RejectedExecutionException e) {
            log.warn("问答线程池已满,kbId={}", kbId);
            try {
                emitter.send(SseEmitter.event()
                        .name("error")
                        .data(QueryChunkEvent.error("服务繁忙，请稍后重试")));
                emitter.complete();
            } catch (Exception ex) {
                emitter.completeWithError(ex);
            }
        }

        return emitter;
    }
}
