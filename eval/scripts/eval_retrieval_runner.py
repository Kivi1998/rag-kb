#!/usr/bin/env python3
"""用产品真实检索代码对评估集跑检索，输出 predicted JSONL。

移植自已删除的 `EvalRetrievalRunner.java`。复用生产类：
`ElasticsearchChunkIndex`（入库）+ `ElasticsearchLexicalCandidateSource` /
`ElasticsearchVectorCandidateSource` / `ElasticsearchChunkHydrator` + `HybridRetriever`
（检索——三端口独立组装是当前 backend-py 生产装配方式，见
`app/routers/_factories.py::build_hybrid_retriever()`；遗留合一实现
`ElasticsearchHybridCandidateSource` 已在其模块 docstring 里注明"仅供评测脚本与
存量测试复用"，但三端口写法与生产环境完全一致，本脚本采用这种写法）。

数据源是 `eval_corpus_indexer.py` dump 的 corpus-index.jsonl（V3 真实切块产物），
chunk_id 与评估集 ground_truth 完全一致，无需映射。

**Embedding 说明**：评测环境 embedding 不可达（`RAG_EMBEDDING_ENDPOINT` /
`RAG_EMBEDDING_MODEL` 环境变量缺失）时，本工具向 ES 写入占位单位向量（仅为通过
索引层的维度校验），并给 HybridRetriever 注入一个必然抛 `ModelClientException` 的
EmbeddingClient——这会触发产品内建的 BM25-only 降级路径（与生产中 embedding 短暂
不可用的行为一致）。因此本工具产出的指标在该情况下只是「V3 切分 + BM25 单路召回」
的真实值，不包含 kNN 向量召回与 Rerank 的贡献。

用法（可在任意目录下执行）：

    python3 eval/scripts/eval_retrieval_runner.py \\
        [corpus-index.jsonl] [eval-set.jsonl] [output.jsonl] \\
        [candidateLimit=50] [skipIndex=false]

第 4/5 个参数用于候选池大小（N）调优实验：candidateLimit 覆盖 RRF 两路各自的召回
条数；skipIndex=true 时跳过重建评测索引（仅 candidateLimit 变化、语料不变时可复用
已有索引，省掉重复 embedding 入库的时间与调用成本）。每题检索延迟会写入
`<output>.latency.json`（mean/median/p95，单位毫秒）。

依赖真实 ES（`RAG_ES_ENDPOINT`，默认 http://127.0.0.1:9200）；embedding/rerank
（`RAG_EMBEDDING_*`/`RAG_RERANK_*`）未配置时自动降级为 BM25-only，不报错。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path

import _eval_common
from _eval_common import EVAL_INDEX_NAME, EVAL_KB_ID, EVAL_ORG_ID, EVAL_VECTOR_DIMS

TOP_K = 10
_INDEX_BATCH_SIZE = 32


class _AlwaysFailEmbeddingClient:
    """query embedding 客户端桩：embedding 未配置时注入，必然抛 ModelClientException，
    触发 HybridRetriever 内建的 BM25-only 降级路径。对应 Java 版的匿名 lambda。
    """

    async def embed(self, texts: list[str]):  # noqa: ANN001 - 延迟 import 后才知道具体类型
        from app.ragcore.model import ModelClientException

        raise ModelClientException("评测环境 embedding 服务不可达（走 BM25-only 降级）")


def _placeholder_vector() -> list[float]:
    """占位向量：仅为通过索引层维度校验；BM25 查询路径不读取该字段。"""
    return [1.0] + [0.0] * (EVAL_VECTOR_DIMS - 1)


def _build_embedding_client():
    """从 RAG_EMBEDDING_* 环境变量构造真实 embedding 客户端；配置不全返回 None（BM25-only）。

    直接读环境变量、手动构造 EmbeddingProperties，而不是走
    `app.ragcore.embedding.openai_compatible.build_embedding_client(settings)` 工厂——
    后者受 `RAG_EMBEDDING_ENABLED` 总开关门控；本工具与 Java 版一致，只要 endpoint/model
    两个环境变量存在就直接启用，不受全局 enabled 开关影响。
    """
    from app.ragcore.embedding.openai_compatible import EmbeddingProperties, OpenAiCompatibleEmbeddingClient

    endpoint = os.environ.get("RAG_EMBEDDING_ENDPOINT")
    model = os.environ.get("RAG_EMBEDDING_MODEL")
    if not endpoint or not endpoint.strip() or not model or not model.strip():
        return None
    props = EmbeddingProperties(
        enabled=True,
        endpoint=endpoint,
        api_key=os.environ.get("RAG_EMBEDDING_API_KEY") or "",
        model=model,
        timeout_ms=60_000,
    )
    return OpenAiCompatibleEmbeddingClient(props)


def _build_reranker():
    """从 RAG_RERANK_* 环境变量构造真实 rerank 客户端；配置不全返回 None（跳过重排）。"""
    from app.ragcore.rerank.openai_compatible import OpenAiCompatibleRerankerClient, RerankProperties

    endpoint = os.environ.get("RAG_RERANK_ENDPOINT")
    model = os.environ.get("RAG_RERANK_MODEL")
    if not endpoint or not endpoint.strip() or not model or not model.strip():
        return None
    props = RerankProperties(
        enabled=True,
        endpoint=endpoint,
        api_key=os.environ.get("RAG_RERANK_API_KEY") or "",
        model=model,
        timeout_ms=60_000,
    )
    return OpenAiCompatibleRerankerClient(props)


def _load_chunks(corpus_index: Path) -> list:
    """把 corpus-index.jsonl 逐行解析为生产 `app.ragcore.model.Chunk`。"""
    from app.ragcore.model import Chunk

    chunks: list[Chunk] = []
    with corpus_index.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            n = json.loads(line)
            metadata = {str(k): str(v) for k, v in (n.get("metadata") or {}).items()}
            heading_path = [str(h) for h in (n.get("heading_path") or [])]
            language = n.get("language")
            if language is None:
                language = "zh"
            chunks.append(
                Chunk(
                    id=n["chunk_id"],
                    organization_id=EVAL_ORG_ID,
                    knowledge_base_id=EVAL_KB_ID,
                    document_id=uuid.UUID(n["document_id"]),
                    ordinal=int(n["ordinal"]),
                    content=n["content"],
                    heading_path=heading_path,
                    source_path=n["document_name"],
                    page_no=n.get("page_no"),
                    line_start=n.get("line_start"),
                    line_end=n.get("line_end"),
                    language=language,
                    content_hash=n["content_hash"],
                    metadata=metadata,
                )
            )
    return chunks


def _write_latency_summary(output: Path, candidate_limit: int, latencies_ms: list[int]) -> None:
    sorted_ms = sorted(latencies_ms)
    n = len(sorted_ms)
    mean = sum(sorted_ms) / n if n else 0.0
    median = sorted_ms[n // 2] if n else 0
    p95_idx = min(n - 1, math.ceil(n * 0.95) - 1) if n else 0
    p95 = sorted_ms[p95_idx] if n else 0
    summary = {
        "candidateLimit": candidate_limit,
        "n": n,
        "meanMs": round(mean),
        "medianMs": median,
        "p95Ms": p95,
        "minMs": sorted_ms[0] if n else 0,
        "maxMs": sorted_ms[-1] if n else 0,
    }
    latency_path = Path(str(output) + ".latency.json")
    latency_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[latency] mean={round(mean)}ms median={median}ms p95={p95}ms → {latency_path}")


async def _run(
    corpus_index: Path,
    eval_set: Path,
    output: Path,
    candidate_limit: int,
    skip_index: bool,
) -> None:
    from elasticsearch import NotFoundError

    from app.core.es_client import get_es_client
    from app.ragcore.index.es_chunk_index import ElasticsearchChunkIndex
    from app.ragcore.retrieval.es_chunk_hydrator import ElasticsearchChunkHydrator
    from app.ragcore.retrieval.es_lexical_candidate_source import ElasticsearchLexicalCandidateSource
    from app.ragcore.retrieval.es_vector_candidate_source import ElasticsearchVectorCandidateSource
    from app.ragcore.retrieval.hybrid_retriever import HybridRetriever
    from app.ragcore.retrieval.retrieval_options import RetrievalOptions

    es = get_es_client()

    # ── 1. 组装模型客户端：环境变量配置齐 → 完整混合检索；否则 BM25-only 降级 ──
    embedding_client = _build_embedding_client()
    reranker = _build_reranker()
    hybrid = embedding_client is not None
    if hybrid:
        mode_desc = "完整混合检索（真实 embedding" + (" + rerank）" if reranker is not None else "，无 rerank）")
    else:
        mode_desc = "BM25-only（embedding 未配置/不可达）"
    print(f"[mode] {mode_desc} candidateLimit={candidate_limit} skipIndex={skip_index}")

    # ── 2. 重建独立评测索引（不触碰生产 rag_chunks_v1）──
    if skip_index:
        print(f"[index] 跳过重建，复用已有索引 {EVAL_INDEX_NAME}")
    else:
        try:
            await es.indices.delete(index=EVAL_INDEX_NAME)
            print(f"[index] 已删除旧评测索引 {EVAL_INDEX_NAME}")
        except NotFoundError:
            pass

        chunks = _load_chunks(corpus_index)
        print(f"[index] 读取 corpus-index：{len(chunks)} chunks")
        chunk_index = ElasticsearchChunkIndex(es, index_name=EVAL_INDEX_NAME, vector_dimensions=EVAL_VECTOR_DIMS)
        for i in range(0, len(chunks), _INDEX_BATCH_SIZE):
            sl = chunks[i : i + _INDEX_BATCH_SIZE]
            if hybrid:
                result = await embedding_client.embed([c.content for c in sl])
                vectors = [list(v) for v in result.vectors]
                model_version = result.model_version
            else:
                vectors = [_placeholder_vector() for _ in sl]
                model_version = "eval-placeholder(BM25-only)"
            await chunk_index.upsert(sl, vectors, model_version)
            print(f"[index] 已入库 {min(i + _INDEX_BATCH_SIZE, len(chunks))}/{len(chunks)}")
        await es.indices.refresh(index=EVAL_INDEX_NAME)
        print(f"[index] 已写入并 refresh 索引 {EVAL_INDEX_NAME}")

    # ── 3. 组装产品检索链（词法 + 向量 + chunk hydrator 三端口，与生产装配一致）──
    lexical = ElasticsearchLexicalCandidateSource(es, index_name=EVAL_INDEX_NAME)
    vector_source = ElasticsearchVectorCandidateSource(es, index_name=EVAL_INDEX_NAME, vector_dimensions=EVAL_VECTOR_DIMS)
    hydrator = ElasticsearchChunkHydrator(es, index_name=EVAL_INDEX_NAME)
    query_embedding_client = embedding_client if hybrid else _AlwaysFailEmbeddingClient()
    retriever = HybridRetriever(
        lexical_source=lexical,
        vector_source=vector_source,
        chunk_hydrator=hydrator,
        embedding_client=query_embedding_client,
        reranker_provider=reranker,
    )
    options = RetrievalOptions(candidate_limit=candidate_limit, result_limit=TOP_K, rerank=reranker is not None)

    # ── 4. 逐题检索（记录每题延迟）──
    with eval_set.open("r", encoding="utf-8") as f:
        eval_lines = [ln.strip() for ln in f if ln.strip()]

    out_lines: list[str] = []
    latencies_ms: list[int] = []
    refusals = 0
    for line in eval_lines:
        q = json.loads(line)
        qid = q.get("id", "")
        question = q.get("question", "")
        expect_refusal = bool(q.get("expect_refusal", False))

        started = time.perf_counter()
        result = await retriever.retrieve_with_decision(EVAL_ORG_ID, EVAL_KB_ID, question, options)
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))
        latencies_ms.append(elapsed_ms)

        prediction: dict = {"id": qid}
        if result.refused:
            refusals += 1
            prediction["predicted_chunk_ids"] = []
            prediction["predicted_refusal"] = True
            prediction["predicted_refusal_reason"] = "NO_RETRIEVAL"
        else:
            prediction["predicted_chunk_ids"] = [rc.chunk.id for rc in result.chunks]
            prediction["predicted_refusal"] = False
            prediction["predicted_refusal_reason"] = None
            # 诊断字段（schema 未知字段，eval.runner 会忽略）：供拒答阈值校准使用。
            top = result.chunks[0]
            if top.final_score is not None:
                prediction["_top_rerank_score"] = top.final_score
            if top.rrf_score is not None:
                prediction["_top_rrf_score"] = top.rrf_score
        prediction["reranked"] = bool(hybrid and reranker is not None)
        prediction["_latency_ms"] = elapsed_ms
        out_lines.append(json.dumps(prediction, ensure_ascii=False))

        status = f"拒答({result.refusal_reason})" if result.refused else f"{len(result.chunks)} chunks"
        print(f"[query] {qid}{' [应拒答]' if expect_refusal else ''} → {status} ({elapsed_ms}ms)")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
    print(f"[done] {len(out_lines)} 条预测（其中拒答 {refusals}）→ {output}")

    _write_latency_summary(output, candidate_limit, latencies_ms)

    # 收尾：关闭各自持有的 httpx/ES 客户端，避免 "unclosed client session" 警告。
    if embedding_client is not None:
        await embedding_client.aclose()
    if reranker is not None:
        await reranker.aclose()
    await es.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用产品真实检索代码对评估集跑检索，输出 predicted JSONL")
    parser.add_argument(
        "corpus_index",
        nargs="?",
        default=str(_eval_common.REPO_ROOT / "eval/datasets/corpus-index.jsonl"),
    )
    parser.add_argument(
        "eval_set",
        nargs="?",
        default=str(_eval_common.REPO_ROOT / "eval/datasets/eval-set-2026Q3.jsonl"),
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=str(_eval_common.REPO_ROOT / "eval/predictions/predicted-v3-bm25.jsonl"),
    )
    parser.add_argument("candidate_limit", nargs="?", type=int, default=50)
    parser.add_argument("skip_index", nargs="?", default="false")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    corpus_index = Path(args.corpus_index).resolve()
    eval_set = Path(args.eval_set).resolve()
    output = Path(args.output).resolve()
    candidate_limit = args.candidate_limit
    skip_index = _eval_common.parse_bool(str(args.skip_index))

    if not corpus_index.is_file():
        print(f"corpus-index 不存在: {corpus_index}", file=sys.stderr)
        return 2
    if not eval_set.is_file():
        print(f"eval-set 不存在: {eval_set}", file=sys.stderr)
        return 2

    _eval_common.bootstrap_backend_py()
    asyncio.run(_run(corpus_index, eval_set, output, candidate_limit, skip_index))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
