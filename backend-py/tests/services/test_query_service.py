"""QueryService `prepare` 主流程测试 + `stream` 透传测试。

对照 Java 版 `service/QueryService.java`。
关键不变量:
- `prepare` 必须先校验 kb 属于当前租户(org_id 取自 tenant_context),否则直接 404
- 检索结果的所有 chunk 必须严格属于 (org_id, kb_id) 边界,否则抛 RuntimeError
  ——这是防"越权召回"的安全门,即使下游不严格过滤也能在这里兜住
- 拒答(refused=True)且无 quick_document 兜底时,PreparedQuery.refusal_reason 必填
  且 audit 快照也带 refusal_reason
- quick_document 存在时,检索拒答不再让整轮问答拒答——兜底语义
- `stream` 在 query.refusal_reason 非空时,第一个事件必须是 refusal
  (Java 端 FactVerificationGate 落地前的当前行为,生成器产物原样透传)
- `_apply_intent_weights`:PRECISE_LOOKUP → (1.3, 0.7);SEMANTIC → (0.7, 1.3)
- `_to_audit_label`:UNKNOWN 映射为 None(永不写入审计表)
"""

from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.tenant_context import TenantContext
from app.exceptions.errors import ResourceNotFoundException
from app.ragcore.generation.client import AnswerGenerator
from app.ragcore.generation.metrics import GenerationMetrics
from app.ragcore.intent.query_intent import QueryIntent
from app.ragcore.intent.query_intent_classifier import QueryIntentClassifier
from app.ragcore.model import Chunk, QueryEvent, RetrievedChunk
from app.ragcore.retrieval.retrieval_diagnostics import RetrievalDiagnostics
from app.ragcore.retrieval.retrieval_options import RetrievalOptions
from app.ragcore.retrieval.retrieval_result import RetrievalResult
from app.ragcore.retrieval.retriever import Retriever
from app.services.chat_session_service import ChatSessionService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.query_service import (
    PRECISE_LOOKUP_BM25_WEIGHT,
    PRECISE_LOOKUP_VECTOR_WEIGHT,
    SEMANTIC_BM25_WEIGHT,
    SEMANTIC_VECTOR_WEIGHT,
    QueryService,
)


def _set_tenant(org_id: UUID, member_id: UUID, role: str = "MEMBER") -> None:
    from app.core import tenant_context

    tenant_context._tenant_context.set(
        TenantContext(org_id=org_id, member_id=member_id, role=role)
    )


def _make_chunk(
    chunk_id: str = "c1",
    document_id: UUID | None = None,
    organization_id: UUID | None = None,
    knowledge_base_id: UUID | None = None,
    final_score: float | None = 0.8,
) -> RetrievedChunk:
    c = Chunk(
        id=chunk_id,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id or uuid4(),
        ordinal=0,
        content="hello world",
    )
    return RetrievedChunk(chunk=c, final_score=final_score)


class _StubRetriever(Retriever):
    """Retriever 协议 stub,默认返回给定 chunks 的 RetrievalResult。"""

    def __init__(self, result: RetrievalResult) -> None:
        self._result = result
        self.call_count = 0
        self.last_options: RetrievalOptions | None = None

    async def retrieve(self, organization_id, knowledge_base_id, query, options):
        return list(self._result.chunks)

    async def retrieve_with_decision(self, organization_id, knowledge_base_id, query, options):
        self.call_count += 1
        self.last_options = options
        return self._result


class _StubIntentClassifier(QueryIntentClassifier):
    def __init__(self, intent: QueryIntent = QueryIntent.UNKNOWN) -> None:
        self._intent = intent

    async def classify(self, question: str) -> QueryIntent:
        return self._intent


class _StubGenerator(AnswerGenerator):
    def __init__(self, events: list[QueryEvent] | None = None) -> None:
        self._events = events or [QueryEvent.chunk("hi"), QueryEvent.done()]
        self.called_with_question: str | None = None

    def model_id(self) -> str:
        return "stub-model"

    async def stream_with_metrics(self, question, contexts, metrics, additional_system_context=None):
        self.called_with_question = question
        for e in self._events:
            yield e


