"""知识库流式问答接口;事件 data 仅包含前端契约定义的业务字段。
对应 Java 版 controller/QueryController.java。

装配入口:`_query_service` 把模型客户端、HybridRetriever、记忆子系统、临时文档存储
等所有 ragcore 依赖按 `settings.rag_*_enabled` 条件性串起来,未启用时整体传 None,
由 QueryService 自身的 None 容忍路径做优雅降级(fail-open),不在路由层兜底。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.tenant_context import get_tenant_context
from app.models.enums import QueryAuditStatus
from app.ragcore.audit.query_audit_snapshot import QueryAuditSnapshot
from app.ragcore.generation.metrics import GenerationMetrics
from app.ragcore.model import Citation, ModelClientException, QueryEvent, QueryEventType
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository
from app.repositories.query_audit_log_repository import QueryAuditLogRepository
from app.routers._factories import (
    build_answer_generator,
    build_hybrid_retriever,
    build_intent_classifier,
    build_quick_document_store,
    build_reranker_client,
)
from app.routers.chat_sessions import _chat_session_service
from app.routers.deps import get_session, require_tenant
from app.routers.knowledge_bases import _kb_service
from app.schemas.query import QueryRequest
from app.services.chat_session_service import ChatSessionService
from app.services.intent_training_sample_service import IntentTrainingSampleService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.query_audit_service import QueryAuditService
from app.services.query_service import PreparedQuery, QueryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["query"], dependencies=[Depends(require_tenant)])


def _memory_orchestrator():
    """记忆编排器,`rag_memory_enabled=false` 时返回 None。"""
    from app.routers._factories import _build_memory_orchestrator

    return _build_memory_orchestrator()


def _query_service(
    db: AsyncSession = Depends(get_session),
    kb_service: KnowledgeBaseService = Depends(_kb_service),
    chat_session_service: ChatSessionService = Depends(_chat_session_service),
) -> QueryService:
    return QueryService(
        retriever=build_hybrid_retriever(),
        answer_generator=build_answer_generator(),
        knowledge_base_service=kb_service,
        document_repository=KnowledgeDocumentRepository(db),
        chat_session_service=chat_session_service,
        memory_orchestrator=_memory_orchestrator(),
        reranker=build_reranker_client(),
        intent_classifier=build_intent_classifier(),
        quick_document_store=build_quick_document_store(),
    )


@router.post("/{kb_id}/query")
async def query(
    kb_id: UUID,
    req: QueryRequest,
    response: Response,
    service: QueryService = Depends(_query_service),
) -> StreamingResponse:
    trace_id = str(uuid.uuid4())
    response.headers["X-RAG-Trace-Id"] = trace_id

    ctx = get_tenant_context()
    try:
        prepared = await service.prepare(kb_id, req.session_id, req.question, trace_id)
    except Exception as exc:
        await _record_pre_retrieval_failure(trace_id, kb_id, ctx.org_id, ctx.member_id, exc)
        raise

    return StreamingResponse(_write_stream(service, prepared), media_type="text/event-stream")


async def _write_stream(service: QueryService, prepared: PreparedQuery) -> AsyncIterator[bytes]:
    try:
        await _record_intent_training_sample(prepared)
    except Exception as exc:  # noqa: BLE001 - 不影响本次问答
        logger.warning("意图训练样本记录失败，不影响本次问答 traceId=%s: %s", prepared.audit.trace_id, exc)

    generation_started_at = time.perf_counter()
    metrics = GenerationMetrics()
    try:
        async for event in service.stream(prepared, metrics):
            yield _format_sse(event)
        yield _format_sse(QueryEvent.done())
        generation_latency_ms = int((time.perf_counter() - generation_started_at) * 1000)
        await _record_audit(
            prepared,
            _resolve_status(prepared, metrics),
            metrics,
            generation_latency_ms,
            prepared.audit.retrieval_latency_ms + generation_latency_ms,
            None,
        )
    except Exception as exc:  # noqa: BLE001 - SSE 流内的失败必须转成 error 事件,不能抛给 ASGI 层
        status_ = QueryAuditStatus.CANCELLED if _is_client_disconnected(exc) else QueryAuditStatus.FAILED
        logger.warning(
            "知识库 SSE 问答失败 traceId=%s status=%s errorCode=%s", prepared.audit.trace_id, status_, _error_code(exc)
        )
        generation_latency_ms = int((time.perf_counter() - generation_started_at) * 1000)
        await _record_audit(
            prepared,
            status_,
            GenerationMetrics(),
            generation_latency_ms,
            prepared.audit.retrieval_latency_ms + generation_latency_ms,
            _error_code(exc),
        )
        yield _format_sse(QueryEvent.error("问答服务暂时不可用，请稍后重试"))


async def _record_intent_training_sample(prepared: PreparedQuery) -> None:
    """训练样本只关心"这句问题该分到哪类意图",与本次查询最终是否被拒答/生成失败无关。"""
    if prepared.audit is None:
        return
    predicted_intent = prepared.audit.predicted_intent
    if predicted_intent is None:
        return
    if not settings.rag_intent_training_data_enabled:
        return
    async with SessionLocal() as session:
        service = IntentTrainingSampleService(_intent_training_repository(session), session)
        await service.record_safely(
            prepared.audit.organization_id,
            prepared.audit.knowledge_base_id,
            prepared.audit.member_id,
            prepared.resolved_question,
            predicted_intent,
        )


async def _record_audit(
    prepared: PreparedQuery,
    status_: QueryAuditStatus,
    metrics: GenerationMetrics,
    generation_latency_ms: int,
    total_latency_ms: int,
    error_code: str | None,
) -> None:
    async with SessionLocal() as session:
        service = QueryAuditService(QueryAuditLogRepository(session), session)
        await service.record_safely(prepared.audit, status_, metrics, generation_latency_ms, total_latency_ms, error_code)


async def _record_pre_retrieval_failure(
    trace_id: str, kb_id: UUID, org_id: UUID | None, member_id: UUID | None, exc: Exception
) -> None:
    if org_id is None or member_id is None:
        logger.warning("RAG 查询在租户上下文建立前失败 traceId=%s errorCode=%s", trace_id, _error_code(exc))
        return
    async with SessionLocal() as session:
        service = QueryAuditService(QueryAuditLogRepository(session), session)
        snapshot = QueryAuditSnapshot.before_retrieval(trace_id, org_id, kb_id, member_id)
        await service.record_safely(snapshot, QueryAuditStatus.FAILED, GenerationMetrics(), 0, 0, _error_code(exc))


def _intent_training_repository(session: AsyncSession):
    from app.repositories.intent_training_sample_repository import IntentTrainingSampleRepository

    return IntentTrainingSampleRepository(session)


def _is_client_disconnected(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, (ConnectionError, OSError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _error_code(exc: BaseException) -> str:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ModelClientException):
            return "MODEL_UNAVAILABLE"
        if isinstance(current, (ConnectionError, OSError)):
            return "CLIENT_DISCONNECTED"
        current = current.__cause__ or current.__context__
    return "QUERY_INTERNAL_ERROR"


def _resolve_status(prepared: PreparedQuery, metrics: GenerationMetrics) -> QueryAuditStatus:
    """审计状态判断需要同时看检索阶段拒答与生成阶段事实核验拒答,后者发生在 prepared 固化之后。"""
    refused = prepared.refusal_reason is not None or metrics.fact_verification_refusal_reason is not None
    return QueryAuditStatus.REFUSED if refused else QueryAuditStatus.COMPLETED


def _format_sse(event: QueryEvent) -> bytes:
    payload = _event_payload(event)
    frame = f"event: {event.sse_event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    return frame.encode("utf-8")


def _event_payload(event: QueryEvent) -> dict:
    if event.type == QueryEventType.CHUNK:
        return {"content": event.content}
    if event.type == QueryEventType.SOURCE:
        return {"citation": _citation_payload(event.citation)}
    if event.type in (QueryEventType.REFUSAL, QueryEventType.ERROR, QueryEventType.SELF_CHECK_WARNING):
        return {"message": event.message}
    return {}


def _citation_payload(citation: Citation | None) -> dict | None:
    if citation is None:
        return None
    return {
        "documentId": str(citation.document_id) if citation.document_id else None,
        "documentName": citation.document_name,
        "headingPath": list(citation.heading_path),
        "snippet": citation.snippet,
        "pageNo": citation.page_no,
        "lineStart": citation.line_start,
        "lineEnd": citation.line_end,
        "score": citation.score,
    }
