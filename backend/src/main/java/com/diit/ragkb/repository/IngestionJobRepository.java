package com.diit.ragkb.repository;

import com.diit.ragkb.model.IngestionJob;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface IngestionJobRepository extends JpaRepository<IngestionJob, UUID> {

    Optional<IngestionJob> findFirstByDocumentIdOrderByCreatedAtDesc(UUID documentId);

    Optional<IngestionJob> findByIdAndKnowledgeBaseIdAndOrgId(UUID id, UUID knowledgeBaseId, UUID orgId);

    List<IngestionJob> findByStatusOrderByCreatedAtAsc(IngestionStatus status);

    void deleteByDocumentId(UUID documentId);
}
