package com.diit.ragkb.service;

import com.diit.ragkb.config.RagMemoryProperties;
import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.ChatSession;
import com.diit.ragkb.model.ChatSessionStatus;
import com.diit.ragkb.ragcore.conversation.ChatMessage;
import com.diit.ragkb.ragcore.conversation.ConversationStore;
import com.diit.ragkb.repository.ChatSessionRepository;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.security.TenantContext;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * 会话生命周期管理：创建、归属校验（跨组织/跨成员一律 404，不泄露会话是否存在）、
 * 状态机流转（ACTIVE/IDLE/ARCHIVED，读时按 lastActiveAt 计算，不需要定时任务维护）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
public class ChatSessionService {

    private final ChatSessionRepository chatSessionRepository;
    private final KnowledgeBaseService knowledgeBaseService;
    private final OrganizationRepository organizationRepository;
    private final KnowledgeBaseRepository knowledgeBaseRepository;
    private final MemberRepository memberRepository;
    private final ConversationStore conversationStore;
    private final RagMemoryProperties properties;

    @Transactional
    public ChatSession createSession(UUID kbId) {
        knowledgeBaseService.getByIdAndCurrentOrg(kbId); // 校验 kb 属于当前组织，越权 → 404
        UUID organizationId = requireOrganizationId();
        UUID memberId = requireMemberId();

        ChatSession session = new ChatSession();
        session.setOrg(organizationRepository.getReferenceById(organizationId));
        session.setKb(knowledgeBaseRepository.getReferenceById(kbId));
        session.setMember(memberRepository.getReferenceById(memberId));
        session.setStatus(ChatSessionStatus.ACTIVE);
        return chatSessionRepository.save(session);
    }

    /** 校验归属并续期（有新消息时无论原状态如何都续期回 ACTIVE）。 */
    @Transactional
    public ChatSession touchSession(UUID sessionId) {
        ChatSession session = getOwnedSession(sessionId);
        session.setStatus(ChatSessionStatus.ACTIVE);
        session.setLastActiveAt(Instant.now());
        return chatSessionRepository.save(session);
    }

    @Transactional(readOnly = true)
    public List<ChatMessage> getMessages(UUID sessionId) {
        ChatSession session = getOwnedSession(sessionId);
        return conversationStore.archivedMessages(requireOrganizationId(), session.getId());
    }

    /** 只读地推断当前有效状态，不落库；落库的状态更新只在 {@link #touchSession} 时发生。 */
    public ChatSessionStatus effectiveStatus(ChatSession session) {
        Duration sinceLastActive = Duration.between(session.getLastActiveAt(), Instant.now());
        if (sinceLastActive.toMinutes() < properties.getSessionActiveMinutes()) {
            return ChatSessionStatus.ACTIVE;
        }
        if (sinceLastActive.toHours() < properties.getSessionIdleHours()) {
            return ChatSessionStatus.IDLE;
        }
        return ChatSessionStatus.ARCHIVED;
    }

    private ChatSession getOwnedSession(UUID sessionId) {
        return chatSessionRepository
                .findByIdAndOrgIdAndMemberId(sessionId, requireOrganizationId(), requireMemberId())
                .orElseThrow(() -> new ResourceNotFoundException("会话不存在"));
    }

    private UUID requireOrganizationId() {
        UUID organizationId = TenantContext.getOrgId();
        if (organizationId == null) throw new IllegalStateException("缺少租户上下文");
        return organizationId;
    }

    private UUID requireMemberId() {
        UUID memberId = TenantContext.getMemberId();
        if (memberId == null) throw new IllegalStateException("缺少成员上下文");
        return memberId;
    }
}
