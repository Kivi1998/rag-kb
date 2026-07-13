package com.diit.ragkb.repository;

import com.diit.ragkb.model.DocumentUploadSession;
import com.diit.ragkb.model.UploadSessionStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import jakarta.persistence.LockModeType;
import org.springframework.data.domain.Pageable;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface DocumentUploadSessionRepository extends JpaRepository<DocumentUploadSession, UUID> {

    Optional<DocumentUploadSession> findByIdAndOrgId(UUID id, UUID orgId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select session from DocumentUploadSession session where session.id = :id and session.org.id = :orgId")
    Optional<DocumentUploadSession> findForUpdate(@Param("id") UUID id, @Param("orgId") UUID orgId);

    Optional<DocumentUploadSession> findByOrgIdAndKnowledgeBaseIdAndIdempotencyKey(
            UUID orgId, UUID knowledgeBaseId, String idempotencyKey);

    @Query("select session.id as sessionId, session.org.id as orgId from DocumentUploadSession session " +
            "where session.status = :status and session.expiresAt < :now")
    List<ExpiredSessionRef> findExpiredSessionRefs(@Param("status") UploadSessionStatus status,
                                                   @Param("now") Instant now,
                                                   Pageable pageable);

    interface ExpiredSessionRef {
        UUID getSessionId();
        UUID getOrgId();
    }
}
