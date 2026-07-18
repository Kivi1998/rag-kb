package com.diit.ragkb.ragcore.index;

import com.diit.ragkb.config.RagMilvusProperties;
import com.diit.ragkb.ragcore.model.Chunk;
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import io.milvus.v2.client.MilvusClientV2;
import io.milvus.v2.common.ConsistencyLevel;
import io.milvus.v2.service.vector.request.DeleteReq;
import io.milvus.v2.service.vector.request.QueryReq;
import io.milvus.v2.service.vector.request.UpsertReq;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Milvus 向量投影：先不可见暂存，再按租户文档边界激活。 */
public class MilvusVectorIndex implements VectorChunkIndex {

    static final String DOCUMENT_FILTER = MilvusCollectionManager.ORG_ID + " == {org_id} and "
            + MilvusCollectionManager.KB_ID + " == {kb_id} and "
            + MilvusCollectionManager.DOCUMENT_ID + " == {document_id}";

    private final MilvusClientV2 client;
    private final RagMilvusProperties properties;
    private final Gson gson = new Gson();

    public MilvusVectorIndex(MilvusClientV2 client, RagMilvusProperties properties) {
        this.client = client;
        this.properties = properties;
    }

    @Override
    public void stage(List<Chunk> chunks, List<List<Float>> vectors, String embeddingModelVersion,
                      String chunkVersion) {
        validateBatch(chunks, vectors, embeddingModelVersion, chunkVersion);
        if (chunks.isEmpty()) return;
        List<JsonObject> rows = new ArrayList<>(chunks.size());
        long indexedAt = Instant.now().toEpochMilli();
        for (int index = 0; index < chunks.size(); index++) {
            Chunk chunk = chunks.get(index);
            List<Float> vector = vectors.get(index);
            if (vector == null || vector.size() != properties.getVectorDimensions()) {
                throw new IllegalArgumentException("Milvus 向量维度必须为 " + properties.getVectorDimensions());
            }
            JsonObject row = new JsonObject();
            row.addProperty(MilvusCollectionManager.CHUNK_ID, chunk.id());
            row.add(MilvusCollectionManager.EMBEDDING, gson.toJsonTree(vector));
            row.addProperty(MilvusCollectionManager.ORG_ID, chunk.organizationId().toString());
            row.addProperty(MilvusCollectionManager.KB_ID, chunk.knowledgeBaseId().toString());
            row.addProperty(MilvusCollectionManager.DOCUMENT_ID, chunk.documentId().toString());
            row.addProperty(MilvusCollectionManager.EMBEDDING_MODEL, embeddingModelVersion);
            row.addProperty(MilvusCollectionManager.CHUNK_VERSION, chunkVersion);
            row.addProperty(MilvusCollectionManager.RETRIEVAL_READY, false);
            row.addProperty(MilvusCollectionManager.INDEXED_AT, indexedAt);
            rows.add(row);
        }
        try {
            client.upsert(UpsertReq.builder()
                    .databaseName(properties.getDatabaseName())
                    .collectionName(properties.getCollectionName())
                    .data(rows)
                    .build());
        } catch (RuntimeException exception) {
            throw new MilvusVectorException("Milvus 向量暂存失败", exception);
        }
    }

    @Override
    public void activateDocument(UUID organizationId, UUID knowledgeBaseId, UUID documentId) {
        setVisibility(organizationId, knowledgeBaseId, documentId, true);
    }

    @Override
    public void deactivateDocument(UUID organizationId, UUID knowledgeBaseId, UUID documentId) {
        setVisibility(organizationId, knowledgeBaseId, documentId, false);
    }

    @Override
    public void deleteByDocumentId(UUID organizationId, UUID knowledgeBaseId, UUID documentId) {
        Map<String, Object> values = documentBoundary(organizationId, knowledgeBaseId, documentId);
        try {
            client.delete(DeleteReq.builder()
                    .databaseName(properties.getDatabaseName())
                    .collectionName(properties.getCollectionName())
                    .filter(DOCUMENT_FILTER)
                    .filterTemplateValues(values)
                    .build());
        } catch (RuntimeException exception) {
            throw new MilvusVectorException("Milvus 文档向量删除失败", exception);
        }
    }

    private void setVisibility(UUID organizationId, UUID knowledgeBaseId, UUID documentId, boolean ready) {
        Map<String, Object> values = documentBoundary(organizationId, knowledgeBaseId, documentId);
        try {
            var response = client.query(QueryReq.builder()
                    .databaseName(properties.getDatabaseName())
                    .collectionName(properties.getCollectionName())
                    .filter(DOCUMENT_FILTER)
                    .filterTemplateValues(values)
                    .outputFields(List.of(MilvusCollectionManager.CHUNK_ID))
                    .limit(16_384)
                    .consistencyLevel(ConsistencyLevel.SESSION)
                    .build());
            List<JsonObject> updates = response.getQueryResults().stream()
                    .map(result -> result.getEntity().get(MilvusCollectionManager.CHUNK_ID))
                    .filter(id -> id != null)
                    .map(id -> visibilityRow(id.toString(), ready))
                    .toList();
            if (!updates.isEmpty()) {
                client.upsert(UpsertReq.builder()
                        .databaseName(properties.getDatabaseName())
                        .collectionName(properties.getCollectionName())
                        .partialUpdate(true)
                        .data(updates)
                        .build());
            }
        } catch (RuntimeException exception) {
            throw new MilvusVectorException(ready ? "Milvus 文档向量激活失败" : "Milvus 文档向量关闭可见性失败",
                    exception);
        }
    }

    private JsonObject visibilityRow(String chunkId, boolean ready) {
        JsonObject row = new JsonObject();
        row.addProperty(MilvusCollectionManager.CHUNK_ID, chunkId);
        row.addProperty(MilvusCollectionManager.RETRIEVAL_READY, ready);
        return row;
    }

    private Map<String, Object> documentBoundary(UUID organizationId, UUID knowledgeBaseId, UUID documentId) {
        if (organizationId == null || knowledgeBaseId == null || documentId == null) {
            throw new IllegalArgumentException("Milvus 文档操作必须包含 orgId、kbId、documentId");
        }
        return Map.of("org_id", organizationId.toString(), "kb_id", knowledgeBaseId.toString(),
                "document_id", documentId.toString());
    }

    private void validateBatch(List<Chunk> chunks, List<List<Float>> vectors,
                               String embeddingModelVersion, String chunkVersion) {
        if (chunks == null || vectors == null || chunks.size() != vectors.size()) {
            throw new IllegalArgumentException("Chunk 与向量必须按下标一一对应");
        }
        if ((embeddingModelVersion == null || embeddingModelVersion.isBlank())
                || (chunkVersion == null || chunkVersion.isBlank())) {
            throw new IllegalArgumentException("embeddingModelVersion 和 chunkVersion 不能为空");
        }
        for (Chunk chunk : chunks) {
            if (chunk == null || chunk.id() == null || chunk.id().isBlank()
                    || chunk.organizationId() == null || chunk.knowledgeBaseId() == null
                    || chunk.documentId() == null) {
                throw new IllegalArgumentException("Milvus Chunk 必须包含 ID 与完整租户边界");
            }
        }
    }
}
