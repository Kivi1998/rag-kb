"""会话内临时文档(长上下文直接塞入模式):不写入知识库、不切块不索引,只在当前会话有效。
上传接口同步阻塞——解析(含 OCR 网关降级)完成才返回,不走异步任务状态机。
对应 Java 版 controller/QuickDocumentController.java。

装配入口:`_quick_document_service` 把 6 个本地解析器 + Redis 临时文档存储串起来;
`settings.rag_quick_document_enabled=false` 时 `_quick_document_service` 直接抛
`RuntimeError` 让 router 层在调用时主动抛 400,避免用户看到 500。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.core.tenant_context import get_tenant_context
from app.ragcore.parser.code_parser import CodeParser
from app.ragcore.parser.docx_parser import DocxParser
from app.ragcore.parser.factory import DocumentParserFactory
from app.ragcore.parser.markdown_parser import MarkdownParser
from app.ragcore.parser.local_multimodal_parser import LocalMultimodalDocumentParser
from app.ragcore.parser.pdf_parser import PdfParser
from app.ragcore.parser.pptx_parser import PptxParser
from app.ragcore.parser.structured_data_parser import StructuredDataParser
from app.ragcore.parser.subtitle_parser import SubtitleParser
from app.ragcore.parser.text_parser import TextParser
from app.ragcore.quickdocument.quick_document import QuickDocument
from app.ragcore.quickdocument.quick_document_service import QuickDocumentService
from app.routers._factories import build_quick_document_store
from app.routers.chat_sessions import _chat_session_service
from app.routers.deps import get_session, require_tenant
from app.schemas.common import ApiResponse
from app.schemas.quick_document import QuickDocumentSummary
from app.services.chat_session_service import ChatSessionService

router = APIRouter(
    prefix="/api/v1/knowledge-bases/{kb_id}/sessions/{session_id}/quick-documents",
    tags=["quick-documents"],
    dependencies=[Depends(require_tenant)],
)


# 模块级单例:9 个解析器(6 本地 + 3 新增)与 DocumentParserFactory 都无内部状态,
# 允许多请求共用。本地多模态解析器在 settings 关闭时 supports() 自动返回 False,
# 不影响临时文档同步解析的现有契约。
_PARSER_FACTORY = DocumentParserFactory(
    [
        PdfParser(),
        DocxParser(),
        PptxParser(),
        MarkdownParser(),
        StructuredDataParser(),
        CodeParser(),
        TextParser(),
        SubtitleParser(),
        LocalMultimodalDocumentParser(),
    ]
)


def _quick_document_service(db: AsyncSession = Depends(get_session)) -> QuickDocumentService:
    store = build_quick_document_store()
    if store is None:
        # 与 main.py 的 `settings.rag_quick_document_enabled` 门控对齐:模块未启用时
        # 在 router 层直接抛 400,避免上游看到 500。
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="会话内临时文档功能未启用(rag_quick_document_enabled=false)",
        )
    return QuickDocumentService(parser_factory=_PARSER_FACTORY, store=store)


def _to_summary(document: QuickDocument) -> QuickDocumentSummary:
    return QuickDocumentSummary(
        docId=document.doc_id, filename=document.filename, characterCount=document.character_count
    )


@router.post("", response_model=ApiResponse[QuickDocumentSummary], response_model_exclude_none=True)
async def upload(
    kb_id: UUID,
    session_id: UUID,
    file: UploadFile = File(...),
    chat_session_service: ChatSessionService = Depends(_chat_session_service),
    service: QuickDocumentService = Depends(_quick_document_service),
) -> ApiResponse[QuickDocumentSummary]:
    ctx = get_tenant_context()
    await chat_session_service.touch_session(ctx.org_id, kb_id, ctx.member_id, session_id)  # 校验归属,越权/不存在 → 404
    document = await service.upload(session_id, file)
    return ApiResponse.ok(_to_summary(document))


@router.get("", response_model=ApiResponse[list[QuickDocumentSummary]], response_model_exclude_none=True)
async def list_quick_documents(
    kb_id: UUID,
    session_id: UUID,
    chat_session_service: ChatSessionService = Depends(_chat_session_service),
    service: QuickDocumentService = Depends(_quick_document_service),
) -> ApiResponse[list[QuickDocumentSummary]]:
    ctx = get_tenant_context()
    # 只读校验归属,不像 touch_session 那样把只读请求悄悄续期成一次会话活跃。
    await chat_session_service.require_owned_session(ctx.org_id, kb_id, ctx.member_id, session_id)
    documents = await service.list(session_id)
    return ApiResponse.ok([_to_summary(d) for d in documents])


@router.delete("/{doc_id}", response_model=ApiResponse[None], response_model_exclude_none=True)
async def delete(
    kb_id: UUID,
    session_id: UUID,
    doc_id: UUID,
    chat_session_service: ChatSessionService = Depends(_chat_session_service),
    service: QuickDocumentService = Depends(_quick_document_service),
) -> ApiResponse[None]:
    ctx = get_tenant_context()
    await chat_session_service.require_owned_session(ctx.org_id, kb_id, ctx.member_id, session_id)
    await service.delete(session_id, doc_id)
    return ApiResponse.ok()
