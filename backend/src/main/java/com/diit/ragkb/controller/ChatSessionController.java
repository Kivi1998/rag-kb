package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.model.ChatSession;
import com.diit.ragkb.ragcore.conversation.ChatMessage;
import com.diit.ragkb.service.ChatSessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 多轮对话会话管理（需认证+租户上下文）。会话生命周期与 {@code rag.memory.enabled} 无关，
 * 始终可用——{@code sessionId} 在 QueryRequest 上始终必填，关闭记忆子系统时消息历史降级为空。
 */
@RestController
@RequestMapping("/api/v1/knowledge-bases/{kbId}/sessions")
@RequiredArgsConstructor
public class ChatSessionController {

    private final ChatSessionService chatSessionService;

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<Map<String, UUID>> createSession(@PathVariable UUID kbId) {
        ChatSession session = chatSessionService.createSession(kbId);
        return ApiResponse.ok(Map.of("sessionId", session.getId()));
    }

    @GetMapping
    public ApiResponse<List<ChatSessionService.ChatSessionSummary>> listSessions(@PathVariable UUID kbId) {
        return ApiResponse.ok(chatSessionService.listSessions(kbId));
    }

    @GetMapping("/{sessionId}/messages")
    public ApiResponse<List<ChatMessage>> getMessages(@PathVariable UUID kbId, @PathVariable UUID sessionId) {
        return ApiResponse.ok(chatSessionService.getMessages(kbId, sessionId));
    }

    @DeleteMapping("/{sessionId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteSession(@PathVariable UUID kbId, @PathVariable UUID sessionId) {
        chatSessionService.deleteSession(kbId, sessionId);
    }
}
