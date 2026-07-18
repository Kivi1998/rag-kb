package com.diit.ragkb.ragcore.index;

import com.diit.ragkb.config.RagMilvusProperties;
import io.milvus.v2.client.MilvusClientV2;
import io.milvus.v2.common.DataType;
import io.milvus.v2.common.IndexParam;
import io.milvus.v2.service.collection.request.CreateCollectionReq;
import io.milvus.v2.service.collection.response.DescribeCollectionResp;
import io.milvus.v2.service.index.response.DescribeIndexResp;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class MilvusCollectionManagerTest {

    @Test
    void createsStrictSchemaAndHnswCosineIndexWhenCollectionIsMissing() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        when(client.hasCollection(any())).thenReturn(false);
        var manager = new MilvusCollectionManager(client, properties(1_024));

        manager.ensureReady();

        ArgumentCaptor<CreateCollectionReq> captor = ArgumentCaptor.forClass(CreateCollectionReq.class);
        verify(client).createCollection(captor.capture());
        CreateCollectionReq request = captor.getValue();
        assertFalse(request.getCollectionSchema().isEnableDynamicField());
        assertEquals(1_024, request.getCollectionSchema().getField(MilvusCollectionManager.EMBEDDING)
                .getDimension());
        assertEquals(DataType.VarChar, request.getCollectionSchema().getField(MilvusCollectionManager.CHUNK_ID)
                .getDataType());
        assertEquals(IndexParam.IndexType.HNSW, request.getIndexParams().get(0).getIndexType());
        assertEquals(IndexParam.MetricType.COSINE, request.getIndexParams().get(0).getMetricType());
        assertEquals(16, request.getIndexParams().get(0).getExtraParams().get("M"));
        verify(client).loadCollection(any());
    }

    @Test
    void acceptsCompatibleExistingCollectionAndLoadsIt() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        when(client.hasCollection(any())).thenReturn(true);
        when(client.describeCollection(any())).thenReturn(description(1_024));
        when(client.describeIndex(any())).thenReturn(indexDescription(IndexParam.MetricType.COSINE));

        new MilvusCollectionManager(client, properties(1_024)).ensureReady();

        verify(client, never()).createCollection(any());
        verify(client).loadCollection(any());
    }

    @Test
    void failsFastWithoutOverwritingIncompatibleDimensions() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        when(client.hasCollection(any())).thenReturn(true);
        when(client.describeCollection(any())).thenReturn(description(768));

        assertThrows(MilvusVectorException.class,
                () -> new MilvusCollectionManager(client, properties(1_024)).ensureReady());

        verify(client, never()).createCollection(any());
        verify(client, never()).loadCollection(any());
    }

    @Test
    void failsFastOnMetricMismatch() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        when(client.hasCollection(any())).thenReturn(true);
        when(client.describeCollection(any())).thenReturn(description(1_024));
        when(client.describeIndex(any())).thenReturn(indexDescription(IndexParam.MetricType.L2));

        assertThrows(MilvusVectorException.class,
                () -> new MilvusCollectionManager(client, properties(1_024)).ensureReady());

        verify(client, never()).createCollection(any());
    }

    private DescribeCollectionResp description(int dimensions) {
        List<CreateCollectionReq.FieldSchema> fields = List.of(
                varchar(MilvusCollectionManager.CHUNK_ID, true),
                CreateCollectionReq.FieldSchema.builder().name(MilvusCollectionManager.EMBEDDING)
                        .dataType(DataType.FloatVector).dimension(dimensions).build(),
                varchar(MilvusCollectionManager.ORG_ID, false),
                varchar(MilvusCollectionManager.KB_ID, false),
                varchar(MilvusCollectionManager.DOCUMENT_ID, false),
                varchar(MilvusCollectionManager.EMBEDDING_MODEL, false),
                varchar(MilvusCollectionManager.CHUNK_VERSION, false),
                CreateCollectionReq.FieldSchema.builder().name(MilvusCollectionManager.RETRIEVAL_READY)
                        .dataType(DataType.Bool).build(),
                CreateCollectionReq.FieldSchema.builder().name(MilvusCollectionManager.INDEXED_AT)
                        .dataType(DataType.Int64).build());
        var schema = CreateCollectionReq.CollectionSchema.builder()
                .enableDynamicField(false).fieldSchemaList(fields).build();
        return DescribeCollectionResp.builder()
                .primaryFieldName(MilvusCollectionManager.CHUNK_ID)
                .autoID(false).enableDynamicField(false).collectionSchema(schema).build();
    }

    private DescribeIndexResp indexDescription(IndexParam.MetricType metricType) {
        var index = DescribeIndexResp.IndexDesc.builder()
                .fieldName(MilvusCollectionManager.EMBEDDING)
                .indexName(MilvusCollectionManager.VECTOR_INDEX)
                .indexType(IndexParam.IndexType.HNSW)
                .metricType(metricType).build();
        return DescribeIndexResp.builder().indexDescriptions(List.of(index)).build();
    }

    private CreateCollectionReq.FieldSchema varchar(String name, boolean primary) {
        return CreateCollectionReq.FieldSchema.builder().name(name).dataType(DataType.VarChar)
                .maxLength(256).isPrimaryKey(primary).autoID(false).build();
    }

    private RagMilvusProperties properties(int dimensions) {
        RagMilvusProperties properties = new RagMilvusProperties();
        properties.setEnabled(true);
        properties.setUri("http://localhost:19530");
        properties.setVectorDimensions(dimensions);
        return properties;
    }
}
