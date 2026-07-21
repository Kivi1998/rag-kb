"""`MilvusCollectionManager` 字段常量与 Schema 兼容性校验测试。

对照 Java 版 `ragcore/index/MilvusCollectionManager.java`。
Milvus 向量字段名 `EMBEDDING` 是跨模块单一权威来源——`milvus_vector_candidate_source.py`
和 `milvus_vector_index.py` 都从这里 import,不是本地硬编码;测试锁定这个契约以防
后续有人改字段名导致 HNSW 索引失效。
"""

from __future__ import annotations

import pytest
from pymilvus import DataType

from app.ragcore.index.exceptions import MilvusVectorException
from app.ragcore.index.milvus_collection_manager import MilvusCollectionManager


class TestFieldNameConstants:
    """Milvus 字段名是跨模块契约,改了就破坏 retrieval 链路。"""

    def test_chunk_id_is_chunk_id(self):
        assert MilvusCollectionManager.CHUNK_ID == "chunk_id"

    def test_embedding_field_name(self):
        """`EMBEDDING` 是 MilvusCollectionManager 类的唯一权威来源,
        其他模块(milvus_vector_candidate_source / milvus_vector_index)必须从这里 import。"""
        assert MilvusCollectionManager.EMBEDDING == "embedding"

    def test_org_id_field_name(self):
        assert MilvusCollectionManager.ORG_ID == "org_id"

    def test_kb_id_field_name(self):
        assert MilvusCollectionManager.KB_ID == "kb_id"

    def test_document_id_field_name(self):
        assert MilvusCollectionManager.DOCUMENT_ID == "document_id"

    def test_retrieval_ready_field_name(self):
        assert MilvusCollectionManager.RETRIEVAL_READY == "retrieval_ready"

    def test_vector_index_name(self):
        assert MilvusCollectionManager.VECTOR_INDEX == "embedding_hnsw_idx"


