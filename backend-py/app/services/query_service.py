"""问答应用服务:在 HTTP 请求里完成租户校验和检索(prepare),在 SSE 流里只消费不可变查询
快照(stream)。对应 Java 版 service/QueryService.java。

会话记忆是可选增强(`rag_memory_enabled=false` 时 `memory_orchestrator`/`chat_session_service`
均为 None),退化为原先的无记忆单轮问答,不影响主链路。

**生成阶段两道闸(已接入)**:`stream()` 用 `FactVerificationGate` 边流边拦截生成流首行的
`{"found": true|false}` 判断(对应 Java 版 `gate.asConsumer()` 的位置)——`found:true` 补发
被延迟的引用事件后透传正文,`found:false` 只发一条固定拒答话术的 `REFUSAL` 事件、丢弃已
缓冲内容与后续输出;`async for` 正常耗尽后必须调用 `gate.flush()`(模型整段输出可能就是
判断行本身,不 flush 内容会永远卡在缓冲区里)。生成正文全部结束、且未被事实核验拒答时,
再用 `AnswerSelfChecker`(复用同一个 `RerankerClient` 实例,而不是新建)做一次生成后自检,
命中未支撑断言时追加一个 `SELF_CHECK_WARNING` 事件(对应 Java 版 `runSelfCheck`)。

`app.ragcore.quickdocument.*`(会话内临时文档)整个子包为空目录,本文件按 Java 版接口做了
一层可选降级(`QuickDocumentStore` 引入失败时视为始终不可用),不阻塞其余逻辑。

**转写差异说明**:Java 版 `AnswerGenerator.streamWithMetrics` 用 `Consumer<QueryEvent>` 回调 +
返回值拿 `GenerationMetrics`;Python 版 `AnswerGenerator` 协议(`ragcore/generation/client.py`)
改成 `async for event in generator.stream_with_metrics(question, contexts, metrics, ctx)` +
`metrics` 参数原地更新,详见该协议文件的说明。`FactVerificationGate` 在 Python 侧同样改成
pull-based 写法:`gate.feed(event) -> list[QueryEvent]`,调用方在 `async for` 循环里把上游
事件喂给它、收集返回的事件 yield 给下游,而不是像 Java 版那样把 `Consumer<QueryEvent>`
传进构造函数——两者语义一致,只是 Python 的 async generator 更适合 pull 风格。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator
from uuid import UUID

from app.core.tenant_context import get_tenant_context
from app.ragcore.audit.query_audit_snapshot import QueryAuditSnapshot
from app.ragcore.generation.answer_self_checker import AnswerSelfChecker
from app.ragcore.generation.citation_builder import build as build_citations
from app.ragcore.generation.client import AnswerGenerator
from app.ragcore.generation.fact_verification_gate import FactVerificationGate
from app.ragcore.generation.metrics import GenerationMetrics
from app.ragcore.intent.query_intent import QueryIntent
from app.ragcore.intent.query_intent_classifier import QueryIntentClassifier
from app.ragcore.memory.conversation_memory_orchestrator import ConversationMemoryOrchestrator
from app.ragcore.model import Chunk, Citation, QueryEvent, RetrievedChunk
from app.ragcore.rerank.client import RerankerClient
from app.ragcore.retrieval.retrieval_options import RetrievalOptions
from app.ragcore.retrieval.retriever import Retriever
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository
from app.services.chat_session_service import ChatSessionService
from app.services.knowledge_base_service import KnowledgeBaseService

try:  # 会话内临时文档子系统整体未落地,视为始终不可用(见模块文档字符串第 2 点)
    from app.ragcore.quickdocument.quick_document_store import QuickDocument, QuickDocumentStore
except ImportError:  # pragma: no cover
    QuickDocument = None  # type: ignore[assignment]
    QuickDocumentStore = None  # type: ignore[assignment]

# 精确检索型/语义理解型的 RRF 权重倾斜。1.3x/0.7x 是温和倾斜的保守起点,分类器本身和这组权重
# 都还没有经过真实评估集验证,写成命名常量而非配置项,调整需要走代码评审。
PRECISE_LOOKUP_BM25_WEIGHT = 1.3
PRECISE_LOOKUP_VECTOR_WEIGHT = 0.7
SEMANTIC_BM25_WEIGHT = 0.7
SEMANTIC_VECTOR_WEIGHT = 1.3


@dataclass(frozen=True)
class PreparedQuery:
    question: str
    resolved_question: str
    profile_context: str | None
    organization_id: UUID | None
    knowledge_base_id: UUID | None
    member_id: UUID | None
    session_id: UUID | None
    contexts: tuple[RetrievedChunk, ...] = field(default_factory=tuple)
    citations: tuple[Citation, ...] = field(default_factory=tuple)
    refusal_reason: str | None = None
    audit: QueryAuditSnapshot | None = None

    @staticmethod
    def refused(question: str, resolved_question: str, reason: str, audit: QueryAuditSnapshot) -> "PreparedQuery":
        return PreparedQuery(
            question=question,
            resolved_question=resolved_question,
            profile_context=None,
            organization_id=None,
            knowledge_base_id=None,
            member_id=None,
            session_id=None,
            contexts=(),
            citations=(),
            refusal_reason=reason,
            audit=audit,
        )


class QueryService:
    def __init__(
        self,
        retriever: Retriever | None,
        answer_generator: AnswerGenerator | None,
        knowledge_base_service: KnowledgeBaseService,
        document_repository: KnowledgeDocumentRepository,
        chat_session_service: ChatSessionService | None = None,
        memory_orchestrator: ConversationMemoryOrchestrator | None = None,
        reranker: RerankerClient | None = None,
        intent_classifier: QueryIntentClassifier | None = None,
        quick_document_store: "QuickDocumentStore | None" = None,
    ) -> None:
        self._retriever = retriever
        self._answer_generator = answer_generator
        self._kb_service = knowledge_base_service
        self._documents = document_repository
        self._chat_session_service = chat_session_service
        self._memory_orchestrator = memory_orchestrator
        self._reranker = reranker
        # AnswerSelfChecker 内部对 reranker_client=None 是 fail-open(check() 直接返回
        # SelfCheckResult.none()),这里始终构造一个实例、不必在调用处判空——复用同一个
        # RerankerClient 实例,不新建(混合检索本来就持有它)。
        self._self_checker = AnswerSelfChecker(reranker)
        self._intent_classifier = intent_classifier
        self._quick_document_store = quick_document_store

    async def prepare(self, knowledge_base_id: UUID, session_id: UUID, question: str, trace_id: str | None = None) -> PreparedQuery:
        trace_id = trace_id or str(uuid.uuid4())
        # 先按当前请求的租户上下文验证 kb,SSE 阶段不再读取租户上下文(见模块文档字符串)。
        await self._kb_service.get_by_id_and_current_org(knowledge_base_id)
        ctx = get_tenant_context()
        organization_id, member_id = ctx.org_id, ctx.member_id

        # 检索或生成服务未启用(settings.rag_retrieval_enabled / rag_generation_enabled 为 false
        # 时工厂层会注入 None)——fail-closed:不再走 retrieval/memory/intent,直接拒答。
        # 顺序必须放在 kb 校验与租户上下文之后,避免对无权访问的 kb 也泄露"服务未启用"信号。
        if self._retriever is None or self._answer_generator is None:
            return PreparedQuery.refused(
                question=question,
                resolved_question=question,
                reason="检索或生成服务未启用,无法回答",
                audit=QueryAuditSnapshot.before_retrieval(
                    trace_id, organization_id, knowledge_base_id, member_id
                ),
            )

        if self._chat_session_service is not None:
            # 校验归属并续期,越权/不存在 → 抛异常映射 404
            await self._chat_session_service.touch_session(organization_id, knowledge_base_id, member_id, session_id)

        resolved_question = question
        profile_context: str | None = None
        retrieval_options = RetrievalOptions.defaults()
        if self._memory_orchestrator is not None:
            memory_context = await self._memory_orchestrator.prepare_context(
                organization_id, member_id, session_id, question
            )
            resolved_question = memory_context.resolved_question
            profile_context = memory_context.profile_system_context if memory_context.has_profile_context else None
            if memory_context.resolved_question_vector is not None:
                retrieval_options = retrieval_options.with_precomputed_query_vector(
                    memory_context.resolved_question_vector
                )

        intent = QueryIntent.UNKNOWN
        if self._intent_classifier is not None:
            intent = await self._intent_classifier.classify(resolved_question)
        retrieval_options = self._apply_intent_weights(retrieval_options, intent)

        quick_document_names: dict[UUID, str] = {}
        quick_document_chunks: list[RetrievedChunk] = []
        if self._quick_document_store is not None:
            quick_document_chunks = await self._build_quick_document_chunks(
                session_id, organization_id, knowledge_base_id, quick_document_names
            )

        retrieval_started_at = time.perf_counter()
        result = await self._retriever.retrieve_with_decision(
            organization_id, knowledge_base_id, resolved_question, retrieval_options
        )
        retrieval_latency_ms = int((time.perf_counter() - retrieval_started_at) * 1000)

        # 会话挂着临时文档时,知识库检索本身触发的拒答阈值不再让整轮问答拒答——只有"检索拒答且
        # 没有临时文档兜底"才真正短路,审计快照必须按这个最终决策记录。
        actually_refused = result.refused and not quick_document_chunks
        contexts: list[RetrievedChunk] = list(quick_document_chunks)
        document_names: dict[UUID, str] = dict(quick_document_names)
        if not result.refused:
            self._assert_boundary(result.chunks, organization_id, knowledge_base_id)
            contexts.extend(result.chunks)
            docs = await self._documents.find_by_knowledge_base_id_and_org_id_order_by_created_at_desc(
                knowledge_base_id, organization_id
            )
            document_names.update({d.id: d.name for d in docs})

        audit = QueryAuditSnapshot.from_retrieval(
            trace_id=trace_id,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            member_id=member_id,
            retrieval_latency_ms=retrieval_latency_ms,
            chunks=contexts,
            diagnostics=result.diagnostics,
            refused=actually_refused,
            refusal_reason=result.refusal_reason if actually_refused else None,
            predicted_intent=self._to_audit_label(intent),
        )
        if actually_refused:
            # resolved_question(而非原始 question)才是意图分类实际处理过的文本。
            return PreparedQuery.refused(question, resolved_question, result.refusal_reason, audit)

        if quick_document_chunks and self._quick_document_store is not None:
            # 只续期本轮实际用到(即当前仍挂在会话上)的临时文档,未命中的按原 TTL 自然过期。
            await self._quick_document_store.touch(
                session_id, [c.chunk.document_id for c in quick_document_chunks]
            )

        return PreparedQuery(
            question=question,
            resolved_question=resolved_question,
            profile_context=profile_context,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            member_id=member_id,
            session_id=session_id,
            contexts=tuple(contexts),
            citations=tuple(build_citations(contexts, document_names)),
            refusal_reason=None,
            audit=audit,
        )

    async def _build_quick_document_chunks(
        self,
        session_id: UUID,
        organization_id: UUID,
        knowledge_base_id: UUID,
        name_map_out: dict[UUID, str],
    ) -> list[RetrievedChunk]:
        """会话内临时文档(长上下文直接塞入模式)包装成合成 RetrievedChunk:不经过 BM25/向量
        排序,final_score 固定设高值让它们排在知识库检索结果前面。
        """
        documents = await self._quick_document_store.find_all_by_session(session_id)
        chunks: list[RetrievedChunk] = []
        for document in documents:
            chunk = Chunk(
                id=f"quickdoc:{document.doc_id}",
                organization_id=organization_id,
                knowledge_base_id=knowledge_base_id,
                document_id=document.doc_id,
                ordinal=0,
                content=document.content,
                heading_path=(),
                source_path=None,
                page_no=None,
                line_start=None,
                line_end=None,
                language="text",
                content_hash=None,
                metadata={"quickDocument": "true"},
            )
            chunks.append(RetrievedChunk(chunk=chunk, final_score=1.0))
            name_map_out[document.doc_id] = document.filename
        return chunks

    async def stream(self, query: PreparedQuery, metrics: GenerationMetrics) -> AsyncIterator[QueryEvent]:
        """流式生成回答。`metrics` 由调用方传入,生成过程原地更新(见 client.py 协议说明),
        `async for` 正常耗尽后调用方可直接读取最终用量统计。

        生成事件先经过 `FactVerificationGate` 过闸(拦截首行 `{"found": ...}` 判断,
        `found:false` 时改判 REFUSED、丢弃已缓冲内容与后续输出),只有 `gate.feed()`/
        `gate.flush()` 返回的事件才会被 yield 给下游 SSE——上游 `AnswerGenerator` 产出的
        原始事件不再直接透传。`async for` 循环正常耗尽后必须调用一次 `gate.flush()`(模型
        整段输出可能就是判断行本身,不 flush 内容会永远卡在缓冲区里,见该类 docstring)。

        生成正文全部结束、且未被事实核验拒答时,再用 `AnswerSelfChecker`(构造时已复用
        `self._reranker` 同一个实例,见 `__init__`)对拼接好的正文做一次生成后自检,命中
        未支撑断言时追加一个 `SELF_CHECK_WARNING` 事件(对应 Java 版 `runSelfCheck`)。事实
        核验拒答时没有正文可检查,跳过自检(对应 Java 版 `!gate.refusedByFactVerification()`
        这个判断)。

        `gate.refused_by_fact_verification` 为 True 时,`metrics.fact_verification_refusal_reason`
        置为 `"NO_RETRIEVAL"`——这是 Java 版 `QueryService.stream()` 里
        `rawMetrics.withFactVerificationRefusalReason("NO_RETRIEVAL")` 的原样移植,路由层
        `_resolve_status`(`app/routers/query.py`)据此把审计状态记为 REFUSED 而不是
        COMPLETED。会话标题写入(`maybe_set_title`)只依赖问题文本,与本轮是否被事实核验
        拒答无关,始终执行;会话记忆写入(`record_turn`)则在事实核验拒答时跳过——拒答没有
        产生真实回答,与检索阶段拒答语义一致,不计入会话记忆(避免记一条空答案),这两点
        都照抄 Java 版 `stream()` 方法本体的处理(`orchestrator != null &&
        !gate.refusedByFactVerification()`)。
        """
        # 生成服务未启用(settings.rag_generation_enabled=false)时 self._answer_generator 为 None。
        # 即使 prepared 来自 prepare()(正常路径)prepare() 已经会拒答,这里再加一道防御式早退,
        # 避免直接 await None.stream_with_metrics 抛 AttributeError 进而让 SSE 裸抛 500。
        # 透传 refusal 事件而不是抛异常:与 prepare() 的拒答语义保持一致,SSE 客户端拿到一致
        # 的 refusal 事件流,而不是 connection-level 错误。
        if self._answer_generator is None:
            yield QueryEvent.refusal(
                query.refusal_reason or "生成服务未启用,无法回答"
            )
            return

        if query.refusal_reason is not None:
            yield QueryEvent.refusal(query.refusal_reason)
            return

        answer_parts: list[str] = []
        gate = FactVerificationGate(citations=list(query.citations))
        async for event in self._answer_generator.stream_with_metrics(
            query.resolved_question, list(query.contexts), metrics, query.profile_context
        ):
            for gated_event in gate.feed(event):
                if gated_event.content is not None:
                    answer_parts.append(gated_event.content)
                yield gated_event
        for gated_event in gate.flush():
            if gated_event.content is not None:
                answer_parts.append(gated_event.content)
            yield gated_event

        answer_text = "".join(answer_parts)
        refused_by_fact_verification = gate.refused_by_fact_verification
        if refused_by_fact_verification:
            # 审计状态判断依据,见本方法 docstring 与 app/routers/query.py 的 _resolve_status。
            metrics.fact_verification_refusal_reason = "NO_RETRIEVAL"
        else:
            self_check_result = await self._self_checker.check(answer_text, list(query.citations))
            if self_check_result.has_unsupported_claims:
                yield QueryEvent.self_check_warning(self_check_result.build_warning_message())

        if self._chat_session_service is not None:
            # 会话标题只依赖问题文本,与生成结果/是否被事实核验拒答无关(纯 Postgres 关注点)。
            await self._chat_session_service.maybe_set_title(
                query.organization_id, query.knowledge_base_id, query.member_id, query.session_id, query.question
            )
        if self._memory_orchestrator is not None and not refused_by_fact_verification:
            # 事实核验拒答没有产生真实回答,与检索阶段拒答语义一致,不计入会话记忆
            # (避免记一条空答案)——同 Java 版 `orchestrator != null && !gate.refusedByFactVerification()`。
            await self._memory_orchestrator.record_turn(
                query.organization_id,
                query.knowledge_base_id,
                query.member_id,
                query.session_id,
                query.question,
                answer_text,
                list(query.citations),
            )

    def _apply_intent_weights(self, options: RetrievalOptions, intent: QueryIntent) -> RetrievalOptions:
        """comparative/out-of-scope 分类结果本阶段只记录标签、不调整检索行为(见设计文档)。"""
        if intent == QueryIntent.PRECISE_LOOKUP:
            return options.with_weights(PRECISE_LOOKUP_BM25_WEIGHT, PRECISE_LOOKUP_VECTOR_WEIGHT)
        if intent == QueryIntent.SEMANTIC:
            return options.with_weights(SEMANTIC_BM25_WEIGHT, SEMANTIC_VECTOR_WEIGHT)
        return options

    def _to_audit_label(self, intent: QueryIntent) -> str | None:
        """UNKNOWN(分类失败/未启用)不写入审计表,其余映射为 prompt 里定义的字面量。"""
        if intent == QueryIntent.UNKNOWN:
            return None
        return intent.value

    def _assert_boundary(self, chunks: list[RetrievedChunk], organization_id: UUID, knowledge_base_id: UUID) -> None:
        for item in chunks:
            if item.chunk.organization_id != organization_id or item.chunk.knowledge_base_id != knowledge_base_id:
                raise RuntimeError("检索结果越过组织或知识库边界")
