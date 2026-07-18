package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.config.RagMilvusProperties;
import com.diit.ragkb.ragcore.index.MilvusCollectionManager;
import com.diit.ragkb.ragcore.index.MilvusVectorException;
import io.milvus.v2.client.MilvusClientV2;
import io.milvus.v2.common.ConsistencyLevel;
import io.milvus.v2.common.IndexParam;
import io.milvus.v2.service.vector.request.SearchReq;
import io.milvus.v2.service.vector.request.data.FloatVec;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Milvus HNSW 召回，只返回 Chunk ID、得分和名次。 */
public class MilvusVectorCandidateSource implements VectorCandidateSource {

    private final MilvusClientV2 client;
    private final RagMilvusProperties properties;

    public MilvusVectorCandidateSource(MilvusClientV2 client, RagMilvusProperties properties) {
        this.client = client;
        this.properties = properties;
    }

    @Override
    public List<VectorHit> search(VectorSearchRequest request) {
        if (request == null) throw new IllegalArgumentException("Milvus 向量查询不能为空");
        if (request.queryVector().size() != properties.getVectorDimensions()) {
            throw new IllegalArgumentException("Milvus 查询向量维度必须为 " + properties.getVectorDimensions());
        }
        Map<String, Object> values = new LinkedHashMap<>();
        values.put("org_id", request.organizationId().toString());
        values.put("kb_id", request.knowledgeBaseId().toString());
        String filter = MilvusCollectionManager.ORG_ID + " == {org_id} and "
                + MilvusCollectionManager.KB_ID + " == {kb_id} and "
                + MilvusCollectionManager.RETRIEVAL_READY + " == true";
        if (!request.documentIds().isEmpty()) {
            filter += " and " + MilvusCollectionManager.DOCUMENT_ID + " in {document_ids}";
            values.put("document_ids", request.documentIds().stream().map(Object::toString).toList());
        }
        SearchReq milvusRequest = SearchReq.builder()
                .databaseName(properties.getDatabaseName())
                .collectionName(properties.getCollectionName())
                .annsField(MilvusCollectionManager.EMBEDDING)
                .metricType(IndexParam.MetricType.COSINE)
                .topK(request.topK())
                .filter(filter)
                .filterTemplateValues(values)
                .outputFields(List.of(MilvusCollectionManager.CHUNK_ID))
                .data(List.of(new FloatVec(request.queryVector())))
                .searchParams(Map.of("ef", Math.max(properties.getSearchEf(), request.topK())))
                .consistencyLevel(ConsistencyLevel.SESSION)
                .build();
        try {
            var response = client.search(milvusRequest);
            if (response == null || response.getSearchResults() == null
                    || response.getSearchResults().isEmpty()) {
                return List.of();
            }
            List<VectorHit> hits = new ArrayList<>();
            int rank = 1;
            for (var result : response.getSearchResults().get(0)) {
                Object projectedId = result.getEntity() == null ? null
                        : result.getEntity().get(MilvusCollectionManager.CHUNK_ID);
                String id = projectedId == null ? null : projectedId.toString();
                if ((id == null || id.isBlank()) && result.getId() != null) {
                    id = result.getId().toString();
                }
                if (id == null || id.isBlank()) id = result.getPrimaryKey();
                if (id == null || id.isBlank() || result.getScore() == null) continue;
                hits.add(new VectorHit(id, rank++, result.getScore()));
            }
            return List.copyOf(hits);
        } catch (RuntimeException exception) {
            throw new MilvusVectorException("Milvus 向量检索失败", exception);
        }
    }
}
