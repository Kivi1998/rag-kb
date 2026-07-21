"""持久化枚举定义。

对应 Java 版 model 包下的各 enum(MemberRole/KbStatus/IngestionStatus/UploadSessionStatus/
ChatSessionStatus/QueryAuditStatus/UserStatus)。Java 端用 @Enumerated(EnumType.STRING) 存储,
Flyway 里对应列都是普通 VARCHAR(N),数据库层没有 native enum 类型 —— 这里统一用
`str, enum.Enum` 混入,SQLAlchemy 列类型用 native_enum=False,只做应用层校验,存储仍是字符串,
与 Java 行为一致。
"""

from enum import Enum


class MemberRole(str, Enum):
    """成员角色:owner > admin > member。对应 model/MemberRole.java。"""

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class KbStatus(str, Enum):
    """知识库状态。对应 model/KbStatus.java。"""

    ACTIVE = "ACTIVE"
    PENDING_CLEANUP = "PENDING_CLEANUP"


class IngestionStatus(str, Enum):
    """文档入库状态机。对应 ragcore/model/IngestionStatus.java。

    只允许按 QUEUED -> PARSING -> CHUNKING -> EMBEDDING -> INDEXING -> READY 顺序推进；
    任一处理中状态均可进入 FAILED,删除请求进入 DELETING。
    """

    QUEUED = "QUEUED"
    PARSING = "PARSING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"
    DELETING = "DELETING"


class UploadSessionStatus(str, Enum):
    """大文件直传会话状态。对应 model/UploadSessionStatus.java。"""

    PENDING = "PENDING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ChatSessionStatus(str, Enum):
    """会话生命周期状态。对应 model/ChatSessionStatus.java。

    ACTIVE(30分钟内有新消息) -> IDLE(超过30分钟未超2小时) -> ARCHIVED(超过2小时);
    有新消息时随时从 IDLE/ARCHIVED 续期回 ACTIVE。
    """

    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    ARCHIVED = "ARCHIVED"


class QueryAuditStatus(str, Enum):
    """问答审计最终状态。对应 model/QueryAuditStatus.java。"""

    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class UserStatus(str, Enum):
    """用户账号状态。对应 model/UserStatus.java。"""

    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
