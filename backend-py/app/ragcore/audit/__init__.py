"""查询审计子包。对应 Java 版 `ragcore/audit/` 包。

本包只提供审计快照值对象;实际写入 `rag_query_audit` 表的落库逻辑由 query/audit
编排层处理,本子包不依赖任何持久化库。
"""

from app.ragcore.audit.query_audit_snapshot import QueryAuditSnapshot

__all__ = ["QueryAuditSnapshot"]
