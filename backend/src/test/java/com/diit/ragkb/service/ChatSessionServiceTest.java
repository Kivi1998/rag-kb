package com.diit.ragkb.service;

import com.diit.ragkb.config.RagMemoryProperties;
import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.ChatSession;
import com.diit.ragkb.model.ChatSessionStatus;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.ragcore.conversation.ChatMessage;
import com.diit.ragkb.ragcore.conversation.ConversationStore;
import com.diit.ragkb.repository.ChatSessionRepository;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.security.TenantContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** 会话创建、归属校验（跨组织/跨知识库/跨成员一律 404，不泄露会话是否存在）、状态机续期。 */
class ChatSessionServiceTest {

    @AfterEach
    void clearTenant() {
        TenantContext.clear();
    }

    @Test
    void createSessionValidatesKbOwnershipAndPersists() {
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        KnowledgeBaseService kbService = mock(KnowledgeBaseService.class);
        when(kbService.getByIdAndCurrentOrg(kbId)).thenReturn(new KnowledgeBase());
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));
        OrganizationRepository orgRepository = mock(OrganizationRepository.class);
        when(orgRepository.getReferenceById(orgId)).thenReturn(new Organization());
        KnowledgeBaseRepository kbRepository = mock(KnowledgeBaseRepository.class);
        when(kbRepository.getReferenceById(kbId)).thenReturn(new KnowledgeBase());
        MemberRepository memberRepository = mock(MemberRepository.class);
        when(memberRepository.getReferenceById(memberId)).thenReturn(new Member());
        ChatSessionService service = new ChatSessionService(sessionRepository, kbService, orgRepository, kbRepository,
                memberRepository, emptyConversationStoreProvider(), new RagMemoryProperties());

        ChatSession created = service.createSession(kbId);

        assertEquals(ChatSessionStatus.ACTIVE, created.getStatus());
        verify(kbService, times(1)).getByIdAndCurrentOrg(kbId);
        verify(sessionRepository, times(1)).save(any(ChatSession.class));
    }

    @Test
    void touchSessionThrowsForForeignSession() {
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, orgId, kbId, memberId))
                .thenReturn(Optional.empty());
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), emptyConversationStoreProvider(), new RagMemoryProperties());

        assertThrows(ResourceNotFoundException.class, () -> service.touchSession(kbId, sessionId));
    }

    @Test
    void touchSessionThrowsWhenSessionBelongsToDifferentKnowledgeBase() {
        // 回归测试：session 属于 kb-A，但请求方通过 kb-B 的 URL 路径访问，必须视为不存在。
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        UUID actualKbId = UUID.randomUUID();
        UUID foreignKbId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        // 真实 kbId 查询会命中，但 controller 传入的是别的 kbId，repository 层直接查不到。
        when(sessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, orgId, actualKbId, memberId))
                .thenReturn(Optional.of(new ChatSession()));
        when(sessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, orgId, foreignKbId, memberId))
                .thenReturn(Optional.empty());
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), emptyConversationStoreProvider(), new RagMemoryProperties());

        assertThrows(ResourceNotFoundException.class, () -> service.touchSession(foreignKbId, sessionId));
    }

    @Test
    void touchSessionReactivatesIdleSession() {
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        ChatSession idleSession = new ChatSession();
        idleSession.setId(sessionId);
        idleSession.setStatus(ChatSessionStatus.IDLE);
        idleSession.setLastActiveAt(Instant.now().minus(1, ChronoUnit.HOURS));
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, orgId, kbId, memberId))
                .thenReturn(Optional.of(idleSession));
        when(sessionRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), emptyConversationStoreProvider(), new RagMemoryProperties());

        ChatSession touched = service.touchSession(kbId, sessionId);

        assertEquals(ChatSessionStatus.ACTIVE, touched.getStatus());
    }

    @Test
    void getMessagesReturnsEmptyListWhenConversationStoreUnavailable() {
        // rag.memory.enabled=false 时 ConversationStore bean 不存在，历史消息应降级为空列表而非报错。
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        ChatSession session = new ChatSession();
        session.setId(sessionId);
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, orgId, kbId, memberId))
                .thenReturn(Optional.of(session));
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), emptyConversationStoreProvider(), new RagMemoryProperties());

        List<ChatMessage> messages = service.getMessages(kbId, sessionId);

        assertTrue(messages.isEmpty());
    }

    @Test
    void getMessagesDelegatesToConversationStoreWhenAvailable() {
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        ChatSession session = new ChatSession();
        session.setId(sessionId);
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, orgId, kbId, memberId))
                .thenReturn(Optional.of(session));
        ConversationStore conversationStore = mock(ConversationStore.class);
        List<ChatMessage> stored = List.of(ChatMessage.user("你好", Instant.now()));
        when(conversationStore.archivedMessages(orgId, memberId, sessionId)).thenReturn(stored);
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), providerOf(conversationStore), new RagMemoryProperties());

        List<ChatMessage> messages = service.getMessages(kbId, sessionId);

        assertEquals(stored, messages);
    }

    @SuppressWarnings("unchecked")
    private ObjectProvider<ConversationStore> emptyConversationStoreProvider() {
        ObjectProvider<ConversationStore> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(null);
        return provider;
    }

    @SuppressWarnings("unchecked")
    private ObjectProvider<ConversationStore> providerOf(ConversationStore store) {
        ObjectProvider<ConversationStore> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(store);
        return provider;
    }
}
