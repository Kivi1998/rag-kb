"""对应 repository/QueryAuditLogRepository.java —— Java 版只继承 JpaRepository,没有任何
自定义查询方法,这里同样只提供 BaseRepository 的通用 CRUD。

未做租户过滤,继承自 Java 版原始行为:rag_query_audit 表虽有 org_id/kb_id 外键,但
QueryAuditLog.java 实体本身没有 @Filter(tenantFilter) 注解,repository 也没有任何按
org_id 过滤的方法 —— 写入/读取路径的租户校验(如有)在 service 层完成,不在这里。
"""

from app.models.query_audit_log import QueryAuditLog
from app.repositories.base import BaseRepository


class QueryAuditLogRepository(BaseRepository[QueryAuditLog]):
    model = QueryAuditLog
