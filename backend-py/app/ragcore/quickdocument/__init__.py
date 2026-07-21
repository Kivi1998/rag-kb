"""会话内临时文档子包。对应 Java 版 `ragcore/quickdocument/`。

公共 API:
    QuickDocument: 值对象
    QuickDocumentStore: 端口 Protocol
    RedisQuickDocumentStore: Redis 实现(独立逻辑 DB 2,见 settings.rag_quick_document_redis_database)
    QuickDocumentService: 解析 + 额度校验 + 存取编排
    QuotaExceededException: 总额度池已满(继承 ValueError,复用 400 映射)
"""

from app.ragcore.quickdocument.quick_document import QuickDocument
from app.ragcore.quickdocument.quick_document_service import (
    DocumentInputLike,
    QuotaExceededException,
    QuickDocumentService,
)
from app.ragcore.quickdocument.quick_document_store import QuickDocumentStore
from app.ragcore.quickdocument.redis_quick_document_store import RedisQuickDocumentStore

__all__ = [
    "QuickDocument",
    "QuickDocumentStore",
    "RedisQuickDocumentStore",
    "QuickDocumentService",
    "QuotaExceededException",
    "DocumentInputLike",
]
