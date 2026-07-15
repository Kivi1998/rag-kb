package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.model.ChatSession;
import com.diit.ragkb.ragcore.conversation.ChatMessage;
import com.diit.ragkb.service.ChatSessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/** 多轮对话会话管理（需认证+租户上下文）。 */
@RestController
@RequestMapping("/api/v1/knowledge-bases/{kbId}/sessions")
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
public class ChatSessionController {

    private final ChatSessionService chatSessionService;

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<Map<String, UUID>> createSession(@PathVariable UUID kbId) {
        ChatSession session = chatSessionService.createSession(kbId);
        return ApiResponse.ok(Map.of("sessionId", session.getId()));
    }

    @GetMapping("/{sessionId}/messages")
    public ApiResponse<List<ChatMessage>> getMessages(@PathVariable UUID kbId, @PathVariable UUID sessionId) {
        return ApiResponse.ok(chatSessionService.getMessages(sessionId));
    }
}
