package com.diit.ragkb.repository;

import com.diit.ragkb.model.KnowledgeDocument;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface KnowledgeDocumentRepository extends JpaRepository<KnowledgeDocument, UUID> {

    List<KnowledgeDocument> findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(UUID knowledgeBaseId, UUID orgId);

    Optional<KnowledgeDocument> findByIdAndKnowledgeBaseIdAndOrgId(UUID id, UUID knowledgeBaseId, UUID orgId);
}
