package com.diit.ragkb.ragcore.rerank;

import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.List;

/** 重排模型适配层，输入和输出均保留候选块以便审计。 */
public interface RerankerClient {

    List<RetrievedChunk> rerank(String query, List<RetrievedChunk> candidates, int topK);
}
