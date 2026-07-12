package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.List;
import java.util.UUID;

/** 混合召回、融合和可选重排的编排端口。 */
public interface Retriever {

    List<RetrievedChunk> retrieve(UUID organizationId, UUID knowledgeBaseId, String query, RetrievalOptions options);

    /**
     * 返回检索结果及正常拒答原因；实现可覆盖以提供更精确的低置信度判断。
     */
    default RetrievalResult retrieveWithDecision(UUID organizationId, UUID knowledgeBaseId, String query,
                                                RetrievalOptions options) {
        List<RetrievedChunk> chunks = retrieve(organizationId, knowledgeBaseId, query, options);
        return chunks.isEmpty() ? RetrievalResult.refuse("未在当前知识库中检索到足够依据")
                : new RetrievalResult(chunks, null);
    }
}
