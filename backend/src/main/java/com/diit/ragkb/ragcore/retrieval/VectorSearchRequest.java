package com.diit.ragkb.ragcore.retrieval;

import java.util.List;
import java.util.UUID;

/**
 * 服务端生成 Embedding 后用于 ES kNN 召回的租户边界请求。
 *
 * <p>{@code documentIds} 非空时，索引实现应在租户过滤之外叠加范围过滤，只在指定文档内检索。</p>
 */
public record VectorSearchRequest(UUID organizationId, UUID knowledgeBaseId, List<Float> queryVector, int topK,
                                  List<UUID> documentIds) {
    public VectorSearchRequest {
        queryVector = queryVector == null ? List.of() : List.copyOf(queryVector);
        documentIds = documentIds == null ? List.of() : List.copyOf(documentIds);
        if (organizationId == null || knowledgeBaseId == null || queryVector.isEmpty() || topK <= 0) {
            throw new IllegalArgumentException("orgId、kbId、查询向量和 topK 均不能为空");
        }
    }

    public VectorSearchRequest(UUID organizationId, UUID knowledgeBaseId, List<Float> queryVector, int topK) {
        this(organizationId, knowledgeBaseId, queryVector, topK, List.of());
    }
}
