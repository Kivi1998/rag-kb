package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.ragcore.quickdocument.QuickDocument;
import com.diit.ragkb.ragcore.quickdocument.QuickDocumentService;
import com.diit.ragkb.service.ChatSessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;
import java.util.UUID;

/**
 * 会话内临时文档（长上下文直接塞入模式）：不写入知识库、不切块不索引，只在当前会话有效。
 * 上传接口同步阻塞——解析（含 OCR/ASR 网关降级）完成才返回，不走异步任务状态机。
 */
@RestController
@RequestMapping("/api/v1/knowledge-bases/{kbId}/sessions/{sessionId}/quick-documents")
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "rag.quick-document", name = "enabled", havingValue = "true")
public class QuickDocumentController {

    private final QuickDocumentService quickDocumentService;
    private final ChatSessionService chatSessionService;

    @PostMapping
    public ApiResponse<QuickDocumentSummary> upload(@PathVariable UUID kbId, @PathVariable UUID sessionId,
                                                     @RequestParam("file") MultipartFile file) {
        chatSessionService.touchSession(kbId, sessionId); // 校验归属，越权/不存在 → 404
        QuickDocument document;
        try {
            document = quickDocumentService.upload(sessionId, file);
        } catch (IOException ex) {
            throw new IllegalArgumentException("文档解析失败: " + ex.getMessage(), ex);
        }
        return ApiResponse.ok(toSummary(document));
    }

    @GetMapping
    public ApiResponse<List<QuickDocumentSummary>> list(@PathVariable UUID kbId, @PathVariable UUID sessionId) {
        // 只读校验归属，不像 touchSession 那样把只读请求悄悄续期成一次会话活跃——前端每次切换会话
        // 都会调这个接口，用 touchSession 会导致单纯查看历史会话就把它续期回 ACTIVE。
        chatSessionService.requireOwnedSession(kbId, sessionId);
        return ApiResponse.ok(quickDocumentService.list(sessionId).stream().map(this::toSummary).toList());
    }

    @DeleteMapping("/{docId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable UUID kbId, @PathVariable UUID sessionId, @PathVariable UUID docId) {
        chatSessionService.requireOwnedSession(kbId, sessionId);
        quickDocumentService.delete(sessionId, docId);
    }

    private QuickDocumentSummary toSummary(QuickDocument document) {
        return new QuickDocumentSummary(document.docId(), document.filename(), document.characterCount());
    }

    /** 不回传 content——前端只需要展示文件名/字符数，没必要把全文传回浏览器。 */
    public record QuickDocumentSummary(UUID docId, String filename, int characterCount) {
    }
}
