package com.diit.ragkb.repository;

import com.diit.ragkb.model.ChatSession;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

public interface ChatSessionRepository extends JpaRepository<ChatSession, UUID> {

    Optional<ChatSession> findByIdAndOrgIdAndKbIdAndMemberId(UUID id, UUID orgId, UUID kbId, UUID memberId);
}
