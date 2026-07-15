package com.diit.ragkb.service;

import com.diit.ragkb.config.RagMemoryProperties;
import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.ChatSession;
import com.diit.ragkb.model.ChatSessionStatus;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.ragcore.conversation.ConversationStore;
import com.diit.ragkb.repository.ChatSessionRepository;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.security.TenantContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** 会话创建、归属校验（跨组织/跨成员一律 404，不泄露会话是否存在）、状态机续期。 */
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
                memberRepository, mock(ConversationStore.class), new RagMemoryProperties());

        ChatSession created = service.createSession(kbId);

        assertEquals(ChatSessionStatus.ACTIVE, created.getStatus());
        verify(kbService, times(1)).getByIdAndCurrentOrg(kbId);
        verify(sessionRepository, times(1)).save(any(ChatSession.class));
    }

    @Test
    void touchSessionThrowsForForeignSession() {
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByIdAndOrgIdAndMemberId(sessionId, orgId, memberId)).thenReturn(Optional.empty());
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), mock(ConversationStore.class), new RagMemoryProperties());

        assertThrows(ResourceNotFoundException.class, () -> service.touchSession(sessionId));
    }

    @Test
    void touchSessionReactivatesIdleSession() {
        UUID orgId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, memberId, "MEMBER");
        ChatSession idleSession = new ChatSession();
        idleSession.setId(sessionId);
        idleSession.setStatus(ChatSessionStatus.IDLE);
        idleSession.setLastActiveAt(Instant.now().minus(1, ChronoUnit.HOURS));
        ChatSessionRepository sessionRepository = mock(ChatSessionRepository.class);
        when(sessionRepository.findByIdAndOrgIdAndMemberId(sessionId, orgId, memberId))
                .thenReturn(Optional.of(idleSession));
        when(sessionRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));
        ChatSessionService service = new ChatSessionService(sessionRepository, mock(KnowledgeBaseService.class),
                mock(OrganizationRepository.class), mock(KnowledgeBaseRepository.class),
                mock(MemberRepository.class), mock(ConversationStore.class), new RagMemoryProperties());

        ChatSession touched = service.touchSession(sessionId);

        assertEquals(ChatSessionStatus.ACTIVE, touched.getStatus());
    }
}
