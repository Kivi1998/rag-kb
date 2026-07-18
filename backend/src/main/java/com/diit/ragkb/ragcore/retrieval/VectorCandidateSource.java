package com.diit.ragkb.ragcore.retrieval;

import java.util.List;

/** 向量候选端口；只返回最小命中信息，正文必须通过受租户保护的 ChunkHydrator 补齐。 */
public interface VectorCandidateSource {
    List<VectorHit> search(VectorSearchRequest request);
}
