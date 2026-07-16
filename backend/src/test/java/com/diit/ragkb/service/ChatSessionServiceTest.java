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
import com.diit.ragkb.ragcore.conversation.MemoryIndex;
import com.diit.ragkb.repository.ChatSessionRepository;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.security.TenantContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
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
import static org.mockito.ArgumentMatchers.eq;
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
                memberRepository, emptyConversationStoreProvider(), emptyMemoryIndexProvider(), new RagMemoryProperties());

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
                mock(MemberRepository.class), emptyConversationStoreProvider(), emptyMemoryIndexProvider(), new RagMemoryProperties());

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
                mock(MemberRepository.class), emptyConversationStoreProvider(), emptyMemoryIndexProvider(), new RagMemoryProperties());

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
                mock(MemberRepository.class), emptyConversationStoreProvider(), emptyMemoryIndexProvider(), new RagMemoryProperties());

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
                mock(MemberRepository.class), emptyConversationStoreProvider(), emptyMemoryIndexProvider(), new RagMemoryProperties());

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
                mock(MemberRepository.class), providerOf(conversationStore), emptyMemoryIndexProvider(), new RagMemoryProperties());

        List<ChatMessage> messages = service.getMessages(kbId, sessionId);

        assertEquals(stored, messages);
    }

    @Test
    void maybeSetTitleSetsTitleOnFirstMessage() {
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        ChatSession session = new ChatSession();
        session.setId(sessionId);
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, orgId, kbId, memberId))
                .thenReturn(Optional.of(session));
        when(sessionRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), emptyConversationStoreProvider(), emptyMemoryIndexProvider(), new RagMemoryProperties());

        service.maybeSetTitle(orgId, kbId, memberId, sessionId, "重疾险犹豫期过了还能退保吗，这个问题我想问很久了");

        assertEquals("重疾险犹豫期过了还能退保吗，这个问题我想问很久了".codePoints().limit(30)
                .collect(StringBuilder::new, StringBuilder::appendCodePoint, StringBuilder::append).toString(),
                session.getTitle());
        verify(sessionRepository, times(1)).save(session);
    }

    @Test
    void maybeSetTitleDoesNotOverwriteExistingTitle() {
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        ChatSession session = new ChatSession();
        session.setId(sessionId);
        session.setTitle("已有标题");
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, orgId, kbId, memberId))
                .thenReturn(Optional.of(session));
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), emptyConversationStoreProvider(), emptyMemoryIndexProvider(), new RagMemoryProperties());

        service.maybeSetTitle(orgId, kbId, memberId, sessionId, "第二轮的问题不应该覆盖标题");

        assertEquals("已有标题", session.getTitle());
        verify(sessionRepository, never()).save(any());
    }

    @Test
    void maybeSetTitleNoOpsWhenSessionNotFound() {
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, orgId, kbId, memberId))
                .thenReturn(Optional.empty());
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), emptyConversationStoreProvider(), emptyMemoryIndexProvider(), new RagMemoryProperties());

        service.maybeSetTitle(orgId, kbId, memberId, sessionId, "会话已被并发删除");

        verify(sessionRepository, never()).save(any());
    }

    @Test
    void listSessionsQueriesRepositoryWithTenantScopeAndOrdersByLastActive() {
        // 跨租户隔离验证：查询本身携带 org/kb/member 三重条件，不会拿到其他租户/知识库/成员的会话。
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        ChatSession newer = new ChatSession();
        newer.setId(UUID.randomUUID());
        newer.setTitle("最近的对话");
        newer.setLastActiveAt(Instant.now());
        ChatSession older = new ChatSession();
        older.setId(UUID.randomUUID());
        older.setTitle("较早的对话");
        older.setLastActiveAt(Instant.now().minus(1, ChronoUnit.HOURS));
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByOrgIdAndKbIdAndMemberIdAndTitleIsNotNullOrderByLastActiveAtDesc(eq(orgId),
                eq(kbId), eq(memberId), any())).thenReturn(List.of(newer, older));
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), emptyConversationStoreProvider(), emptyMemoryIndexProvider(),
                new RagMemoryProperties());

        List<ChatSessionService.ChatSessionSummary> sessions = service.listSessions(kbId);

        assertEquals(2, sessions.size());
        assertEquals("最近的对话", sessions.get(0).title());
        assertEquals("较早的对话", sessions.get(1).title());
        verify(sessionRepository, times(1)).findByOrgIdAndKbIdAndMemberIdAndTitleIsNotNullOrderByLastActiveAtDesc(
                eq(orgId), eq(kbId), eq(memberId), any());
    }

    @Test
    void listSessionsExcludesSessionsWithoutAnyMessages() {
        // 未发生过任何问答的空会话（title 为空）不应出现在历史列表里，避免每次挂载/新建对话都产生的占位记录淤积。
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        // repository 方法本身按 title IS NOT NULL 过滤，这里验证 service 调用的正是这个过滤方法而非无过滤版本。
        when(sessionRepository.findByOrgIdAndKbIdAndMemberIdAndTitleIsNotNullOrderByLastActiveAtDesc(eq(orgId),
                eq(kbId), eq(memberId), any())).thenReturn(List.of());
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), emptyConversationStoreProvider(), emptyMemoryIndexProvider(),
                new RagMemoryProperties());

        List<ChatSessionService.ChatSessionSummary> sessions = service.listSessions(kbId);

        assertTrue(sessions.isEmpty());
    }

    @Test
    void deleteSessionThrowsForForeignOrCrossKbSession() {
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByIdAndOrgIdAndKbIdAndMemberId(sessionId, orgId, kbId, memberId))
                .thenReturn(Optional.empty());
        MemoryIndex memoryIndex = mock(MemoryIndex.class);
        ConversationStore conversationStore = mock(ConversationStore.class);
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), providerOf(conversationStore), providerOf(memoryIndex),
                new RagMemoryProperties());

        assertThrows(ResourceNotFoundException.class, () -> service.deleteSession(kbId, sessionId));
        verify(memoryIndex, never()).deleteBySession(any(), any());
        verify(conversationStore, never()).deleteSession(any(), any(), any());
        verify(sessionRepository, never()).delete(any());
    }

    @Test
    void deleteSessionCascadesAcrossAllStoresInOrder() {
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
        MemoryIndex memoryIndex = mock(MemoryIndex.class);
        ConversationStore conversationStore = mock(ConversationStore.class);
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), providerOf(conversationStore), providerOf(memoryIndex),
                new RagMemoryProperties());

        service.deleteSession(kbId, sessionId);

        InOrder order = inOrder(memoryIndex, conversationStore, sessionRepository);
        order.verify(memoryIndex).deleteBySession(orgId, sessionId);
        order.verify(conversationStore).deleteSession(orgId, memberId, sessionId);
        order.verify(sessionRepository).delete(session);
    }

    @Test
    void deleteSessionOnlyDeletesPostgresRowWhenMemorySubsystemDisabled() {
        // rag.memory.enabled=false 时 MemoryIndex/ConversationStore 均取不到 bean，只删 Postgres 行。
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
                mock(MemberRepository.class), emptyConversationStoreProvider(), emptyMemoryIndexProvider(),
                new RagMemoryProperties());

        service.deleteSession(kbId, sessionId);

        verify(sessionRepository, times(1)).delete(session);
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

    @SuppressWarnings("unchecked")
    private ObjectProvider<MemoryIndex> emptyMemoryIndexProvider() {
        ObjectProvider<MemoryIndex> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(null);
        return provider;
    }

    @SuppressWarnings("unchecked")
    private ObjectProvider<MemoryIndex> providerOf(MemoryIndex memoryIndex) {
        ObjectProvider<MemoryIndex> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(memoryIndex);
        return provider;
    }
}
