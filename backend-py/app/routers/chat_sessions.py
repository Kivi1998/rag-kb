"""多轮对话会话管理(需认证+租户上下文)。对应 Java 版 controller/ChatSessionController.java。

会话生命周期与 `rag_memory_enabled` 门控无关,始终可用;`sessionId` 在查询请求上始终必填,
关闭记忆子系统时消息历史降级为空。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.core.config import settings
from app.core.tenant_context import get_tenant_context
from app.repositories.chat_session_repository import ChatSessionRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.member_repository import MemberRepository
from app.repositories.organization_repository import OrganizationRepository
from app.ragcore.memory.conversation_store import ConversationStore
from app.ragcore.memory.memory_index import MemoryIndex
from app.routers.deps import get_session, require_tenant
from app.schemas.chat_session import ChatMessageOut, ChatSessionSummaryOut, CreateSessionResponse
from app.schemas.common import ApiResponse
from app.services.chat_session_service import ChatSessionService
from app.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter(
    prefix="/api/v1/knowledge-bases/{kb_id}/sessions",
    tags=["chat-sessions"],
    dependencies=[Depends(require_tenant)],
)


def _conversation_store() -> ConversationStore | None:
    """`rag_memory_enabled=false` 时返回 None,对应 Java 版
    `ObjectProvider<ConversationStore>.getIfAvailable()` 取不到 bean 的情形。
    """
    if not settings.rag_memory_enabled:
        return None
    from app.ragcore.memory.redis_mongo_conversation_store import RedisMongoConversationStore

    return RedisMongoConversationStore()


def _memory_index() -> MemoryIndex | None:
    """按 `settings.rag_es_enabled` 装配 `ElasticsearchMemoryIndex`;开关关闭时返回
    None,`ChatSessionService` 已经按"None = 不可用"做了优雅降级,不需要改调用方。

    客户端来自 `app.core.es_client.get_es_client()` 的模块级单例,与 chunk 索引等
    其他 ES 接入点共用同一连接池。
    """
    if not settings.rag_es_enabled:
        return None
    from app.core.es_client import get_es_client
    from app.ragcore.memory.elasticsearch_memory_index import ElasticsearchMemoryIndex

    return ElasticsearchMemoryIndex(get_es_client())


def _kb_service(db: AsyncSession = Depends(get_session)) -> KnowledgeBaseService:
    return KnowledgeBaseService(
        KnowledgeBaseRepository(db), OrganizationRepository(db), MemberRepository(db), db
    )


def _chat_session_service(db: AsyncSession = Depends(get_session)) -> ChatSessionService:
    return ChatSessionService(
        ChatSessionRepository(db),
        db,
        conversation_store=_conversation_store(),
        memory_index=_memory_index(),
    )


@router.post(
    "",
    response_model=ApiResponse[CreateSessionResponse],
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    kb_id: UUID,
    kb_service: KnowledgeBaseService = Depends(_kb_service),
    service: ChatSessionService = Depends(_chat_session_service),
) -> ApiResponse[CreateSessionResponse]:
    await kb_service.get_by_id_and_current_org(kb_id)  # 校验 kb 属于当前组织,越权 → 404
    ctx = get_tenant_context()
    chat_session = await service.create_session(ctx.org_id, kb_id, ctx.member_id)
    return ApiResponse.ok(CreateSessionResponse(sessionId=chat_session.id))


@router.get("", response_model=ApiResponse[list[ChatSessionSummaryOut]], response_model_exclude_none=True)
async def list_sessions(
    kb_id: UUID, service: ChatSessionService = Depends(_chat_session_service)
) -> ApiResponse[list[ChatSessionSummaryOut]]:
    ctx = get_tenant_context()
    summaries = await service.list_sessions(ctx.org_id, kb_id, ctx.member_id)
    return ApiResponse.ok(
        [
            ChatSessionSummaryOut(sessionId=s.session_id, title=s.title, lastActiveAt=s.last_active_at)
            for s in summaries
        ]
    )


@router.get(
    "/{session_id}/messages", response_model=ApiResponse[list[ChatMessageOut]], response_model_exclude_none=True
)
async def get_messages(
    kb_id: UUID, session_id: UUID, service: ChatSessionService = Depends(_chat_session_service)
) -> ApiResponse[list[ChatMessageOut]]:
    ctx = get_tenant_context()
    messages = await service.get_messages(ctx.org_id, kb_id, ctx.member_id, session_id)
    return ApiResponse.ok([ChatMessageOut.from_domain(m) for m in messages])


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_session(
    kb_id: UUID, session_id: UUID, service: ChatSessionService = Depends(_chat_session_service)
) -> None:
    ctx = get_tenant_context()
    await service.delete_session(ctx.org_id, kb_id, ctx.member_id, session_id)
