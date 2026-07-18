package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.ragcore.index.LexicalChunkIndex;
import com.diit.ragkb.ragcore.index.VectorChunkIndex;
import com.diit.ragkb.ragcore.model.Chunk;

import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Chunk 双投影提交协议：ES 暂存 → Milvus 暂存 → Milvus 激活 → ES 最终激活。
 *
 * <p>任一步失败都不会提前暴露 ES 正文；相同确定性 Chunk ID 的重试使用 Upsert 收敛。</p>
 */
public class ChunkProjectionOrchestrator {

    private final LexicalChunkIndex lexicalIndex;
    private final Optional<VectorChunkIndex> vectorIndex;

    public ChunkProjectionOrchestrator(LexicalChunkIndex lexicalIndex, VectorChunkIndex vectorIndex) {
        this.lexicalIndex = Objects.requireNonNull(lexicalIndex, "lexicalIndex 不能为空");
        this.vectorIndex = Optional.ofNullable(vectorIndex);
    }

    public void project(List<Chunk> chunks, List<List<Float>> vectors, String embeddingModelVersion) {
        DocumentBoundary boundary = validate(chunks, vectors, embeddingModelVersion);
        lexicalIndex.stage(chunks, vectors, embeddingModelVersion);
        if (vectorIndex.isPresent()) {
            String chunkVersion = chunks.get(0).metadata().getOrDefault("chunkVersion", "v1");
            vectorIndex.get().stage(chunks, vectors, embeddingModelVersion, chunkVersion);
            vectorIndex.get().activateDocument(boundary.organizationId(), boundary.knowledgeBaseId(),
                    boundary.documentId());
        }
        // ES 是正文权威源，必须作为最后提交点；只有这一步完成，Pipeline 才能推进 READY。
        lexicalIndex.activateDocument(boundary.organizationId(), boundary.knowledgeBaseId(), boundary.documentId());
    }

    private DocumentBoundary validate(List<Chunk> chunks, List<List<Float>> vectors,
                                      String embeddingModelVersion) {
        if (chunks == null || chunks.isEmpty() || vectors == null || chunks.size() != vectors.size()) {
            throw new IllegalArgumentException("双投影要求非空且一一对应的 Chunk 与向量");
        }
        if (embeddingModelVersion == null || embeddingModelVersion.isBlank()) {
            throw new IllegalArgumentException("embeddingModelVersion 不能为空");
        }
        Chunk first = chunks.get(0);
        DocumentBoundary boundary = boundary(first);
        String chunkVersion = first.metadata().getOrDefault("chunkVersion", "v1");
        for (Chunk chunk : chunks) {
            if (!boundary.equals(boundary(chunk))) {
                throw new IllegalArgumentException("一次双投影批次只能包含同一租户、知识库和文档");
            }
            if (!chunkVersion.equals(chunk.metadata().getOrDefault("chunkVersion", "v1"))) {
                throw new IllegalArgumentException("一次双投影批次不能混用不同 chunkVersion");
            }
        }
        return boundary;
    }

    private DocumentBoundary boundary(Chunk chunk) {
        if (chunk == null || chunk.organizationId() == null || chunk.knowledgeBaseId() == null
                || chunk.documentId() == null || chunk.id() == null || chunk.id().isBlank()) {
            throw new IllegalArgumentException("Chunk 必须包含确定性 ID 与完整租户边界");
        }
        return new DocumentBoundary(chunk.organizationId(), chunk.knowledgeBaseId(), chunk.documentId());
    }

    private record DocumentBoundary(UUID organizationId, UUID knowledgeBaseId, UUID documentId) { }
}
