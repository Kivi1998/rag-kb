package com.diit.ragkb.ragcore.retrieval;

import java.util.List;
import java.util.UUID;

/** 服务端生成 Embedding 后用于 ES kNN 召回的租户边界请求。 */
public record VectorSearchRequest(UUID organizationId, UUID knowledgeBaseId, List<Float> queryVector, int topK) {
    public VectorSearchRequest {
        queryVector = queryVector == null ? List.of() : List.copyOf(queryVector);
        if (organizationId == null || knowledgeBaseId == null || queryVector.isEmpty() || topK <= 0) {
            throw new IllegalArgumentException("orgId、kbId、查询向量和 topK 均不能为空");
        }
    }
}