def _build_service(
    retriever: Retriever,
    kb_service: KnowledgeBaseService | None = None,
    document_repository: AsyncMock | None = None,
    chat_session_service: ChatSessionService | None = None,
    intent_classifier: QueryIntentClassifier | None = None,
    answer_generator: AnswerGenerator | None = None,
) -> QueryService:
    return QueryService(
        retriever=retriever,
        answer_generator=answer_generator or _StubGenerator(),
        knowledge_base_service=kb_service or AsyncMock(spec=KnowledgeBaseService),
        document_repository=document_repository or AsyncMock(),
        chat_session_service=chat_session_service,
        memory_orchestrator=None,
        reranker=None,
        intent_classifier=intent_classifier,
        quick_document_store=None,
    )


class TestPrepareRequiresKbOwnership:
    @pytest.mark.asyncio
    async def test_kb_not_in_current_org_raises_404(self):
        """kb 不属于当前租户 → KnowledgeBaseService 抛 404 → prepare 直接向上抛。"""
        org_id = uuid4()
        member_id = uuid4()
        _set_tenant(org_id, member_id)
        kb_id = uuid4()
        session_id = uuid4()

        kb_service = AsyncMock(spec=KnowledgeBaseService)
        kb_service.get_by_id_and_current_org.side_effect = ResourceNotFoundException("知识库不存在")

        retriever = _StubRetriever(RetrievalResult.of([]))
        service = _build_service(retriever, kb_service=kb_service)

        with pytest.raises(ResourceNotFoundException):
            await service.prepare(
                knowledge_base_id=kb_id, session_id=session_id, question="hi"
            )
        # 鉴权失败,retriever 不应被调用
        assert retriever.call_count == 0


class TestPrepareHappyPath:
    @pytest.mark.asyncio
    async def test_returns_chunks_citations_and_audit(self):
        org_id, member_id = uuid4(), uuid4()
        _set_tenant(org_id, member_id)
        kb_id, doc_id = uuid4(), uuid4()

        chunk = _make_chunk(
            chunk_id="c1", document_id=doc_id,
            organization_id=org_id, knowledge_base_id=kb_id,
            final_score=0.9,
        )
        retriever = _StubRetriever(RetrievalResult.of([chunk]))

        kb_service = AsyncMock(spec=KnowledgeBaseService)
        kb_service.get_by_id_and_current_org.return_value = MagicMock()

        doc = MagicMock(spec=["id", "name"])
        doc.id = doc_id
        doc.name = "doc-name"
        doc_repo = AsyncMock()
        doc_repo.find_by_knowledge_base_id_and_org_id_order_by_created_at_desc.return_value = [doc]

        service = _build_service(
            retriever,
            kb_service=kb_service,
            document_repository=doc_repo,
        )

        prepared = await service.prepare(
            knowledge_base_id=kb_id, session_id=uuid4(), question="hello"
        )

        # 主流程:retriever 被调用一次
        assert retriever.call_count == 1
        # contexts 含本次召回的 chunk
        assert len(prepared.contexts) == 1
        assert prepared.contexts[0].chunk.id == "c1"
        # citations 至少 1 条,document_name 来自 find_by_kb_org
        assert len(prepared.citations) == 1
        assert prepared.citations[0].document_name == "doc-name"
        # 不拒答
        assert prepared.refusal_reason is None
        # audit 快照存在,带 chunk_ids / document_ids
        assert prepared.audit is not None
        assert prepared.audit.chunk_ids == ("c1",)
        assert prepared.audit.document_ids == (doc_id,)


