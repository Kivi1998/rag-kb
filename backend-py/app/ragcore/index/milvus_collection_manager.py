"""`rag_chunks_vector_v1` Collection 的生命周期管理:建表/建索引/加载。

对应 Java 版 `ragcore/index/MilvusCollectionManager.java`。创建或严格校验知识库向量
Collection,绝不覆盖不兼容的存量 Collection——发现字段、主键或索引配置不兼容时直接抛
`MilvusVectorException`,不做静默迁移或删表重建,避免在生产环境下悄悄丢失数据。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymilvus import DataType, MilvusClient  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.config import settings as default_settings
from app.ragcore.index.exceptions import MilvusVectorException

logger = logging.getLogger(__name__)


class MilvusCollectionManager:
    """`rag_chunks_vector_v1` Collection 的建表/校验/加载。对应 Java 版同名类。"""

    CHUNK_ID = "chunk_id"
    EMBEDDING = "embedding"
    ORG_ID = "org_id"
    KB_ID = "kb_id"
    DOCUMENT_ID = "document_id"
    EMBEDDING_MODEL = "embedding_model"
    CHUNK_VERSION = "chunk_version"
    RETRIEVAL_READY = "retrieval_ready"
    INDEXED_AT = "indexed_at"
    VECTOR_INDEX = "embedding_hnsw_idx"

    _VARCHAR_MAX_LENGTH: dict[str, int] = {
        CHUNK_ID: 256,
        ORG_ID: 64,
        KB_ID: 64,
        DOCUMENT_ID: 64,
        EMBEDDING_MODEL: 128,
        CHUNK_VERSION: 128,
    }

    def __init__(self, client: MilvusClient, cfg: Settings | None = None) -> None:
        self._client = client
        cfg = cfg or default_settings
        self._database_name = cfg.rag_milvus_database
        self._collection_name = cfg.rag_milvus_collection
        self._vector_dimensions = cfg.rag_milvus_vector_dimensions
        self._hnsw_m = cfg.rag_milvus_hnsw_m
        self._ef_construction = cfg.rag_milvus_ef_construction
        self._rpc_timeout_s = cfg.rag_milvus_rpc_timeout_ms / 1000

    async def ensure_ready(self) -> None:
        """幂等确保 Collection 存在、Schema/索引兼容并已加载。对应 Java 版 `ensureReady()`。

        pymilvus `MilvusClient` 是同步阻塞客户端,整段建表/校验/加载逻辑包一层
        `asyncio.to_thread`,避免在协程里直接跑阻塞网络调用卡住事件循环。
        """
        await asyncio.to_thread(self._ensure_ready_sync)

    # ---- 内部实现(同步,统一在 to_thread 里跑) --------------------------------

    def _ensure_ready_sync(self) -> None:
        try:
            has_collection = self._client.has_collection(
                collection_name=self._collection_name, timeout=self._rpc_timeout_s
            )
            if not has_collection:
                self._create_collection()
            else:
                self._validate_existing_collection()
            self._client.load_collection(
                collection_name=self._collection_name, timeout=self._rpc_timeout_s
            )
        except MilvusVectorException:
            raise
        except Exception as ex:  # noqa: BLE001 - 统一包装为可识别异常
            raise MilvusVectorException("Milvus Collection 初始化失败") from ex

    def _create_collection(self) -> None:
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            self.CHUNK_ID,
            DataType.VARCHAR,
            is_primary=True,
            auto_id=False,
            max_length=self._VARCHAR_MAX_LENGTH[self.CHUNK_ID],
        )
        schema.add_field(self.EMBEDDING, DataType.FLOAT_VECTOR, dim=self._vector_dimensions)
        schema.add_field(self.ORG_ID, DataType.VARCHAR, max_length=self._VARCHAR_MAX_LENGTH[self.ORG_ID])
        schema.add_field(self.KB_ID, DataType.VARCHAR, max_length=self._VARCHAR_MAX_LENGTH[self.KB_ID])
        schema.add_field(
            self.DOCUMENT_ID, DataType.VARCHAR, max_length=self._VARCHAR_MAX_LENGTH[self.DOCUMENT_ID]
        )
        schema.add_field(
            self.EMBEDDING_MODEL, DataType.VARCHAR, max_length=self._VARCHAR_MAX_LENGTH[self.EMBEDDING_MODEL]
        )
        schema.add_field(
            self.CHUNK_VERSION, DataType.VARCHAR, max_length=self._VARCHAR_MAX_LENGTH[self.CHUNK_VERSION]
        )
        schema.add_field(self.RETRIEVAL_READY, DataType.BOOL, default_value=False)
        schema.add_field(self.INDEXED_AT, DataType.INT64)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name=self.EMBEDDING,
            index_name=self.VECTOR_INDEX,
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": self._hnsw_m, "efConstruction": self._ef_construction},
        )
        try:
            self._client.create_collection(
                collection_name=self._collection_name,
                schema=schema,
                index_params=index_params,
                consistency_level="Session",
                timeout=self._rpc_timeout_s,
            )
        except Exception as ex:  # noqa: BLE001
            raise MilvusVectorException("创建 Milvus Collection 失败") from ex

    def _validate_existing_collection(self) -> None:
        try:
            description = self._client.describe_collection(
                collection_name=self._collection_name, timeout=self._rpc_timeout_s
            )
        except Exception as ex:  # noqa: BLE001
            raise MilvusVectorException("查询 Milvus Collection Schema 失败") from ex
        if not description or not description.get("fields"):
            raise MilvusVectorException("Milvus Collection 无法返回 Schema")

        fields: dict[str, dict[str, Any]] = {field["name"]: field for field in description["fields"]}
        primary = fields.get(self.CHUNK_ID)
        if (
            primary is None
            or not primary.get("is_primary")
            or primary.get("auto_id")
            or description.get("enable_dynamic_field")
        ):
            raise MilvusVectorException("Milvus Collection 主键或动态字段配置不兼容")

        self._require_field(fields, self.CHUNK_ID, DataType.VARCHAR)
        self._require_field(fields, self.EMBEDDING, DataType.FLOAT_VECTOR, self._vector_dimensions)
        self._require_field(fields, self.ORG_ID, DataType.VARCHAR)
        self._require_field(fields, self.KB_ID, DataType.VARCHAR)
        self._require_field(fields, self.DOCUMENT_ID, DataType.VARCHAR)
        self._require_field(fields, self.EMBEDDING_MODEL, DataType.VARCHAR)
        self._require_field(fields, self.CHUNK_VERSION, DataType.VARCHAR)
        self._require_field(fields, self.RETRIEVAL_READY, DataType.BOOL)
        self._require_field(fields, self.INDEXED_AT, DataType.INT64)

        try:
            index = self._client.describe_index(
                collection_name=self._collection_name,
                index_name=self.VECTOR_INDEX,
                timeout=self._rpc_timeout_s,
            )
        except Exception as ex:  # noqa: BLE001
            raise MilvusVectorException("查询 Milvus 向量索引失败") from ex
        index_type = str((index or {}).get("index_type", "")).upper()
        metric_type = str((index or {}).get("metric_type", "")).upper()
        if not index or index_type != "HNSW" or metric_type != "COSINE":
            raise MilvusVectorException("Milvus 向量索引必须为 HNSW + COSINE")

    def _require_field(
        self,
        fields: dict[str, dict[str, Any]],
        name: str,
        data_type: DataType,
        dimensions: int | None = None,
    ) -> None:
        field = fields.get(name)
        if field is None or field.get("type") != data_type:
            raise MilvusVectorException(f"Milvus Collection 字段不兼容: {name}")
        if dimensions is not None:
            actual_dim = (field.get("params") or {}).get("dim")
            if actual_dim is None or int(actual_dim) != dimensions:
                raise MilvusVectorException(f"Milvus Collection 字段不兼容: {name}")
