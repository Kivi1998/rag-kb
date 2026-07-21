"""将无正文审计摘要持久化,同时输出同 traceId 的结构化日志。
对应 Java 版 service/QueryAuditService.java。

Java 版用 `@Transactional(propagation = Propagation.REQUIRES_NEW)`——审计落库必须在独立
事务里执行,不与调用方(通常是 SSE 流已经完成、原请求事务早已结束)共享事务边界。
Python 版对应做法:调用方(通常是 QueryController 对应的 router,在后台任务里)应传入一个
**新建的** `AsyncSession`(如 `async with SessionLocal() as session:`),不要复用请求依赖注入
拿到的、生命周期绑定在 HTTP 请求上的那个 session。
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import QueryAuditStatus
from app.models.query_audit_log import QueryAuditLog
from app.ragcore.audit.query_audit_snapshot import QueryAuditSnapshot
from app.ragcore.generation.metrics import GenerationMetrics
from app.repositories.query_audit_log_repository import QueryAuditLogRepository

logger = logging.getLogger(__name__)


class QueryAuditService:
    def __init__(self, repository: QueryAuditLogRepository, session: AsyncSession) -> None:
        self._repository = repository
        self._session = session

    async def record_safely(
        self,
        snapshot: QueryAuditSnapshot,
        status: QueryAuditStatus,
        metrics: GenerationMetrics | None,
        generation_latency_ms: int,
        total_latency_ms: int,
        error_code: str | None,
    ) -> None:
        """审计故障不得反向影响已开始的 SSE 响应。"""
        try:
            await self.record(snapshot, status, metrics, generation_latency_ms, total_latency_ms, error_code)
        except Exception as exc:  # noqa: BLE001 - 审计失败只记日志,不得向上传播
            logger.error(
                "RAG 查询审计落库失败 traceId=%s status=%s errorType=%s",
                snapshot.trace_id,
                status,
                type(exc).__name__,
            )

    async def record(
        self,
        snapshot: QueryAuditSnapshot,
        status: QueryAuditStatus,
        metrics: GenerationMetrics | None,
        generation_latency_ms: int,
        total_latency_ms: int,
        error_code: str | None,
    ) -> None:
        safe_metrics = metrics if metrics is not None else GenerationMetrics()
        entity = QueryAuditLog(
            trace_id=snapshot.trace_id,
            org_id=snapshot.organization_id,
            kb_id=snapshot.knowledge_base_id,
            member_id=snapshot.member_id,
            status=status.value,
            retrieval_latency_ms=snapshot.retrieval_latency_ms,
            generation_latency_ms=max(0, generation_latency_ms),
            total_latency_ms=max(0, total_latency_ms),
            chunk_ids_json=self._write_json(list(snapshot.chunk_ids)),
            document_ids_json=self._write_json([str(d) for d in snapshot.document_ids]),
            final_scores_json=self._write_json(list(snapshot.final_scores)),
            embedding_fallback=snapshot.diagnostics.embedding_fallback,
            rerank_fallback=snapshot.diagnostics.rerank_fallback,
            refusal_reason=snapshot.refusal_reason,
            predicted_intent=snapshot.predicted_intent,
            generation_model=safe_metrics.model,
            prompt_tokens=safe_metrics.prompt_tokens,
            completion_tokens=safe_metrics.completion_tokens,
            output_characters=safe_metrics.output_characters,
            error_code=error_code,
        )
        await self._repository.save(entity)
        await self._session.commit()
        logger.info(
            "rag_query_audit traceId=%s orgId=%s kbId=%s memberId=%s status=%s retrievalMs=%s "
            "generationMs=%s totalMs=%s chunks=%s documents=%s embeddingFallback=%s rerankFallback=%s "
            "model=%s promptTokens=%s completionTokens=%s outputCharacters=%s errorCode=%s",
            snapshot.trace_id,
            snapshot.organization_id,
            snapshot.knowledge_base_id,
            snapshot.member_id,
            status,
            snapshot.retrieval_latency_ms,
            generation_latency_ms,
            total_latency_ms,
            len(snapshot.chunk_ids),
            len(snapshot.document_ids),
            snapshot.diagnostics.embedding_fallback,
            snapshot.diagnostics.rerank_fallback,
            safe_metrics.model,
            safe_metrics.prompt_tokens,
            safe_metrics.completion_tokens,
            safe_metrics.output_characters,
            error_code,
        )

    def _write_json(self, value: object) -> str:
        return json.dumps(value, ensure_ascii=False)
