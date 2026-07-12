package com.diit.ragkb.repository;

import com.diit.ragkb.model.IngestionJob;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.time.Instant;

public interface IngestionJobRepository extends JpaRepository<IngestionJob, UUID> {

    Optional<IngestionJob> findFirstByDocumentIdOrderByCreatedAtDesc(UUID documentId);

    Optional<IngestionJob> findByIdAndKnowledgeBaseIdAndOrgId(UUID id, UUID knowledgeBaseId, UUID orgId);

    List<IngestionJob> findByStatusOrderByCreatedAtAsc(IngestionStatus status);

    void deleteByDocumentId(UUID documentId);

    /**
     * 原子领取任务：避免多实例 Worker 同时处理一条 QUEUED 记录。
     * 返回 0 说明已被其他实例领取或状态已变化。
     */
    @Modifying
    @Query("""
            update IngestionJob job
               set job.status = :nextStatus,
                   job.attempt = job.attempt + 1,
                   job.startedAt = :now,
                   job.updatedAt = :now
             where job.id = :jobId
               and job.status = :expectedStatus
            """)
    int claimIfQueued(@Param("jobId") UUID jobId,
                      @Param("expectedStatus") IngestionStatus expectedStatus,
                      @Param("nextStatus") IngestionStatus nextStatus,
                      @Param("now") Instant now);

    /** 删除请求优先取消未完成任务，正在执行的 Pipeline 会在下一阶段迁移时停止。 */
    @Modifying
    @Query("""
            update IngestionJob job
               set job.status = :deletingStatus,
                   job.updatedAt = :now
             where job.document.id = :documentId
               and job.status in :activeStatuses
            """)
    int markDeletingByDocumentId(@Param("documentId") UUID documentId,
                                 @Param("activeStatuses") List<IngestionStatus> activeStatuses,
                                 @Param("deletingStatus") IngestionStatus deletingStatus,
                                 @Param("now") Instant now);
}
