package com.diit.ragkb.repository;

import com.diit.ragkb.model.ChatSession;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ChatSessionRepository extends JpaRepository<ChatSession, UUID> {

    Optional<ChatSession> findByIdAndOrgIdAndKbIdAndMemberId(UUID id, UUID orgId, UUID kbId, UUID memberId);

    /** 只返回已有标题（即已发生过至少一轮问答）的会话，尚未使用过的空会话不出现在历史列表里。 */
    List<ChatSession> findByOrgIdAndKbIdAndMemberIdAndTitleIsNotNullOrderByLastActiveAtDesc(UUID orgId, UUID kbId,
            UUID memberId, Pageable pageable);
}
