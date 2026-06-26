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
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 问答服务
 *
 * 核心流程(在 @Async 线程中执行):
 * 1. 租户校验(异步线程中重新校验,不依赖 ThreadLocal)
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

    /** 锁注册表(替代 String.intern(),避免内存泄漏) */
    private final ConcurrentHashMap<UUID, Object> lockRegistry = new ConcurrentHashMap<>();

    /**
     * 流式问答(在 queryExecutor 线程池中执行)
     *
     * @param kbId    知识库 ID
     * @param orgId   组织 ID(显式传递,不依赖 ThreadLocal)
     * @param req     问答请求(question + topN)
     * @param emitter SseEmitter(推送给客户端)
     */
    @Async("queryExecutor")
    public void query(UUID kbId, UUID orgId, QueryRequest req, SseEmitter emitter) {
        String sessionId = null;
        KnowledgeBase kb = null;
        try {
            // 1. 异步线程中重新校验租户(不依赖 ThreadLocal)
            kb = kbRepository.findByIdAndOrgId(kbId, orgId)
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
                // 不泄露 RAGFlow 内部错误细节
                emitter.send(SseEmitter.event()
                        .name("error")
                        .data(QueryChunkEvent.error("服务内部错误，请稍后重试")));
                emitter.complete();
            } catch (IOException ex) {
                log.warn("发送 error 事件失败: {}", ex.getMessage());
                emitter.completeWithError(ex);
            }
        } finally {
            // 6. fire-and-forget 删除 Session
            if (sessionId != null && kb != null && kb.getRagflowChatId() != null) {
                ragFlowClient.deleteSession(kb.getRagflowChatId(), sessionId);
            }
        }
    }

    /**
     * 懒建 Chat Assistant(ConcurrentHashMap 锁 + double-check)
     *
     * @param kb 知识库
     * @return chatId
     */
    private String ensureChatAssistant(KnowledgeBase kb) {
        if (kb.getRagflowChatId() != null) {
            return kb.getRagflowChatId();
        }

        // 用 ConcurrentHashMap.computeIfAbsent 保证原子性,避免 String.intern() 内存泄漏
        Object lock = lockRegistry.computeIfAbsent(kb.getId(), k -> new Object());
        synchronized (lock) {
            // double-check:重新从 DB 加载,避免 stale 对象导致重复创建
            KnowledgeBase fresh = kbRepository.findById(kb.getId()).orElse(kb);
            if (fresh.getRagflowChatId() != null) {
                kb.setRagflowChatId(fresh.getRagflowChatId());
                return fresh.getRagflowChatId();
            }

            try {
                String chatId = ragFlowClient.createChat(kb.getId().toString(), kb.getRagflowDatasetId());
                kb.setRagflowChatId(chatId);
                kbRepository.save(kb);
                log.info("懒建 Chat Assistant 完成,kbId={},chatId={}", kb.getId(), chatId);
                return chatId;
            } finally {
                // 清理锁注册表(创建完成或失败后释放)
                lockRegistry.remove(kb.getId());
            }
        }
    }
}
