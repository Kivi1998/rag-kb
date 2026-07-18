package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.index.SearchRequest;
import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.List;

/** BM25/关键词候选端口；实现必须在存储查询中强制租户和知识库边界。 */
public interface LexicalCandidateSource {
    List<RetrievedChunk> search(SearchRequest request);
}
