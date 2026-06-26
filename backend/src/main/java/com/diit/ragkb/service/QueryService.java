package com.diit.ragkb.service;

import com.diit.ragkb.dto.QueryChunkEvent;
import com.diit.ragkb.dto.QueryRequest;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.service.ragflow.RagFlowClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.UUID;

/**
 * 问答服务
 *
 * 核心流程(在 @Async 线程中执行):
 * 1. 租户校验(跨租户 → 404,Controller 同步阶段已完成)
 * 2. 懒建 Chat Assistant(首次问答时创建并持久化)
 * 3. 创建临时 Session
 * 4. 调 RAGFlow 流式 Completion,逐 chunk 推送到 SseEmitter
 * 5. 发送 done 事件
 * 6. finally 块中 fire-and-forget 删除 Session
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class QueryService {

    private final KnowledgeBaseRepository kbRepository;
    private final RagFlowClient ragFlowClient;

    /**
     * 流式问答(在 queryExecutor 线程池中执行)
     *
     * @param kbId    知识库 ID(已由 Controller 完成租户校验)
     * @param req     问答请求(question + topN)
     * @param emitter SseEmitter(推送给客户端)
     */
    @Async("queryExecutor")
    public void query(UUID kbId, QueryRequest req, SseEmitter emitter) {
        String sessionId = null;
        KnowledgeBase kb = null;
        try {
            // 1. 获取知识库(已校验租户,此处不再重复)
            kb = kbRepository.findById(kbId)
                    .orElseThrow(() -> new RuntimeException("知识库不存在"));

            // 2. 懒建 Chat Assistant
            String chatId = ensureChatAssistant(kb);

            // 3. 创建临时 Session
            sessionId = ragFlowClient.createSession(chatId);

            // 4. 流式 Completion
            ragFlowClient.streamCompletion(chatId, sessionId, req.getQuestion(), req.getTopN(), emitter);

            // 5. 发送 done 事件
            emitter.send(SseEmitter.event()
                    .name("done")
                    .data(QueryChunkEvent.done()));
            emitter.complete();

            log.info("问答完成,kbId={},question={}", kbId, req.getQuestion());

        } catch (Exception e) {
            log.error("问答失败,kbId={},question={}: {}", kbId, req.getQuestion(), e.getMessage());
            try {
                emitter.send(SseEmitter.event()
                        .name("error")
                        .data(QueryChunkEvent.error("问答失败: " + e.getMessage())));
                emitter.complete();
            } catch (IOException ex) {
                log.warn("发送 error 事件失败: {}", ex.getMessage());
                emitter.completeWithError(ex);
            }
        } finally {
            // 6. fire-and-forget 删除 Session(复用 try 块的 kb,避免重复查询)
            if (sessionId != null && kb != null && kb.getRagflowChatId() != null) {
                ragFlowClient.deleteSession(kb.getRagflowChatId(), sessionId);
            }
        }
    }

    /**
     * 懒建 Chat Assistant(synchronized + double-check)
     *
     * @param kb 知识库
     * @return chatId
     */
    private String ensureChatAssistant(KnowledgeBase kb) {
        if (kb.getRagflowChatId() != null) {
            return kb.getRagflowChatId();
        }

        synchronized (kb.getId().toString().intern()) {
            // double-check
            if (kb.getRagflowChatId() != null) {
                return kb.getRagflowChatId();
            }

            String chatId = ragFlowClient.createChat(kb.getId().toString(), kb.getRagflowDatasetId());
            kb.setRagflowChatId(chatId);
            kbRepository.save(kb);
            log.info("懒建 Chat Assistant 完成,kbId={},chatId={}", kb.getId(), chatId);
            return chatId;
        }
    }
}
