package com.diit.ragkb.repository;

import com.diit.ragkb.model.KbStatus;
import com.diit.ragkb.model.KnowledgeBase;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface KnowledgeBaseRepository extends JpaRepository<KnowledgeBase, UUID> {

    List<KnowledgeBase> findByOrgId(UUID orgId);

    Optional<KnowledgeBase> findByIdAndOrgId(UUID id, UUID orgId);

    /** 对账:查询待清理的知识库 */
    List<KnowledgeBase> findByStatus(KbStatus status);
}
