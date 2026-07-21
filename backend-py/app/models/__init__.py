"""统一 eager import 所有 ORM model,确保 SQLAlchemy registry 在任何单文件 import 时就完整。

为什么需要这个:多个 model 文件的 `relationship("X")` 用 `TYPE_CHECKING` 包装的字符串式
目标类(只在静态类型检查可见,运行时不存在);SQLAlchemy 在首次 mapper configure 时才解析
字符串,届时 `Base.registry` 里缺类会抛 `InvalidRequestError: When initializing mapper
Mapper[...], expression 'X' failed to locate a name ('X')`。

修这个文件就能修干净整个包——任何 `import app.models.member` 之类的单独 import 都会先
跑这个 `__init__.py`,11 个 model 全部进 registry,字符串解析时全部能找到目标。

不要逐个文件把 `TYPE_CHECKING` 改成运行时 import:model 之间互相有外键引用,轻率改动容易
兜回循环导入,得不偿失。统一在一个地方管理顺序即可。

依赖图(每个 model 字符串式 relationship 引用了哪些其他 model 类):
  - organization:    (无)              根表,所有租户隔离子表回指这里
  - user:            (无)              本地表,无 relationship
  - team:            Organization
  - member:          Organization
  - knowledge_base:  Team, Member, Organization
  - knowledge_document:    KnowledgeBase, Member, Organization
  - ingestion_job:   KnowledgeDocument, KnowledgeBase, Organization
  - document_upload_session: KnowledgeBase, KnowledgeDocument, Member, Organization
  - chat_session:    KnowledgeBase, Member, Organization
  - query_audit_log: (无)              有 FK 列但无 relationship,不会触发字符串解析
  - intent_training_sample: (无)       同上
"""

# 顺序按上面依赖图拓扑序:每个被引用者先 import,引用者后 import
from app.models.organization import Organization  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.team import Team  # noqa: F401
from app.models.member import Member  # noqa: F401
from app.models.knowledge_base import KnowledgeBase  # noqa: F401
from app.models.knowledge_document import KnowledgeDocument  # noqa: F401
from app.models.ingestion_job import IngestionJob  # noqa: F401
from app.models.document_upload_session import DocumentUploadSession  # noqa: F401
from app.models.chat_session import ChatSession  # noqa: F401
from app.models.query_audit_log import QueryAuditLog  # noqa: F401
from app.models.intent_training_sample import IntentTrainingSample  # noqa: F401

__all__ = [
    "Organization",
    "User",
    "Team",
    "Member",
    "KnowledgeBase",
    "KnowledgeDocument",
    "IngestionJob",
    "DocumentUploadSession",
    "ChatSession",
    "QueryAuditLog",
    "IntentTrainingSample",
]
