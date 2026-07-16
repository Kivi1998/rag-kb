package com.diit.ragkb.service;

import com.diit.ragkb.config.RagMemoryProperties;
import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.ChatSession;
import com.diit.ragkb.model.ChatSessionStatus;
import com.diit.ragkb.ragcore.conversation.ChatMessage;
import com.diit.ragkb.ragcore.conversation.ConversationStore;
import com.diit.ragkb.ragcore.conversation.MemoryIndex;
import com.diit.ragkb.repository.ChatSessionRepository;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.security.TenantContext;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * 会话生命周期管理：创建、归属校验（跨组织/跨知识库/跨成员一律 404，不泄露会话是否存在）、
 * 状态机流转（ACTIVE/IDLE/ARCHIVED，读时按 lastActiveAt 计算，不需要定时任务维护）。
 *
 * <p>会话生命周期基于 Postgres {@code chat_session} 表，与 {@code rag.memory.enabled}
 * 门控的 Redis/MongoDB/ES 记忆子系统无关——{@code sessionId} 在 QueryRequest 上始终必填，
 * 因此本服务必须始终可用；只有 {@link #getMessages} 依赖的长期存档查询在记忆子系统关闭时
 * 才降级为空列表。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ChatSessionService {

    private final ChatSessionRepository chatSessionRepository;
    private final KnowledgeBaseService knowledgeBaseService;
    private final OrganizationRepository organizationRepository;
    private final KnowledgeBaseRepository knowledgeBaseRepository;
    private final MemberRepository memberRepository;
    private final ObjectProvider<ConversationStore> conversationStoreProvider;
    private final ObjectProvider<MemoryIndex> memoryIndexProvider;
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

    /** 校验归属（含 kbId）并续期（有新消息时无论原状态如何都续期回 ACTIVE）。 */
    @Transactional
    public ChatSession touchSession(UUID kbId, UUID sessionId) {
        ChatSession session = getOwnedSession(kbId, sessionId);
        session.setStatus(ChatSessionStatus.ACTIVE);
        session.setLastActiveAt(Instant.now());
        return chatSessionRepository.save(session);
    }

    @Transactional(readOnly = true)
    public List<ChatMessage> getMessages(UUID kbId, UUID sessionId) {
        ChatSession session = getOwnedSession(kbId, sessionId);
        ConversationStore conversationStore = conversationStoreProvider.getIfAvailable();
        if (conversationStore == null) {
            return List.of(); // rag.memory 关闭时长期存档未接入，退化为空历史而非报错
        }
        return conversationStore.archivedMessages(requireOrganizationId(), requireMemberId(), session.getId());
    }

    private static final int MAX_LISTED_SESSIONS = 50;

    /** 当前成员在该知识库下最近活跃的会话列表，固定最多 {@value #MAX_LISTED_SESSIONS} 条，按最后活跃时间倒序；不分状态展示。 */
    @Transactional(readOnly = true)
    public List<ChatSessionSummary> listSessions(UUID kbId) {
        UUID organizationId = requireOrganizationId();
        UUID memberId = requireMemberId();
        return chatSessionRepository
                .findByOrgIdAndKbIdAndMemberIdOrderByLastActiveAtDesc(organizationId, kbId, memberId,
                        Pageable.ofSize(MAX_LISTED_SESSIONS))
                .stream()
                .map(session -> new ChatSessionSummary(session.getId(), session.getTitle(), session.getLastActiveAt()))
                .toList();
    }

    public record ChatSessionSummary(UUID sessionId, String title, Instant lastActiveAt) {
    }

    /**
     * 硬删除：先校验归属（越权/不存在 → 404，不泄露存在性），再按"先删衍生索引/缓存，最后删权威记录"
     * 的顺序级联清理 Elasticsearch → MongoDB/Redis → Postgres；不影响该成员的 {@code memory_items}
     * 长期画像（画像是 member 维度，与会话生命周期无关）。{@code rag.memory.enabled=false} 时
     * {@link MemoryIndex}/{@link ConversationStore} 均取不到 bean，只删 Postgres 行。
     */
    @Transactional
    public void deleteSession(UUID kbId, UUID sessionId) {
        ChatSession session = getOwnedSession(kbId, sessionId);
        UUID organizationId = requireOrganizationId();
        UUID memberId = requireMemberId();

        MemoryIndex memoryIndex = memoryIndexProvider.getIfAvailable();
        if (memoryIndex != null) {
            memoryIndex.deleteBySession(organizationId, sessionId);
        }
        ConversationStore conversationStore = conversationStoreProvider.getIfAvailable();
        if (conversationStore != null) {
            conversationStore.deleteSession(organizationId, memberId, sessionId);
        }
        chatSessionRepository.delete(session);
    }

    /**
     * 首轮消息写入时截取前 30 字（按 code point 安全截断，不切分 surrogate pair）作为会话标题，
     * 只在标题当前为空时写入一次，非首轮不覆盖。运行在 SSE 线程（{@link com.diit.ragkb.service.QueryService#stream}），
     * 不读 {@link TenantContext}，租户信息全部来自参数——找不到会话（如同一时刻被并发删除）时静默跳过，不抛异常。
     */
    @Transactional
    public void maybeSetTitle(UUID organizationId, UUID kbId, UUID memberId, UUID sessionId, String content) {
        chatSessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, organizationId, kbId, memberId)
                .ifPresent(session -> {
                    if (session.getTitle() == null || session.getTitle().isBlank()) {
                        session.setTitle(truncateTitle(content));
                        chatSessionRepository.save(session);
                    }
                });
    }

    private static String truncateTitle(String content) {
        if (content == null) return null;
        String trimmed = content.strip();
        if (trimmed.isEmpty()) return null;
        StringBuilder builder = new StringBuilder();
        trimmed.codePoints().limit(30).forEach(builder::appendCodePoint);
        return builder.toString();
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

    private ChatSession getOwnedSession(UUID kbId, UUID sessionId) {
        return chatSessionRepository
                .findByIdAndOrgIdAndKbIdAndMemberId(sessionId, requireOrganizationId(), kbId, requireMemberId())
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
