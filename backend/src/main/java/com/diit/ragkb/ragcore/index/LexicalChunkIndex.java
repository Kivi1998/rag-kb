package com.diit.ragkb.ragcore.index;

import com.diit.ragkb.ragcore.model.Chunk;

import java.util.List;
import java.util.UUID;

/** ES Chunk 词法投影的暂存、激活和隐藏端口。 */
public interface LexicalChunkIndex {

    void stage(List<Chunk> chunks, List<List<Float>> vectors, String embeddingModelVersion);

    void activateDocument(UUID organizationId, UUID knowledgeBaseId, UUID documentId);

    void deactivateDocument(UUID organizationId, UUID knowledgeBaseId, UUID documentId);

    void deleteByDocumentId(UUID organizationId, UUID knowledgeBaseId, UUID documentId);
}
