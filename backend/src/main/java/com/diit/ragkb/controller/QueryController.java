package com.diit.ragkb.controller;

import com.diit.ragkb.dto.QueryRequest;
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
        knowledgeBaseService.getByIdAndCurrentOrg(kbId);

        // 创建 SseEmitter(超时 3 分钟)
        SseEmitter emitter = new SseEmitter(180_000L);

        // 设置超时回调
        emitter.onTimeout(() ->
            log.warn("SseEmitter 超时,kbId={}", kbId)
        );

        // 委托异步服务
        queryService.query(kbId, req, emitter);

        return emitter;
    }
}
