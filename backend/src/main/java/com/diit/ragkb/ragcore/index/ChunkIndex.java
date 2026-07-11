package com.diit.ragkb.ragcore.index;

import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.List;
import java.util.UUID;

/** 倒排索引与向量索引的统一端口。 */
public interface ChunkIndex {

    void upsert(List<Chunk> chunks, List<List<Float>> vectors, String embeddingModelVersion);

    void deleteByDocumentId(UUID organizationId, UUID knowledgeBaseId, UUID documentId);

    List<RetrievedChunk> search(SearchRequest request);
}
