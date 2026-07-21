"""应用配置。字段与环境变量名对齐 backend/src/main/resources/application.yml,
方便同一套 .env / Secret 在 Java、Python 两版服务间直接复用,迁移期间可以对照部署。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 服务
    server_port: int = 8090

    # 数据库
    db_url: str = "postgresql+asyncpg://ragkb:@localhost:5432/ragkb"
    db_username: str = "ragkb"
    db_password: str = ""
    db_pool_size: int = 20

    # 上传
    rag_upload_max_size_bytes: int = 536_870_912
    rag_direct_upload_ttl_seconds: int = 900
    rag_direct_upload_verification_timeout_ms: int = 900_000
    rag_direct_upload_cleanup_interval_ms: int = 60_000

    # 可观测性
    rag_metrics_token: str = ""

    # JWT
    jwt_secret: str = ""
    jwt_expiration_seconds: int = 86_400

    # Redis(JWT 黑名单,DB 0)
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_database: int = 0

    # 多模态解析(本地 deepdoc OCR + faster-whisper ASR 兜底;不再需要
    # endpoint/api-key/timeout 等 HTTP 网关相关配置,原网关客户端已下线)
    rag_multimodal_parser_enabled: bool = False

    # ASR(faster-whisper，从 parser-gateway 移植进 app.ragcore.parser.asr 的内置模块调用，
    # 环境变量名沿用 parser-gateway 里的 PARSER_WHISPER_* 语义)
    rag_whisper_model: str = "small"
    rag_whisper_device: str = "cpu"
    rag_whisper_compute_type: str = "int8"

    # 对象存储
    rag_storage_type: str = "local"
    rag_local_storage_root: str = "./data/rag-objects"
    minio_endpoint: str = ""
    minio_bucket: str = "rag-kb"
    minio_access_key: str = ""
    minio_secret_key: str = ""

    # 摄取 Worker
    rag_ingestion_worker_enabled: bool = False
    rag_ingestion_poll_interval_ms: int = 1_000
    rag_ingestion_worker_id: str = "rag-ingestion-local"
    rag_ingestion_worker_concurrency: int = 4
    rag_ingestion_worker_batch_size: int = 16
    rag_ingestion_worker_lease_duration_ms: int = 1_800_000
    rag_ingestion_cleanup_enabled: bool = True
    rag_ingestion_cleanup_poll_interval_ms: int = 30_000

    # Embedding
    rag_embedding_enabled: bool = False
    rag_embedding_endpoint: str = ""
    rag_embedding_api_key: str = ""
    rag_embedding_model: str = ""
    rag_embedding_batch_size: int = 32
    rag_embedding_timeout_ms: int = 15_000
    rag_embedding_max_attempts: int = 3
    rag_embedding_retry_backoff_ms: int = 200

    # Rerank
    rag_rerank_enabled: bool = False
    rag_rerank_endpoint: str = ""
    rag_rerank_api_key: str = ""
    rag_rerank_model: str = ""
    rag_rerank_timeout_ms: int = 15_000

    # 生成
    rag_generation_enabled: bool = False
    rag_generation_endpoint: str = ""
    rag_generation_api_key: str = ""
    rag_generation_model: str = ""
    rag_generation_timeout_ms: int = 60_000
    rag_generation_include_usage: bool = True

    # NLI 自检
    rag_nli_enabled: bool = False
    rag_nli_endpoint: str = ""
    rag_nli_timeout_ms: int = 15_000

    # 意图分类
    rag_intent_classification_enabled: bool = False
    rag_intent_training_data_enabled: bool = True

    # Elasticsearch
    rag_es_enabled: bool = False
    rag_es_endpoint: str = ""
    rag_es_api_key: str = ""
    rag_es_index_name: str = "rag_chunks_v1"
    rag_es_vector_dimensions: int = 0
    rag_es_connect_timeout_ms: int = 3_000
    rag_es_socket_timeout_ms: int = 30_000
    rag_es_visibility_backfill_enabled: bool = False
    rag_es_visibility_backfill_dry_run: bool = True
    rag_es_visibility_backfill_batch_size: int = 500
    rag_es_visibility_backfill_max_attempts: int = 3

    # 向量检索切流
    rag_vector_provider: str = "elasticsearch"  # elasticsearch | shadow | milvus
    rag_vector_fallback_to_es: bool = True
    rag_vector_shadow_timeout_ms: int = 1_500
    rag_vector_shadow_sample_rate: float = 1.0

    # Milvus
    rag_milvus_enabled: bool = False
    rag_milvus_uri: str = ""
    rag_milvus_auth_enabled: bool = False
    rag_milvus_token: str = ""
    rag_milvus_username: str = ""
    rag_milvus_password: str = ""
    rag_milvus_database: str = "default"
    rag_milvus_collection: str = "rag_chunks_vector_v1"
    rag_milvus_vector_dimensions: int = 1024
    rag_milvus_metric_type: str = "COSINE"
    rag_milvus_index_type: str = "HNSW"
    rag_milvus_hnsw_m: int = 16
    rag_milvus_ef_construction: int = 200
    rag_milvus_search_ef: int = 128
    rag_milvus_connect_timeout_ms: int = 3_000
    rag_milvus_rpc_timeout_ms: int = 3_000
    rag_milvus_tls_enabled: bool = False

    # 检索/问答总开关
    rag_retrieval_enabled: bool = False
    rag_query_enabled: bool = False
    rag_query_stream_timeout_ms: int = 120_000
    rag_query_worker_threads: int = 8

    # 会话记忆
    rag_memory_enabled: bool = False
    rag_memory_redis_database: int = 1
    rag_memory_mongo_uri: str = ""
    rag_memory_es_index_name: str = "rag_memory_v1"
    rag_memory_token_budget: int = 1_000
    rag_memory_decay_half_life_days: int = 30
    rag_memory_profile_top_k: int = 5
    rag_memory_session_active_minutes: int = 30
    rag_memory_session_idle_hours: int = 2

    # 临时文档问答
    rag_quick_document_enabled: bool = True
    rag_quick_document_redis_database: int = 2
    rag_quick_document_ttl_hours: int = 2
    rag_quick_document_max_total_characters: int = 15_000


settings = Settings()
