package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.List;
import java.util.UUID;

/** 混合召回、融合和可选重排的编排端口。 */
public interface Retriever {

    List<RetrievedChunk> retrieve(UUID organizationId, UUID knowledgeBaseId, String query, RetrievalOptions options);
}
