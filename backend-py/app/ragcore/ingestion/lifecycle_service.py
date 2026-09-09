"""摄取任务状态机的入口抽象(Protocol)。

对应 Java 版 `ragcore/ingestion/IngestionJobLifecycleService.java`。
HTTP 层只能请求重试,后台 Worker 只能通过此类领取和推进任务;所有状态变化同时更新
ingestion_job 与 document,避免列表页与任务详情出现不一致。

Python 版先定义 Protocol,具体实现由持久层(SQLAlchemy + 现有 Flyway 迁移)落库。
本模块不依赖任何 ORM 库,以便后续接入 PostgreSQL 迁移时只补一个具体类。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Protocol, runtime_checkable

from app.ragcore.ingestion.status import IngestionStatus
from app.ragcore.ingestion.task import IngestionTask, JobSnapshot


@runtime_checkable
class IngestionJobLifecycleService(Protocol):
    """状态机入口;具体持久化由实现类(典型为 SQLAlchemy)负责。"""

    async def claim(
        self,
        job_id: object,
        worker_id: str | None = None,
        lease_duration: Optional[timedelta] = None,
    ) -> Optional[IngestionTask]:
        """使用条件更新原子领取排队任务;返回 None 表示已被其他 Worker 抢先领取。"""

    async def heartbeat(
        self, task: IngestionTask, lease_duration: timedelta
    ) -> bool:
        """活跃 Worker 定期续租;返回 False 表示任务已被删除、取消或接管。"""

    async def advance(
        self, target: "object | IngestionTask", next_status: IngestionStatus
    ) -> object:
        """Worker 在一个合法阶段完成后推进至下一阶段。
        支持两种调用形态: `advance(job_id, status)` 与 `advance(task, status)`(带 fencing)。"""

    async def fail(
        self, target: "object | IngestionTask", cause: BaseException
    ) -> object:
        """任意处理中阶段失败均进入 FAILED;已超最大尝试次数的任务即为死信状态。"""

    async def record_parsed_artifact(
        self,
        target: "object | IngestionTask",
        artifact_path: str,
        parser_name: str,
        parser_version: str,
    ) -> None:
        """解析成功后记录可复用产物,后续向量化/索引失败重试不重复 OCR。"""

    async def recover_expired_leases(self) -> int:
        """仅回收明确已过期的任务;超过最大尝试次数的任务转 FAILED,避免无限重试。"""

    async def retry(self, job_id: object) -> JobSnapshot:
        """管理员触发的失败任务重试;尝试次数由下一次原子领取时递增。"""
