"""意图分类训练数据留存:把「问题原文 + 预测意图标签」样本落库,供未来训练 BERT 分类器使用。
对应 Java 版 service/IntentTrainingSampleService.java。

只在意图分类成功产出合法标签时才有意义写入,调用方(对应 Java 版 QueryController,这里是
query 相关 router)负责判断。是否启用由 `settings.rag_intent_training_data_enabled` 门控,
门控逻辑由调用方(依赖注入装配处)负责,本类不感知开关。

Java 版用 `@Transactional(propagation = Propagation.REQUIRES_NEW)`,语义同
`QueryAuditService`——调用方应传入独立于请求生命周期的新 session。
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intent_training_sample import IntentTrainingSample
from app.repositories.intent_training_sample_repository import IntentTrainingSampleRepository

logger = logging.getLogger(__name__)


class IntentTrainingSampleService:
    def __init__(self, repository: IntentTrainingSampleRepository, session: AsyncSession) -> None:
        self._repository = repository
        self._session = session

    async def record_safely(
        self, org_id: UUID, kb_id: UUID, member_id: UUID, question: str, predicted_intent: str
    ) -> None:
        """落库失败不得影响问答主流程——这张表是数据积累,不是问答必需环节。"""
        try:
            await self.record(org_id, kb_id, member_id, question, predicted_intent)
        except Exception as exc:  # noqa: BLE001 - 训练样本落库失败只记日志
            logger.error("意图训练样本落库失败 orgId=%s errorType=%s", org_id, type(exc).__name__)

    async def record(
        self, org_id: UUID, kb_id: UUID, member_id: UUID, question: str, predicted_intent: str
    ) -> None:
        entity = IntentTrainingSample(
            org_id=org_id,
            kb_id=kb_id,
            member_id=member_id,
            question=question,
            predicted_intent=predicted_intent,
        )
        await self._repository.save(entity)
        await self._session.commit()
        # 不含问题原文——同 QueryAuditService 的落库日志一样,只记标识和标签方便排查。
        logger.info(
            "intent_training_sample orgId=%s kbId=%s memberId=%s predictedIntent=%s",
            org_id,
            kb_id,
            member_id,
            predicted_intent,
        )
