"""`ElasticsearchVisibilityBackfill` 存量 `retrieval_ready` 回填测试。

对应 Java 版 `ragcore/index/ElasticsearchVisibilityBackfill.java`。
为迁移前写入 `rag_chunks_v1` 的存量 Chunk 回填 `retrieval_ready=true`,缺字段的
Chunk 视为已发布(dry_run 模式只统计不写)。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.ragcore.index.elasticsearch_visibility_backfill import (
    BackfillResult,
    ElasticsearchVisibilityBackfill,
)
from app.ragcore.index.exceptions import ElasticsearchIndexException


class _FakeESClient:
    def __init__(self) -> None:
        self.count_responses: list[dict] = []
        self.put_mapping_calls: list[dict] = 0
        self.update_by_query_responses: list[dict] = []
        self.queries_seen: list[dict] = []
        self.update_call_count = 0
        # 模拟 es.indices.put_mapping 的链式属性
        self.indices = self._Indices(self)

    class _Indices:
        def __init__(self, parent: "_FakeESClient") -> None:
            self._parent = parent

        async def put_mapping(self, *, index: str, properties: dict) -> None:
            self._parent.put_mapping_calls += 1

    async def count(self, *, index: str, query: dict) -> dict:
        self.queries_seen.append(query)
        if self.count_responses:
            return self.count_responses.pop(0)
        return {"count": 0}

    async def update_by_query(self, **kwargs) -> dict:
        self.queries_seen.append(kwargs.get("query"))
        self.update_call_count += 1
        if self.update_by_query_responses:
            return self.update_by_query_responses.pop(0)
        return {"updated": 0, "failures": []}


def _settings() -> Settings:
    return Settings(rag_es_index_name="rag_chunks_v1")


class TestParameterValidation:
    @pytest.mark.asyncio
    async def test_zero_batch_size_rejected(self):
        es = _FakeESClient()
        backfill = ElasticsearchVisibilityBackfill(es_client=es, cfg=_settings())
        with pytest.raises(ValueError):
            await backfill.run(dry_run=True, batch_size=0, max_attempts=3)

    @pytest.mark.asyncio
    async def test_zero_max_attempts_rejected(self):
        es = _FakeESClient()
        backfill = ElasticsearchVisibilityBackfill(es_client=es, cfg=_settings())
        with pytest.raises(ValueError):
            await backfill.run(dry_run=True, batch_size=100, max_attempts=0)


class TestDryRun:
    """dry_run=True 时只统计缺失字段,不做任何写入。"""

    @pytest.mark.asyncio
    async def test_dry_run_only_counts_no_writes(self):
        es = _FakeESClient()
        es.count_responses = [{"count": 1234}]
        backfill = ElasticsearchVisibilityBackfill(es_client=es, cfg=_settings())

        result = await backfill.run(dry_run=True, batch_size=100, max_attempts=3)
        assert result.dry_run is True
        assert result.missing_before == 1234
        assert result.updated == 0
        assert result.missing_after == 1234  # dry_run 不变
        # 没触发 put_mapping / update_by_query
        assert es.put_mapping_calls == 0
        assert es.update_call_count == 0

    @pytest.mark.asyncio
    async def test_dry_run_no_missing_returns_zero(self):
        es = _FakeESClient()
        es.count_responses = [{"count": 0}]
        backfill = ElasticsearchVisibilityBackfill(es_client=es, cfg=_settings())
        result = await backfill.run(dry_run=True, batch_size=100, max_attempts=3)
        assert result.missing_before == 0
        assert result.updated == 0


class TestNormalRun:
    @pytest.mark.asyncio
    async def test_normal_run_writes_retrieval_ready_true(self):
        es = _FakeESClient()
        es.count_responses = [
            {"count": 500},  # 第一次 count:有 500 个缺失
            {"count": 0},  # 第二次 count:回填后为 0
        ]
        es.update_by_query_responses = [{"updated": 500, "failures": []}]
        backfill = ElasticsearchVisibilityBackfill(es_client=es, cfg=_settings())

        result = await backfill.run(dry_run=False, batch_size=200, max_attempts=3)
        assert result.dry_run is False
        assert result.missing_before == 500
        assert result.updated == 500
        assert result.missing_after == 0
        assert es.put_mapping_calls == 1
        assert es.update_call_count == 1

    @pytest.mark.asyncio
    async def test_no_missing_no_write_even_in_normal_mode(self):
        """missing_before=0 时直接返回,不打 update_by_query。"""
        es = _FakeESClient()
        es.count_responses = [{"count": 0}]
        backfill = ElasticsearchVisibilityBackfill(es_client=es, cfg=_settings())
        result = await backfill.run(dry_run=False, batch_size=200, max_attempts=3)
        assert result.missing_before == 0
        assert result.updated == 0
        assert es.update_call_count == 0

    @pytest.mark.asyncio
    async def test_update_by_query_failures_raises(self):
        """update_by_query 报告存在分项失败时,回填必须 fail-fast 抛错,
        不能把"看起来成功了但实际没填上"的结果吞掉。"""
        es = _FakeESClient()
        es.count_responses = [{"count": 10}, {"count": 5}]
        es.update_by_query_responses = [{
            "updated": 8, "failures": [{"index": "rag_chunks_v1", "reason": "version_conflict"}]
        }]
        backfill = ElasticsearchVisibilityBackfill(es_client=es, cfg=_settings())
        with pytest.raises(ElasticsearchIndexException):
            await backfill.run(dry_run=False, batch_size=10, max_attempts=1)


class TestRetry:
    @pytest.mark.asyncio
    async def test_retries_update_by_query_then_succeeds(self):
        """ES update_by_query 偶发失败时按 max_attempts 退避重试,重试耗尽才抛错。"""
        es = _FakeESClient()
        es.count_responses = [{"count": 10}, {"count": 0}]
        es.update_by_query_responses = [{"updated": 10, "failures": []}]

        # 让前两次 update_by_query 抛 RuntimeError
        original = es.update_by_query
        attempts = {"n": 0}

        async def flaky_update_by_query(**kwargs):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("ES connection blip")
            return await original(**kwargs)

        es.update_by_query = flaky_update_by_query
        backfill = ElasticsearchVisibilityBackfill(es_client=es, cfg=_settings())
        result = await backfill.run(dry_run=False, batch_size=10, max_attempts=5)
        assert result.updated == 10
        assert attempts["n"] == 3  # 失败 2 次,第三次成功

    @pytest.mark.asyncio
    async def test_max_attempts_exhausted_raises(self):
        es = _FakeESClient()
        es.count_responses = [{"count": 5}]

        async def always_fail(**kwargs):
            raise RuntimeError("permanent failure")

        es.update_by_query = always_fail
        backfill = ElasticsearchVisibilityBackfill(es_client=es, cfg=_settings())
        with pytest.raises(ElasticsearchIndexException):
            await backfill.run(dry_run=False, batch_size=10, max_attempts=2)

    @pytest.mark.asyncio
    async def test_count_failure_wrapped(self):
        es = _FakeESClient()

        async def fail_count(*, index, query):
            raise RuntimeError("count failed")

        es.count = fail_count
        backfill = ElasticsearchVisibilityBackfill(es_client=es, cfg=_settings())
        with pytest.raises(ElasticsearchIndexException):
            await backfill.run(dry_run=True, batch_size=10, max_attempts=1)