class TestValidateExistingCollection:
    """存量 Collection 校验:字段类型/主键/索引配置任意一项不兼容,直接抛错,
    绝不允许"静默迁移"或"删表重建"——生产环境下那会无声丢数据。"""

    def _make_client(self):
        client = type("_StubClient", (), {})()
        return client

    def _base_settings(self, **overrides):
        from app.core.config import Settings

        defaults = dict(
            rag_milvus_database="default",
            rag_milvus_collection="rag_chunks_vector_v1",
            rag_milvus_vector_dimensions=1024,
            rag_milvus_hnsw_m=16,
            rag_milvus_ef_construction=200,
            rag_milvus_rpc_timeout_ms=3000,
        )
        defaults.update(overrides)
        return Settings(**defaults)

    def _valid_description(self, **overrides):
        fields = [
            {"name": "chunk_id", "type": DataType.VARCHAR, "is_primary": True, "auto_id": False},
            {"name": "embedding", "type": DataType.FLOAT_VECTOR, "params": {"dim": 1024}},
            {"name": "org_id", "type": DataType.VARCHAR},
            {"name": "kb_id", "type": DataType.VARCHAR},
            {"name": "document_id", "type": DataType.VARCHAR},
            {"name": "embedding_model", "type": DataType.VARCHAR},
            {"name": "chunk_version", "type": DataType.VARCHAR},
            {"name": "retrieval_ready", "type": DataType.BOOL},
            {"name": "indexed_at", "type": DataType.INT64},
        ]
        desc = {"fields": fields, "enable_dynamic_field": False}
        desc.update(overrides)
        return desc

    def test_valid_collection_passes_validation(self):
        client = self._make_client()
        client.has_collection = lambda **kw: True
        client.describe_collection = lambda **kw: self._valid_description()
        client.describe_index = lambda **kw: {"index_type": "HNSW", "metric_type": "COSINE"}
        load_called = {"count": 0}
        client.load_collection = lambda **kw: load_called.__setitem__("count", load_called["count"] + 1)

        mgr = MilvusCollectionManager(client, cfg=self._base_settings())
        import asyncio
        asyncio.run(mgr.ensure_ready())
        # 走到这里说明 validate + load 都跑完
        assert load_called["count"] == 1

    def test_missing_chunk_id_field_rejected(self):
        client = self._make_client()
        client.has_collection = lambda **kw: True

        # 缺 chunk_id
        fields = [f for f in self._valid_description()["fields"] if f["name"] != "chunk_id"]
        client.describe_collection = lambda **kw: {"fields": fields, "enable_dynamic_field": False}
        client.describe_index = lambda **kw: {"index_type": "HNSW", "metric_type": "COSINE"}

        mgr = MilvusCollectionManager(client, cfg=self._base_settings())
        with pytest.raises(MilvusVectorException):
            import asyncio
            asyncio.run(mgr.ensure_ready())

    def test_primary_key_must_be_chunk_id(self):
        client = self._make_client()
        client.has_collection = lambda **kw: True
        fields = self._valid_description()["fields"]
        for f in fields:
            if f["name"] == "chunk_id":
                f["is_primary"] = False
        client.describe_collection = lambda **kw: {"fields": fields, "enable_dynamic_field": False}
        client.describe_index = lambda **kw: {"index_type": "HNSW", "metric_type": "COSINE"}

        mgr = MilvusCollectionManager(client, cfg=self._base_settings())
        with pytest.raises(MilvusVectorException):
            import asyncio
            asyncio.run(mgr.ensure_ready())

    def test_auto_id_must_be_false(self):
        """auto_id=True 会让客户端自己生成主键,失去 chunk_id ↔ 业务 ID 的稳定映射。"""
        client = self._make_client()
        client.has_collection = lambda **kw: True
        fields = self._valid_description()["fields"]
        for f in fields:
            if f["name"] == "chunk_id":
                f["auto_id"] = True
        client.describe_collection = lambda **kw: {"fields": fields, "enable_dynamic_field": False}
        client.describe_index = lambda **kw: {"index_type": "HNSW", "metric_type": "COSINE"}

        mgr = MilvusCollectionManager(client, cfg=self._base_settings())
        with pytest.raises(MilvusVectorException):
            import asyncio
            asyncio.run(mgr.ensure_ready())

    def test_enable_dynamic_field_must_be_false(self):
        """dynamic_field=True 会让任意字段都可被写入,破坏 schema 契约。"""
        client = self._make_client()
        client.has_collection = lambda **kw: True
        client.describe_collection = lambda **kw: self._valid_description(enable_dynamic_field=True)
        client.describe_index = lambda **kw: {"index_type": "HNSW", "metric_type": "COSINE"}

        mgr = MilvusCollectionManager(client, cfg=self._base_settings())
        with pytest.raises(MilvusVectorException):
            import asyncio
            asyncio.run(mgr.ensure_ready())

    def test_embedding_dim_mismatch_rejected(self):
        """embedding.dim 与配置不一致时直接抛错,不允许 HNSW 用错维度。"""
        client = self._make_client()
        client.has_collection = lambda **kw: True
        fields = self._valid_description()["fields"]
        for f in fields:
            if f["name"] == "embedding":
                f["params"] = {"dim": 768}  # 配置的是 1024
        client.describe_collection = lambda **kw: {"fields": fields, "enable_dynamic_field": False}
        client.describe_index = lambda **kw: {"index_type": "HNSW", "metric_type": "COSINE"}

        mgr = MilvusCollectionManager(client, cfg=self._base_settings())
        with pytest.raises(MilvusVectorException):
            import asyncio
            asyncio.run(mgr.ensure_ready())

    def test_non_hnsw_index_rejected(self):
        """HNSW 索引类型不能被改成 IVF/Flat,否则召回率会暴跌。"""
        client = self._make_client()
        client.has_collection = lambda **kw: True
        client.describe_collection = lambda **kw: self._valid_description()
        client.describe_index = lambda **kw: {"index_type": "IVF_FLAT", "metric_type": "COSINE"}

        mgr = MilvusCollectionManager(client, cfg=self._base_settings())
        with pytest.raises(MilvusVectorException):
            import asyncio
            asyncio.run(mgr.ensure_ready())

    def test_non_cosine_metric_rejected(self):
        client = self._make_client()
        client.has_collection = lambda **kw: True
        client.describe_collection = lambda **kw: self._valid_description()
        client.describe_index = lambda **kw: {"index_type": "HNSW", "metric_type": "L2"}

        mgr = MilvusCollectionManager(client, cfg=self._base_settings())
        with pytest.raises(MilvusVectorException):
            import asyncio
            asyncio.run(mgr.ensure_ready())

    def test_create_branch_when_no_existing_collection(self):
        """没有存量 collection 时走 create 路径,必须用 HNSW + COSINE。"""
        client = self._make_client()
        client.has_collection = lambda **kw: False
        create_called = {"called": False}
        # 模拟 create_schema / prepare_index_params 返回的 chainable 对象
        schema = type("_StubSchema", (), {"add_field": lambda *a, **kw: None})()
        index_params = type("_StubIndexParams", (), {"add_index": lambda *a, **kw: None})()
        client.create_schema = lambda **kw: schema
        client.prepare_index_params = lambda **kw: index_params
        client.create_collection = lambda **kw: create_called.__setitem__("called", True)
        client.load_collection = lambda **kw: None

        mgr = MilvusCollectionManager(client, cfg=self._base_settings())
        import asyncio
        asyncio.run(mgr.ensure_ready())
        assert create_called["called"] is True

    def test_load_collection_timeout_wrapped(self):
        """load_collection 抛任何异常都被包成 MilvusVectorException(同步阻塞路径,被 to_thread 包装)。"""
        client = self._make_client()
        client.has_collection = lambda **kw: True
        client.describe_collection = lambda **kw: self._valid_description()
        client.describe_index = lambda **kw: {"index_type": "HNSW", "metric_type": "COSINE"}
        client.load_collection = lambda **kw: (_ for _ in ()).throw(RuntimeError("RPC timeout"))

        mgr = MilvusCollectionManager(client, cfg=self._base_settings())
        import asyncio
        with pytest.raises(MilvusVectorException):
            asyncio.run(mgr.ensure_ready())
