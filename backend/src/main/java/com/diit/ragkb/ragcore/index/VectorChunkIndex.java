package com.diit.ragkb.ragcore.index;

import com.diit.ragkb.ragcore.model.Chunk;

import java.util.List;
import java.util.UUID;

/** 独立向量投影端口；正文和引用字段仍以 Elasticsearch 为权威来源。 */
public interface VectorChunkIndex {

    void stage(List<Chunk> chunks, List<List<Float>> vectors, String embeddingModelVersion,
               String chunkVersion);

    void activateDocument(UUID organizationId, UUID knowledgeBaseId, UUID documentId);

    void deactivateDocument(UUID organizationId, UUID knowledgeBaseId, UUID documentId);

    void deleteByDocumentId(UUID organizationId, UUID knowledgeBaseId, UUID documentId);
}
