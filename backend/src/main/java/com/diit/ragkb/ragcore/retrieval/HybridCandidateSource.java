package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.index.SearchRequest;
import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.List;

/** 两路候选召回端口；每个实现必须在底层查询中强制租户与知识库过滤。 */
public interface HybridCandidateSource {

    List<RetrievedChunk> searchBm25(SearchRequest request);

    List<RetrievedChunk> searchKnn(VectorSearchRequest request);
}
