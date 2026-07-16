package com.diit.ragkb.repository;

import com.diit.ragkb.model.ChatSession;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ChatSessionRepository extends JpaRepository<ChatSession, UUID> {

    Optional<ChatSession> findByIdAndOrgIdAndKbIdAndMemberId(UUID id, UUID orgId, UUID kbId, UUID memberId);

    List<ChatSession> findByOrgIdAndKbIdAndMemberIdOrderByLastActiveAtDesc(UUID orgId, UUID kbId, UUID memberId,
            Pageable pageable);
}