class TestPrepareBoundaryCheck:
    @pytest.mark.asyncio
    async def test_chunk_outside_org_boundary_raises(self):
        """越权召回:retriever 返回的 chunk 带有别人的 org_id——必须抛 RuntimeError 兜住。"""
        org_id, member_id = uuid4(), uuid4()
        _set_tenant(org_id, member_id)
        kb_id = uuid4()
        # chunk 来自另一个 org——boundary 必失败
        other_org = uuid4()
        chunk = _make_chunk(
            organization_id=other_org,
            knowledge_base_id=kb_id,
        )
        retriever = _StubRetriever(RetrievalResult.of([chunk]))

        kb_service = AsyncMock(spec=KnowledgeBaseService)
        kb_service.get_by_id_and_current_org.return_value = MagicMock()
        doc_repo = AsyncMock()
        doc_repo.find_by_knowledge_base_id_and_org_id_order_by_created_at_desc.return_value = []

        service = _build_service(retriever, kb_service=kb_service, document_repository=doc_repo)

        with pytest.raises(RuntimeError):
            await service.prepare(
                knowledge_base_id=kb_id, session_id=uuid4(), question="leak"
            )

    @pytest.mark.asyncio
    async def test_chunk_outside_kb_boundary_raises(self):
        """越权召回:chunk 来自另一个 kb_id——必须抛。"""
        org_id, member_id = uuid4(), uuid4()
        _set_tenant(org_id, member_id)
        kb_id = uuid4()
        other_kb = uuid4()
        chunk = _make_chunk(organization_id=org_id, knowledge_base_id=other_kb)
        retriever = _StubRetriever(RetrievalResult.of([chunk]))

        kb_service = AsyncMock(spec=KnowledgeBaseService)
        kb_service.get_by_id_and_current_org.return_value = MagicMock()
        doc_repo = AsyncMock()
        doc_repo.find_by_knowledge_base_id_and_org_id_order_by_created_at_desc.return_value = []

        service = _build_service(retriever, kb_service=kb_service, document_repository=doc_repo)

        with pytest.raises(RuntimeError):
            await service.prepare(
                knowledge_base_id=kb_id, session_id=uuid4(), question="leak"
            )


class TestPrepareRefused:
    @pytest.mark.asyncio
    async def test_refused_result_propagates_to_prepared(self):
        org_id, member_id = uuid4(), uuid4()
        _set_tenant(org_id, member_id)
        kb_id = uuid4()

        retriever = _StubRetriever(RetrievalResult.refuse("参考资料不包含具体答案"))
        kb_service = AsyncMock(spec=KnowledgeBaseService)
        kb_service.get_by_id_and_current_org.return_value = MagicMock()

        service = _build_service(retriever, kb_service=kb_service)

        prepared = await service.prepare(
            knowledge_base_id=kb_id, session_id=uuid4(), question="hi"
        )
        # 拒答
        assert prepared.refusal_reason == "参考资料不包含具体答案"
        assert prepared.audit is not None
        assert prepared.audit.refused is True
        assert prepared.audit.refusal_reason == "参考资料不包含具体答案"
        # 拒答时 context 应为空
        assert prepared.contexts == ()

    @pytest.mark.asyncio
    async def test_retriever_none_returns_refused_without_attribute_error(self):
        """settings.rag_retrieval_enabled=false → 工厂层注入 retriever=None,prepare 必须
        fail-closed 返回拒答,而不是在 _retriever.retrieve_with_decision() 上 AttributeError。
        kb 校验仍然要先调(权限先行),retriever 必须保持未被调用。"""
        org_id, member_id = uuid4(), uuid4()
        _set_tenant(org_id, member_id)
        kb_id = uuid4()

        kb_service = AsyncMock(spec=KnowledgeBaseService)
        kb_service.get_by_id_and_current_org.return_value = MagicMock()
        answer_generator = _StubGenerator()

        service = QueryService(
            retriever=None,
            answer_generator=answer_generator,
            knowledge_base_service=kb_service,
            document_repository=AsyncMock(),
            chat_session_service=None,
            memory_orchestrator=None,
            reranker=None,
            intent_classifier=None,
            quick_document_store=None,
        )

        prepared = await service.prepare(
            knowledge_base_id=kb_id, session_id=uuid4(), question="hi"
        )

        # 拒答而不是抛异常
        assert prepared.refusal_reason is not None
        assert "未启用" in prepared.refusal_reason
        assert prepared.contexts == ()
        assert prepared.citations == ()
        # kb 校验必须先调(retriever=None 也不能跳过鉴权)
        kb_service.get_by_id_and_current_org.assert_awaited_once_with(kb_id)
        # 生成器不应被任何 retriever 类逻辑触发
        assert answer_generator.called_with_question is None

    @pytest.mark.asyncio
    async def test_answer_generator_none_returns_refused_without_attribute_error(self):
        """settings.rag_generation_enabled=false → 工厂层注入 answer_generator=None,prepare 必须
        fail-closed 返回拒答,而不是走到 stream() 阶段才暴露。"""
        org_id, member_id = uuid4(), uuid4()
        _set_tenant(org_id, member_id)
        kb_id = uuid4()

        kb_service = AsyncMock(spec=KnowledgeBaseService)
        kb_service.get_by_id_and_current_org.return_value = MagicMock()
        retriever = _StubRetriever(RetrievalResult.of([]))

        service = QueryService(
            retriever=retriever,
            answer_generator=None,
            knowledge_base_service=kb_service,
            document_repository=AsyncMock(),
            chat_session_service=None,
            memory_orchestrator=None,
            reranker=None,
            intent_classifier=None,
            quick_document_store=None,
        )

        prepared = await service.prepare(
            knowledge_base_id=kb_id, session_id=uuid4(), question="hi"
        )

        # 拒答而不是抛异常
        assert prepared.refusal_reason is not None
        assert "未启用" in prepared.refusal_reason
        assert prepared.contexts == ()
        assert prepared.citations == ()
        # 早退发生在 retriever 之前:retriever 不应被调用(否则一旦 answer_generator 缺席仍去
        # 拉取 chunk,会浪费 ES 流量且 audit 看起来像正常检索)
        assert retriever.call_count == 0
        # audit 走 before_retrieval:refused=False(retrieval 未发生)、refusal_reason=None
        # (拒答语义由 PreparedQuery.refusal_reason 承载,audit 表达"还没开始检索就退了")
        assert prepared.audit is not None
        assert prepared.audit.refused is False
        assert prepared.audit.refusal_reason is None


