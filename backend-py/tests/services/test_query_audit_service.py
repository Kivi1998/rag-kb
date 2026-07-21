"""QueryAuditService 审计落库测试。

对照 Java 版 `service/QueryAuditService.java`(@Transactional(REQUIRES_NEW))。
关键不变量:
- `record` 成功路径:写入 QueryAuditLog + commit + 输出结构化日志
- `record_safely` 失败路径:落库异常被吞,只记服务端错误日志,绝不能向上抛
  ——审计失败不得反向影响已开始的 SSE 响应
- chunk_ids / document_ids / final_scores 必须以 JSON 字符串落库
- generation_latency_ms / total_latency_ms 通过 `max(0, ...)` 兜底,负数会被压回 0
- metrics=None 时用空 GenerationMetrics 兜底,不抛
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.enums import QueryAuditStatus
from app.ragcore.audit.query_audit_snapshot import QueryAuditSnapshot
from app.ragcore.generation.metrics import GenerationMetrics
from app.ragcore.model import Chunk, RetrievedChunk
from app.ragcore.retrieval.retrieval_diagnostics import RetrievalDiagnostics
from app.services.query_audit_service import QueryAuditService


def _build_snapshot(**overrides) -> QueryAuditSnapshot:
    defaults = dict(
        trace_id="trace-abc",
        organization_id=uuid4(),
        knowledge_base_id=uuid4(),
        member_id=uuid4(),
        retrieval_latency_ms=42,
    )
    defaults.update(overrides)
    return QueryAuditSnapshot(**defaults)


def _build_service() -> tuple[QueryAuditService, AsyncMock, AsyncMock]:
    repo = AsyncMock()
    session = AsyncMock()
    service = QueryAuditService(repo, session)
    return service, repo, session


def _make_chunk(chunk_id: str = "c1") -> Chunk:
    return Chunk(
        id=chunk_id,
        organization_id=uuid4(),
        knowledge_base_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        content="x",
    )


class TestRecordHappyPath:
    @pytest.mark.asyncio
    async def test_record_persists_entity_and_commits(self):
        service, repo, session = _build_service()
        snap = _build_snapshot()

        await service.record(
            snapshot=snap,
            status=QueryAuditStatus.COMPLETED,
            metrics=GenerationMetrics(model="gpt-x", prompt_tokens=10, completion_tokens=20, output_characters=30),
            generation_latency_ms=100,
            total_latency_ms=200,
            error_code=None,
        )

        # save 必须被调用一次(写入 rag_query_audit 行)
        repo.save.assert_awaited_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_serializes_collections_to_json(self):
        """chunk_ids / document_ids / final_scores 三列必须以 JSON 字符串落库。"""
        service, repo, _session = _build_service()
        org = uuid4()
        kb = uuid4()
        doc_id = uuid4()
        chunks = [
            RetrievedChunk(chunk=Chunk(
                id="c-1", organization_id=org, knowledge_base_id=kb,
                document_id=doc_id, ordinal=0, content="x",
            ), final_score=0.9),
            RetrievedChunk(chunk=Chunk(
                id="c-2", organization_id=org, knowledge_base_id=kb,
                document_id=doc_id, ordinal=1, content="y",
            ), final_score=None),
        ]
        snap = QueryAuditSnapshot.from_retrieval(
            trace_id="t",
            organization_id=org,
            knowledge_base_id=kb,
            member_id=uuid4(),
            retrieval_latency_ms=10,
            chunks=chunks,
            diagnostics=RetrievalDiagnostics.empty(),
            refused=False,
            refusal_reason=None,
            predicted_intent="semantic",
        )

        await service.record(
            snapshot=snap,
            status=QueryAuditStatus.COMPLETED,
            metrics=GenerationMetrics(),
            generation_latency_ms=10,
            total_latency_ms=20,
            error_code=None,
        )

        saved_entity = repo.save.await_args.args[0]
        # 字段必须是 JSON 字符串(供下游读端 json.loads 解析)
        assert isinstance(saved_entity.chunk_ids_json, str)
        assert json.loads(saved_entity.chunk_ids_json) == ["c-1", "c-2"]
        assert isinstance(saved_entity.document_ids_json, str)
        # document_ids 去重保序 → 只有 1 个
        assert json.loads(saved_entity.document_ids_json) == [str(doc_id)]
        assert isinstance(saved_entity.final_scores_json, str)
        # final_score=None 的 chunk 被过滤,只剩一个
        assert json.loads(saved_entity.final_scores_json) == [0.9]
        # 标签透传
        assert saved_entity.predicted_intent == "semantic"

    @pytest.mark.asyncio
    async def test_record_metrics_none_falls_back_to_empty(self):
        """metrics=None 时,不能让它在 entity 构造时崩,必须用空 GenerationMetrics 兜底。"""
        service, repo, _session = _build_service()
        snap = _build_snapshot()

        await service.record(
            snapshot=snap,
            status=QueryAuditStatus.FAILED,
            metrics=None,
            generation_latency_ms=0,
            total_latency_ms=10,
            error_code="LLM_TIMEOUT",
        )

        saved = repo.save.await_args.args[0]
        # 默认空 metrics,字段都为 None / 0
        assert saved.generation_model == "unknown"
        assert saved.prompt_tokens is None
        assert saved.completion_tokens is None
        assert saved.output_characters == 0
        # 错误码透传
        assert saved.error_code == "LLM_TIMEOUT"

    @pytest.mark.asyncio
    async def test_record_clamps_negative_latencies_to_zero(self):
        """负的生成/总延迟被 `max(0, ...)` 压回 0——DB CheckConstraint 同样下限是 0。"""
        service, repo, _session = _build_service()
        snap = _build_snapshot()

        await service.record(
            snapshot=snap,
            status=QueryAuditStatus.COMPLETED,
            metrics=GenerationMetrics(),
            generation_latency_ms=-50,
            total_latency_ms=-100,
            error_code=None,
        )

        saved = repo.save.await_args.args[0]
        assert saved.generation_latency_ms == 0
        assert saved.total_latency_ms == 0

    @pytest.mark.asyncio
    async def test_record_propagates_status_value(self):
        """status 写入时是 .value(字符串),不是枚举本体——与 rag_query_audit.status VARCHAR(20) 列一致。"""
        service, repo, _session = _build_service()
        snap = _build_snapshot()

        for status in QueryAuditStatus:
            repo.reset_mock()
            await service.record(
                snapshot=snap,
                status=status,
                metrics=GenerationMetrics(),
                generation_latency_ms=1,
                total_latency_ms=2,
                error_code=None,
            )
            saved = repo.save.await_args.args[0]
            assert saved.status == status.value

    @pytest.mark.asyncio
    async def test_record_carries_diagnostics_flags(self):
        """embedding_fallback / rerank_fallback 来自 diagnostics,审计用途需要能看到。"""
        service, repo, _session = _build_service()
        snap = QueryAuditSnapshot.from_retrieval(
            trace_id="t",
            organization_id=uuid4(),
            knowledge_base_id=uuid4(),
            member_id=uuid4(),
            retrieval_latency_ms=10,
            chunks=[],
            diagnostics=RetrievalDiagnostics(
                bm25_candidate_count=5,
                vector_candidate_count=3,
                fused_candidate_count=5,
                embedding_fallback=True,
                rerank_fallback=True,
            ),
            refused=False,
            refusal_reason=None,
            predicted_intent=None,
        )

        await service.record(
            snapshot=snap,
            status=QueryAuditStatus.COMPLETED,
            metrics=GenerationMetrics(),
            generation_latency_ms=10,
            total_latency_ms=20,
            error_code=None,
        )

        saved = repo.save.await_args.args[0]
        assert saved.embedding_fallback is True
        assert saved.rerank_fallback is True


class TestRecordSafelyFailurePath:
    @pytest.mark.asyncio
    async def test_record_safely_swallows_repo_failure(self, caplog):
        """record_safely 包裹 record,record 抛异常时不能向上传播——审计失败只记日志。"""
        service, repo, _session = _build_service()
        repo.save.side_effect = ConnectionError("DB down")

        with caplog.at_level(logging.ERROR, logger="app.services.query_audit_service"):
            # 不应抛
            await service.record_safely(
                snapshot=_build_snapshot(),
                status=QueryAuditStatus.COMPLETED,
                metrics=GenerationMetrics(),
                generation_latency_ms=10,
                total_latency_ms=20,
                error_code=None,
            )

        # 错误日志存在,带 traceId
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_logs, "应该至少有一条 ERROR 级别日志"
        # 日志消息中包含 trace_id,方便排查
        assert any("trace-abc" in r.getMessage() for r in error_logs)

    @pytest.mark.asyncio
    async def test_record_safely_swallows_commit_failure(self, caplog):
        """save 成功但 commit 失败时同样被吞——整体写入失败都不应影响 SSE。"""
        service, repo, session = _build_service()
        session.commit.side_effect = RuntimeError("commit failed")

        with caplog.at_level(logging.ERROR, logger="app.services.query_audit_service"):
            await service.record_safely(
                snapshot=_build_snapshot(),
                status=QueryAuditStatus.REFUSED,
                metrics=GenerationMetrics(),
                generation_latency_ms=0,
                total_latency_ms=0,
                error_code="EMPTY",
            )

        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_logs

    @pytest.mark.asyncio
    async def test_record_safely_passes_through_on_success(self):
        """成功路径下,record_safely 和 record 行为一致——commit 必须被调用。"""
        service, repo, session = _build_service()

        await service.record_safely(
            snapshot=_build_snapshot(),
            status=QueryAuditStatus.COMPLETED,
            metrics=GenerationMetrics(),
            generation_latency_ms=1,
            total_latency_ms=2,
            error_code=None,
        )

        repo.save.assert_awaited_once()
        session.commit.assert_awaited_once()
