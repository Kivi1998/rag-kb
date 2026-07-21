"""多轮对话记忆子系统: 短期记忆(滑动窗口+摘要压缩)+ 长期记忆(用户画像+读时衰减遗忘)+
指代消解。对应 Java 版 com.diit.ragkb.ragcore.conversation 包。

存储分工与 Java 版一致: Redis(独立逻辑 DB,见 `redis_client.py`)存滑动窗口热路径,
MongoDB(独立数据库,见 `mongo_client.py`)存长期存档/画像权威数据,Elasticsearch(复用
chunk 检索集群,见 `elasticsearch_memory_index.py`)存统一语义记忆索引 `rag_memory_v1`。

公共 API:
    端口:
        ConversationStore, ConversationSummarizer, CoreferenceResolver,
        MemoryExtractor, MemoryIndex, MemoryItemStore
    值对象:
        ChatMessage, ChatMessageDocument, ConversationWindow, MemoryContext,
        MemoryRecord, MemoryItemDocument, MemoryType, ScoredMemoryRecord
    核心实现:
        SlidingWindowAssembler, TokenEstimator, UserProfileInjector,
        ConversationMemoryOrchestrator,
        DeepSeekConversationSummarizer, DeepSeekCoreferenceResolver,
        DeepSeekMemoryExtractor
    存储实现:
        RedisMongoConversationStore, MemoryItemStoreImpl,
        ElasticsearchMemoryIndex, ChatMessageRepository, MemoryItemRepository,
        run_cleanup_loop
    配置 / 客户端:
        get_memory_redis, get_memory_mongo_client, get_memory_db

多租户三重过滤(必须由所有实现保留):
    1. 短期: Redis key 包含 sessionId 隔离;Redis 失败时 RedisMongoConversationStore
       fail-open 返回空列表,不阻断问答主流程。
    2. MongoDB 长期存档: `archived_messages` / `delete_session` 强制带
       `sessionId + organizationId + kbId + memberId` 四个字段(2026-07-15 漏洞修复,
       防止同组织同成员跨知识库读取/删除对话历史);回包后再次逐条比对。
    3. MongoDB 画像: `find_similar_existing` 与 `top_k_for_generation` 在 ES kNN
       候选 + 批量 MongoDB 读取后,逐条比对 organization_id / member_id。
"""

from app.ragcore.memory.chat_message import ChatMessage, ROLE_ASSISTANT, ROLE_USER, VALID_ROLES
from app.ragcore.memory.chat_message_document import ChatMessageDocument
from app.ragcore.memory.chat_message_repository import ChatMessageRepository
from app.ragcore.memory.conversation_memory_orchestrator import ConversationMemoryOrchestrator
from app.ragcore.memory.conversation_store import ConversationStore
from app.ragcore.memory.conversation_summarizer import ConversationSummarizer
from app.ragcore.memory.conversation_window import ConversationWindow
from app.ragcore.memory.coreference_resolver import CoreferenceResolver
from app.ragcore.memory.deepseek_conversation_summarizer import DeepSeekConversationSummarizer
from app.ragcore.memory.deepseek_coreference_resolver import DeepSeekCoreferenceResolver
from app.ragcore.memory.deepseek_memory_extractor import DeepSeekMemoryExtractor
from app.ragcore.memory.elasticsearch_memory_index import ElasticsearchMemoryIndex
from app.ragcore.memory.memory_cleanup_task import (
    CLEANUP_IMPORTANCE_THRESHOLD,
    DEFAULT_INTERVAL_SECONDS,
    run_cleanup_loop,
)
from app.ragcore.memory.memory_context import MemoryContext
from app.ragcore.memory.memory_extractor import MemoryExtractor
from app.ragcore.memory.memory_index import MemoryIndex, ScoredMemoryRecord
from app.ragcore.memory.memory_item_document import MemoryItemDocument
from app.ragcore.memory.memory_item_repository import MemoryItemRepository
from app.ragcore.memory.memory_item_store import MemoryItemStore
from app.ragcore.memory.memory_item_store_impl import (
    DEDUP_COSINE_SIMILARITY_THRESHOLD,
    MemoryItemStoreImpl,
)
from app.ragcore.memory.memory_record import MemoryRecord
from app.ragcore.memory.memory_type import MemoryType
from app.ragcore.memory.mongo_client import get_memory_db, get_memory_mongo_client
from app.ragcore.memory.redis_client import get_memory_redis, is_available as redis_is_available
from app.ragcore.memory.redis_mongo_conversation_store import (
    REDIS_KEY_TTL_SECONDS,
    REDIS_WINDOW_SIZE,
    RedisMongoConversationStore,
)
from app.ragcore.memory.sliding_window_assembler import SlidingWindowAssembler
from app.ragcore.memory.token_estimator import estimate as estimate_tokens, estimate as token_estimate
from app.ragcore.memory.user_profile_injector import (
    PROFILE_SYSTEM_HEADER,
    UserProfileInjector,
)

__all__ = [
    # 端口
    "ConversationStore",
    "ConversationSummarizer",
    "CoreferenceResolver",
    "MemoryExtractor",
    "MemoryIndex",
    "MemoryItemStore",
    # 值对象
    "ChatMessage",
    "ChatMessageDocument",
    "ConversationWindow",
    "MemoryContext",
    "MemoryRecord",
    "MemoryItemDocument",
    "MemoryType",
    "ScoredMemoryRecord",
    "ROLE_USER",
    "ROLE_ASSISTANT",
    "VALID_ROLES",
    # 核心实现
    "SlidingWindowAssembler",
    "UserProfileInjector",
    "ConversationMemoryOrchestrator",
    "DeepSeekConversationSummarizer",
    "DeepSeekCoreferenceResolver",
    "DeepSeekMemoryExtractor",
    "PROFILE_SYSTEM_HEADER",
    "estimate_tokens",
    "token_estimate",
    # 存储实现
    "RedisMongoConversationStore",
    "REDIS_WINDOW_SIZE",
    "REDIS_KEY_TTL_SECONDS",
    "MemoryItemStoreImpl",
    "DEDUP_COSINE_SIMILARITY_THRESHOLD",
    "ElasticsearchMemoryIndex",
    "ChatMessageRepository",
    "MemoryItemRepository",
    "run_cleanup_loop",
    "CLEANUP_IMPORTANCE_THRESHOLD",
    "DEFAULT_INTERVAL_SECONDS",
    # 配置 / 客户端
    "get_memory_redis",
    "redis_is_available",
    "get_memory_mongo_client",
    "get_memory_db",
]