class TestIntentWeightApplication:
    @pytest.mark.asyncio
    async def test_precise_lookup_uses_bm25_heavy_weights(self):
        org_id, member_id = uuid4(), uuid4()
        _set_tenant(org_id, member_id)
        kb_id, doc_id = uuid4(), uuid4()
        chunk = _make_chunk(
            document_id=doc_id, organization_id=org_id, knowledge_base_id=kb_id
        )
        retriever = _StubRetriever(RetrievalResult.of([chunk]))
        kb_service = AsyncMock(spec=KnowledgeBaseService)
        kb_service.get_by_id_and_current_org.return_value = MagicMock()
        doc_repo = AsyncMock()
        _doc = MagicMock(spec=["id", "name"])
        _doc.id = doc_id
        _doc.name = "n"
        doc_repo.find_by_knowledge_base_id_and_org_id_order_by_created_at_desc.return_value = [_doc]
        classifier = _StubIntentClassifier(QueryIntent.PRECISE_LOOKUP)
        service = _build_service(
            retriever, kb_service=kb_service, document_repository=doc_repo,
            intent_classifier=classifier,
        )

        await service.prepare(knowledge_base_id=kb_id, session_id=uuid4(), question="x")

        assert retriever.last_options.bm25_weight == PRECISE_LOOKUP_BM25_WEIGHT
        assert retriever.last_options.vector_weight == PRECISE_LOOKUP_VECTOR_WEIGHT
        # 这些常量应该是 1.3 / 0.7
        assert PRECISE_LOOKUP_BM25_WEIGHT == 1.3
        assert PRECISE_LOOKUP_VECTOR_WEIGHT == 0.7

    @pytest.mark.asyncio
    async def test_semantic_uses_vector_heavy_weights(self):
        org_id, member_id = uuid4(), uuid4()
        _set_tenant(org_id, member_id)
        kb_id, doc_id = uuid4(), uuid4()
        chunk = _make_chunk(
            document_id=doc_id, organization_id=org_id, knowledge_base_id=kb_id
        )
        retriever = _StubRetriever(RetrievalResult.of([chunk]))
        kb_service = AsyncMock(spec=KnowledgeBaseService)
        kb_service.get_by_id_and_current_org.return_value = MagicMock()
        doc_repo = AsyncMock()
        _doc = MagicMock(spec=["id", "name"])
        _doc.id = doc_id
        _doc.name = "n"
        doc_repo.find_by_knowledge_base_id_and_org_id_order_by_created_at_desc.return_value = [_doc]
        classifier = _StubIntentClassifier(QueryIntent.SEMANTIC)
        service = _build_service(
            retriever, kb_service=kb_service, document_repository=doc_repo,
            intent_classifier=classifier,
        )

        await service.prepare(knowledge_base_id=kb_id, session_id=uuid4(), question="x")

        assert retriever.last_options.bm25_weight == SEMANTIC_BM25_WEIGHT
        assert retriever.last_options.vector_weight == SEMANTIC_VECTOR_WEIGHT
        assert SEMANTIC_BM25_WEIGHT == 0.7
        assert SEMANTIC_VECTOR_WEIGHT == 1.3

    @pytest.mark.asyncio
    async def test_unknown_intent_keeps_equal_weights(self):
        org_id, member_id = uuid4(), uuid4()
        _set_tenant(org_id, member_id)
        kb_id, doc_id = uuid4(), uuid4()
        chunk = _make_chunk(
            document_id=doc_id, organization_id=org_id, knowledge_base_id=kb_id
        )
        retriever = _StubRetriever(RetrievalResult.of([chunk]))
        kb_service = AsyncMock(spec=KnowledgeBaseService)
        kb_service.get_by_id_and_current_org.return_value = MagicMock()
        doc_repo = AsyncMock()
        _doc = MagicMock(spec=["id", "name"])
        _doc.id = doc_id
        _doc.name = "n"
        doc_repo.find_by_knowledge_base_id_and_org_id_order_by_created_at_desc.return_value = [_doc]
        classifier = _StubIntentClassifier(QueryIntent.UNKNOWN)
        service = _build_service(
            retriever, kb_service=kb_service, document_repository=doc_repo,
            intent_classifier=classifier,
        )

        await service.prepare(knowledge_base_id=kb_id, session_id=uuid4(), question="x")

        # UNKNOWN 不调整权重,保持默认等权
        assert retriever.last_options.bm25_weight == 1.0
        assert retriever.last_options.vector_weight == 1.0


