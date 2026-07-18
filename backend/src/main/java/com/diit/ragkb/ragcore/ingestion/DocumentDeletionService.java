package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.model.KnowledgeDocument;
import com.diit.ragkb.ragcore.index.LexicalChunkIndex;
import com.diit.ragkb.ragcore.index.VectorChunkIndex;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import com.diit.ragkb.repository.IngestionJobRepository;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * 文档删除补偿：ES 先隐藏 → Milvus 删除 → ES 物理删除 → 对象与元数据清理。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentDeletionService {

    private static final List<IngestionStatus> ACTIVE_STATUSES = List.of(
            IngestionStatus.QUEUED, IngestionStatus.PARSING, IngestionStatus.CHUNKING,
            IngestionStatus.EMBEDDING, IngestionStatus.INDEXING, IngestionStatus.FAILED);

    private final KnowledgeDocumentRepository documentRepository;
    private final IngestionJobRepository jobRepository;
    private final ObjectStorage objectStorage;
    private final ObjectProvider<LexicalChunkIndex> lexicalIndexProvider;
    private final ObjectProvider<VectorChunkIndex> vectorIndexProvider;

    /** 先持久化删除意图，保证外部清理失败后仍可由补偿任务发现。 */
    @Transactional
    public void requestDeletion(UUID documentId) {
        KnowledgeDocument document = documentRepository.findById(documentId)
                .orElseThrow(() -> new IllegalArgumentException("文档不存在"));
        document.setStatus(IngestionStatus.DELETING);
        jobRepository.markDeletingByDocumentId(documentId, ACTIVE_STATUSES, IngestionStatus.DELETING, Instant.now());
    }

    /**
     * 幂等执行一次外部资源与元数据清理。
     *
     * @return true 表示已彻底删除；false 表示保留 DELETING 等待下一轮补偿。
     */
    @Transactional
    public boolean cleanup(UUID documentId) {
        KnowledgeDocument document = documentRepository.findById(documentId).orElse(null);
        if (document == null) {
            return true;
        }
        if (document.getStatus() != IngestionStatus.DELETING) {
            return false;
        }
        try {
            UUID orgId = document.getOrg().getId();
            UUID kbId = document.getKnowledgeBase().getId();
            LexicalChunkIndex lexicalIndex = lexicalIndexProvider.getIfAvailable();
            VectorChunkIndex vectorIndex = vectorIndexProvider.getIfAvailable();
            if (lexicalIndex != null) {
                // 先关闭正文权威源可见性；后续任一步失败也不会继续出现在问答引用中。
                lexicalIndex.deactivateDocument(orgId, kbId, document.getId());
            }
            if (vectorIndex != null) {
                vectorIndex.deleteByDocumentId(orgId, kbId, document.getId());
            }
            if (lexicalIndex != null) {
                lexicalIndex.deleteByDocumentId(orgId, kbId, document.getId());
            }
            if (document.getObjectStoragePath() != null && !document.getObjectStoragePath().isBlank()) {
                objectStorage.delete(document.getObjectStoragePath());
            }
            if (document.getParseArtifactPath() != null && !document.getParseArtifactPath().isBlank()) {
                objectStorage.delete(document.getParseArtifactPath());
            }
            jobRepository.deleteByDocumentId(document.getId());
            documentRepository.delete(document);
            return true;
        } catch (IOException | RuntimeException ex) {
            log.warn("文档删除补偿失败，documentId={}，将重试", documentId, ex);
            return false;
        }
    }

    @Transactional(readOnly = true)
    public List<UUID> pendingDeletionIds(int limit) {
        return documentRepository.findByStatusOrderByUpdatedAtAsc(IngestionStatus.DELETING).stream()
                .limit(limit)
                .map(KnowledgeDocument::getId)
                .toList();
    }
}
