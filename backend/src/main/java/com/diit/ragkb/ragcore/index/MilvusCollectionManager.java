package com.diit.ragkb.ragcore.index;

import com.diit.ragkb.config.RagMilvusProperties;
import io.milvus.v2.client.MilvusClientV2;
import io.milvus.v2.common.ConsistencyLevel;
import io.milvus.v2.common.DataType;
import io.milvus.v2.common.IndexParam;
import io.milvus.v2.service.collection.request.CreateCollectionReq;
import io.milvus.v2.service.collection.request.DescribeCollectionReq;
import io.milvus.v2.service.collection.request.HasCollectionReq;
import io.milvus.v2.service.collection.request.LoadCollectionReq;
import io.milvus.v2.service.collection.response.DescribeCollectionResp;
import io.milvus.v2.service.index.request.DescribeIndexReq;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 创建或严格校验知识库向量 Collection，绝不覆盖不兼容的存量 Collection。 */
public class MilvusCollectionManager {

    public static final String CHUNK_ID = "chunk_id";
    public static final String EMBEDDING = "embedding";
    public static final String ORG_ID = "org_id";
    public static final String KB_ID = "kb_id";
    public static final String DOCUMENT_ID = "document_id";
    public static final String EMBEDDING_MODEL = "embedding_model";
    public static final String CHUNK_VERSION = "chunk_version";
    public static final String RETRIEVAL_READY = "retrieval_ready";
    public static final String INDEXED_AT = "indexed_at";
    public static final String VECTOR_INDEX = "embedding_hnsw_idx";

    private final MilvusClientV2 client;
    private final RagMilvusProperties properties;

    public MilvusCollectionManager(MilvusClientV2 client, RagMilvusProperties properties) {
        this.client = client;
        this.properties = properties;
    }

    public void ensureReady() {
        try {
            var hasRequest = HasCollectionReq.builder()
                    .databaseName(properties.getDatabaseName())
                    .collectionName(properties.getCollectionName())
                    .build();
            if (!Boolean.TRUE.equals(client.hasCollection(hasRequest))) {
                client.createCollection(createCollectionRequest());
            } else {
                validateExistingCollection();
            }
            client.loadCollection(LoadCollectionReq.builder()
                    .databaseName(properties.getDatabaseName())
                    .collectionName(properties.getCollectionName())
                    .sync(true)
                    .timeout((long) properties.getRpcTimeoutMs())
                    .build());
        } catch (MilvusVectorException exception) {
            throw exception;
        } catch (RuntimeException exception) {
            throw new MilvusVectorException("Milvus Collection 初始化失败", exception);
        }
    }

    CreateCollectionReq createCollectionRequest() {
        var schema = CreateCollectionReq.CollectionSchema.builder()
                .enableDynamicField(false)
                .fieldSchemaList(List.of(
                        varchar(CHUNK_ID, 256, true),
                        CreateCollectionReq.FieldSchema.builder().name(EMBEDDING)
                                .dataType(DataType.FloatVector).dimension(properties.getVectorDimensions()).build(),
                        varchar(ORG_ID, 64, false),
                        varchar(KB_ID, 64, false),
                        varchar(DOCUMENT_ID, 64, false),
                        varchar(EMBEDDING_MODEL, 128, false),
                        varchar(CHUNK_VERSION, 128, false),
                        CreateCollectionReq.FieldSchema.builder().name(RETRIEVAL_READY)
                                .dataType(DataType.Bool).defaultValue(false).build(),
                        CreateCollectionReq.FieldSchema.builder().name(INDEXED_AT)
                                .dataType(DataType.Int64).build()
                ))
                .build();
        var index = IndexParam.builder()
                .fieldName(EMBEDDING)
                .indexName(VECTOR_INDEX)
                .indexType(IndexParam.IndexType.HNSW)
                .metricType(IndexParam.MetricType.COSINE)
                .extraParams(Map.of("M", properties.getHnswM(),
                        "efConstruction", properties.getEfConstruction()))
                .build();
        return CreateCollectionReq.builder()
                .databaseName(properties.getDatabaseName())
                .collectionName(properties.getCollectionName())
                .description("rag-kb knowledge chunk vector projection")
                .collectionSchema(schema)
                .indexParam(index)
                .consistencyLevel(ConsistencyLevel.SESSION)
                .build();
    }

    private void validateExistingCollection() {
        DescribeCollectionResp response = client.describeCollection(DescribeCollectionReq.builder()
                .databaseName(properties.getDatabaseName())
                .collectionName(properties.getCollectionName())
                .build());
        if (response == null || response.getCollectionSchema() == null) {
            throw new MilvusVectorException("Milvus Collection 无法返回 Schema");
        }
        if (!CHUNK_ID.equals(response.getPrimaryFieldName())
                || Boolean.TRUE.equals(response.getAutoID())
                || Boolean.TRUE.equals(response.getEnableDynamicField())) {
            throw new MilvusVectorException("Milvus Collection 主键或动态字段配置不兼容");
        }

        Map<String, CreateCollectionReq.FieldSchema> actual = new LinkedHashMap<>();
        for (var field : response.getCollectionSchema().getFieldSchemaList()) {
            actual.put(field.getName(), field);
        }
        requireField(actual, CHUNK_ID, DataType.VarChar, null);
        requireField(actual, EMBEDDING, DataType.FloatVector, properties.getVectorDimensions());
        requireField(actual, ORG_ID, DataType.VarChar, null);
        requireField(actual, KB_ID, DataType.VarChar, null);
        requireField(actual, DOCUMENT_ID, DataType.VarChar, null);
        requireField(actual, EMBEDDING_MODEL, DataType.VarChar, null);
        requireField(actual, CHUNK_VERSION, DataType.VarChar, null);
        requireField(actual, RETRIEVAL_READY, DataType.Bool, null);
        requireField(actual, INDEXED_AT, DataType.Int64, null);

        var indexResponse = client.describeIndex(DescribeIndexReq.builder()
                .databaseName(properties.getDatabaseName())
                .collectionName(properties.getCollectionName())
                .fieldName(EMBEDDING)
                .indexName(VECTOR_INDEX)
                .build());
        var index = indexResponse == null ? null : indexResponse.getIndexDescByFieldName(EMBEDDING);
        if (index == null || index.getIndexType() != IndexParam.IndexType.HNSW
                || index.getMetricType() != IndexParam.MetricType.COSINE) {
            throw new MilvusVectorException("Milvus 向量索引必须为 HNSW + COSINE");
        }
    }

    private void requireField(Map<String, CreateCollectionReq.FieldSchema> actual, String name,
                              DataType type, Integer dimensions) {
        var field = actual.get(name);
        if (field == null || field.getDataType() != type
                || (dimensions != null && !dimensions.equals(field.getDimension()))) {
            throw new MilvusVectorException("Milvus Collection 字段不兼容: " + name);
        }
    }

    private CreateCollectionReq.FieldSchema varchar(String name, int maxLength, boolean primary) {
        return CreateCollectionReq.FieldSchema.builder()
                .name(name).dataType(DataType.VarChar).maxLength(maxLength)
                .isPrimaryKey(primary).autoID(false).build();
    }
}