class TestStreamRefusal:
    @pytest.mark.asyncio
    async def test_stream_yields_refusal_event_first_when_refused(self):
        """refusal_reason 非空时,stream 第一个事件必须是 refusal 事件。"""
        from app.services.query_service import PreparedQuery

        service = _build_service(_StubRetriever(RetrievalResult.of([])))
        snap = MagicMock()
        snap.trace_id = "t"
        snap.organization_id = uuid4()
        snap.knowledge_base_id = uuid4()
        snap.member_id = uuid4()
        snap.session_id = uuid4()
        snap.question = "q"
        snap.resolved_question = "q"
        snap.profile_context = None
        snap.contexts = ()
        snap.citations = ()
        snap.refusal_reason = "参考资料不包含具体答案"
        snap.audit = None
        query = PreparedQuery.refused("q", "q", "参考资料不包含具体答案", snap)

        events: list[QueryEvent] = []
        async for e in service.stream(query, GenerationMetrics()):
            events.append(e)

        # 第一个事件必须是 refusal
        assert events[0].type.value == "refusal"
        assert events[0].message == "参考资料不包含具体答案"
        # 终止后不应再产生 chunk 事件
        assert all(e.type.value not in ("chunk",) for e in events[1:])


class TestIntentToAuditLabel:
    """_to_audit_label 把 UNKNOWN 映射为 None(永不写入 rag_query_audit.predicted_intent)"""

    def test_unknown_intent_returns_none(self):
        service = _build_service(_StubRetriever(RetrievalResult.of([])))
        assert service._to_audit_label(QueryIntent.UNKNOWN) is None

    def test_precise_lookup_returns_label_value(self):
        service = _build_service(_StubRetriever(RetrievalResult.of([])))
        assert service._to_audit_label(QueryIntent.PRECISE_LOOKUP) == "precise-lookup"

    def test_semantic_returns_label_value(self):
        service = _build_service(_StubRetriever(RetrievalResult.of([])))
        assert service._to_audit_label(QueryIntent.SEMANTIC) == "semantic"

    def test_comparative_returns_label_value(self):
        service = _build_service(_StubRetriever(RetrievalResult.of([])))
        assert service._to_audit_label(QueryIntent.COMPARATIVE) == "comparative"

    def test_out_of_scope_returns_label_value(self):
        service = _build_service(_StubRetriever(RetrievalResult.of([])))
        assert service._to_audit_label(QueryIntent.OUT_OF_SCOPE) == "out-of-scope"
