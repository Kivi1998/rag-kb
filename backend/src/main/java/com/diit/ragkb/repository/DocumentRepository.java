package com.diit.ragkb.repository;

import com.diit.ragkb.model.Document;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface DocumentRepository extends JpaRepository<Document, UUID> {

    List<Document> findByKbIdAndOrgId(UUID kbId, UUID orgId);

    Optional<Document> findByIdAndKbIdAndOrgId(UUID id, UUID kbId, UUID orgId);
}
