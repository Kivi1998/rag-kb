#!/usr/bin/env python3
"""对 no-retrieval-fact-verification 的 `FactVerificationGate` 跑真实端到端回归验证：
真实检索（复用 `rag_chunks_eval_v3` 评测索引，不重建）+ 真实生成模型，统计
NO_RETRIEVAL 标注题的命中拒答比例，与抽样应答题的误伤比例。

移植自已删除的 `EvalFactVerificationRunner.java`。

用法（需要 RAG_EMBEDDING_*、RAG_RERANK_*、RAG_GENERATION_* 前缀的环境变量齐全，
且 `rag_chunks_eval_v3` 索引已由 `eval_retrieval_runner.py` 建好）：

    python3 eval/scripts/eval_fact_verification_runner.py \\
        [eval-set-v2.jsonl] [output.jsonl]

本工具是真实回归验证工具，环境变量缺失时直接报错退出，不做静默降级——这与
`eval_retrieval_runner.py`（embedding/rerank 缺失时降级为 BM25-only）刻意不同。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import _eval_common
from _eval_common import EVAL_INDEX_NAME, EVAL_KB_ID, EVAL_ORG_ID

TOP_K = 10
CANDIDATE_LIMIT = 50

# 150 题评估集里全部 8 道 NO_RETRIEVAL 标注题（见 eval/datasets/eval-set-v2.jsonl）。
NO_RETRIEVAL_IDS = frozenset(
    {"q-136", "q-137", "q-138", "q-139", "q-140", "q-141", "q-142", "q-143"}
)

# 应答题（expect_refusal=false）里按 stride=5 抽样的 25 道，覆盖 easy/medium/hard 且
# 分散在语料各章节，不用随机数以保证可复现：ids[::5]（125 道应答题里每隔 4 道取 1 道）。
ANSWERABLE_SAMPLE_IDS = frozenset(
    {
        "q-001", "q-006", "q-011", "q-016", "q-021", "q-026", "q-031", "q-036", "q-041", "q-046",
        "q-051", "q-056", "q-061", "q-066", "q-071", "q-076", "q-081", "q-086", "q-091", "q-096",
        "q-101", "q-106", "q-111", "q-116", "q-121",
    }
)


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value or not value.strip():
        raise SystemExit(f"缺少环境变量 {key}，本工具需要真实 embedding/rerank/生成服务，不做降级")
    return value


def _build_embedding_client():
    from app.ragcore.embedding.openai_compatible import EmbeddingProperties, OpenAiCompatibleEmbeddingClient

    endpoint = _require_env("RAG_EMBEDDING_ENDPOINT")
    props = EmbeddingProperties(
        enabled=True,
        endpoint=endpoint,
        api_key=os.environ.get("RAG_EMBEDDING_API_KEY") or "",
        model=_require_env("RAG_EMBEDDING_MODEL"),
        timeout_ms=60_000,
    )
    return OpenAiCompatibleEmbeddingClient(props)


def _build_reranker():
    from app.ragcore.rerank.openai_compatible import OpenAiCompatibleRerankerClient, RerankProperties

    endpoint = _require_env("RAG_RERANK_ENDPOINT")
    props = RerankProperties(
        enabled=True,
        endpoint=endpoint,
        api_key=os.environ.get("RAG_RERANK_API_KEY") or "",
        model=_require_env("RAG_RERANK_MODEL"),
        timeout_ms=60_000,
    )
    return OpenAiCompatibleRerankerClient(props)


def _build_generator(assembler):
    from app.ragcore.generation.openai_compatible_answer_generator import (
        GenerationProperties,
        OpenAiCompatibleAnswerGenerator,
    )

    endpoint = _require_env("RAG_GENERATION_ENDPOINT")
    props = GenerationProperties(
        enabled=True,
        endpoint=endpoint,
        api_key=os.environ.get("RAG_GENERATION_API_KEY") or "",
        model=_require_env("RAG_GENERATION_MODEL"),
        timeout_ms=60_000,
    )
    return OpenAiCompatibleAnswerGenerator(props, assembler)


async def _run(eval_set: Path, output: Path) -> None:
    from app.core.es_client import get_es_client
    from app.ragcore.generation.fact_verification_gate import FactVerificationGate
    from app.ragcore.generation.metrics import GenerationMetrics
    from app.ragcore.generation.prompt_assembler import PromptAssembler
    from app.ragcore.retrieval.es_chunk_hydrator import ElasticsearchChunkHydrator
    from app.ragcore.retrieval.es_lexical_candidate_source import ElasticsearchLexicalCandidateSource
    from app.ragcore.retrieval.es_vector_candidate_source import ElasticsearchVectorCandidateSource
    from app.ragcore.retrieval.hybrid_retriever import HybridRetriever
    from app.ragcore.retrieval.retrieval_options import RetrievalOptions

    es = get_es_client()

    embedding_client = _build_embedding_client()
    reranker = _build_reranker()
    prompt_assembler = PromptAssembler()
    generator = _build_generator(prompt_assembler)

    lexical = ElasticsearchLexicalCandidateSource(es, index_name=EVAL_INDEX_NAME)
    vector_source = ElasticsearchVectorCandidateSource(es, index_name=EVAL_INDEX_NAME)
    hydrator = ElasticsearchChunkHydrator(es, index_name=EVAL_INDEX_NAME)
    retriever = HybridRetriever(
        lexical_source=lexical,
        vector_source=vector_source,
        chunk_hydrator=hydrator,
        embedding_client=embedding_client,
        reranker_provider=reranker,
    )
    options = RetrievalOptions(candidate_limit=CANDIDATE_LIMIT, result_limit=TOP_K, rerank=True)

    results: list[dict] = []
    no_retrieval_hits = 0
    answerable_false_refusals = 0
    answerable_retrieval_refused = 0

    with eval_set.open("r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]

    for line in lines:
        q = json.loads(line)
        qid = q.get("id", "")
        is_no_retrieval = qid in NO_RETRIEVAL_IDS
        is_answerable_sample = qid in ANSWERABLE_SAMPLE_IDS
        if not is_no_retrieval and not is_answerable_sample:
            continue
        question = q.get("question", "")

        started = time.perf_counter()
        retrieval = await retriever.retrieve_with_decision(EVAL_ORG_ID, EVAL_KB_ID, question, options)
        fact_verification_refused = False
        answer_snippet = ""
        if not retrieval.refused:
            metrics = GenerationMetrics()
            gate = FactVerificationGate([])
            answer_parts: list[str] = []
            async for event in generator.stream_with_metrics(question, retrieval.chunks, metrics):
                for out_event in gate.feed(event):
                    if out_event.content is not None:
                        answer_parts.append(out_event.content)
            for out_event in gate.flush():
                if out_event.content is not None:
                    answer_parts.append(out_event.content)
            fact_verification_refused = gate.refused_by_fact_verification
            answer = "".join(answer_parts)
            answer_snippet = answer[:80] + "…" if len(answer) > 80 else answer
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))

        if is_no_retrieval and fact_verification_refused:
            no_retrieval_hits += 1
        if is_answerable_sample:
            if retrieval.refused:
                answerable_retrieval_refused += 1
            elif fact_verification_refused:
                answerable_false_refusals += 1

        record = {
            "id": qid,
            "category": "no_retrieval_labeled" if is_no_retrieval else "answerable_sample",
            "question": question,
            "retrieval_refused": retrieval.refused,
            "fact_verification_refused": fact_verification_refused,
            "answer_snippet": answer_snippet,
            "latency_ms": elapsed_ms,
        }
        results.append(record)
        tag = "NO_RETRIEVAL" if is_no_retrieval else "answerable"
        print(
            f"[{qid}] {tag} retrieval_refused={retrieval.refused} "
            f"fact_verification_refused={fact_verification_refused} ({elapsed_ms}ms)"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + ("\n" if results else ""),
        encoding="utf-8",
    )

    no_retrieval_total = len(NO_RETRIEVAL_IDS)
    answerable_total = len(ANSWERABLE_SAMPLE_IDS)
    print()
    print(f"[summary] NO_RETRIEVAL 命中拒答 {no_retrieval_hits}/{no_retrieval_total}（生成阶段事实核验）")
    print(
        f"[summary] 抽样应答题 {answerable_total} 道："
        f"检索阶段已拒答 {answerable_retrieval_refused}（不计入本机制误伤，属既有阈值行为）、"
        f"事实核验误伤 {answerable_false_refusals}"
    )
    print(f"[done] 结果写入 {output}")

    await embedding_client.aclose()
    await reranker.aclose()
    await generator.aclose()
    await es.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对 FactVerificationGate 跑真实端到端回归验证")
    parser.add_argument(
        "eval_set",
        nargs="?",
        default=str(_eval_common.REPO_ROOT / "eval/datasets/eval-set-v2.jsonl"),
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=str(
            _eval_common.REPO_ROOT / f"eval/predictions/no-retrieval-fact-verification-{date.today()}.jsonl"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    eval_set = Path(args.eval_set).resolve()
    output = Path(args.output).resolve()

    if not eval_set.is_file():
        print(f"eval-set 不存在: {eval_set}", file=sys.stderr)
        return 2

    _eval_common.bootstrap_backend_py()
    asyncio.run(_run(eval_set, output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
