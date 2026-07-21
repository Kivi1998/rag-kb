#!/usr/bin/env python3
"""对 `AnswerSelfChecker` 跑真实回归验证：no-retrieval-fact-verification 的做法是用人工
标注的真实问题，本次没有先例数据集，改用从真实语料（rag_chunks_eval_v3 索引对应的
"本科毕设"语料）里摘取的 3 段真实资料原文，人工构造"准确复述"与"标了引用但内容
对不上"的句子各 3 条，跑真实硅基流动 Reranker 打分，统计命中率/误伤率。

移植自已删除的 `EvalAnswerSelfCheckerRunner.java`。测试语料、用例列表、期望值均为
真实构造的回归测试数据，原样照抄，不改写内容。

用法（需要 RAG_RERANK_* 环境变量）：

    python3 eval/scripts/eval_answer_self_checker_runner.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import uuid
from dataclasses import dataclass

import _eval_common

_CITATION_MARKER = re.compile(r"\[资料(\d+)]")


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value or not value.strip():
        raise SystemExit(f"缺少环境变量 {key}，本工具需要真实 Reranker 服务，不做降级")
    return value


@dataclass(frozen=True)
class _Case:
    label: str
    sentence: str
    expect_flagged: bool


async def _raw_support_score(reranker, sentence: str, citations: list) -> float | None:
    """诊断用：直接调用 Reranker 拿到句子与其引用的全部资料之间的原始分数，供分析误判原因。"""
    from app.ragcore.model import Chunk, RetrievedChunk

    candidates: list = []
    for match in _CITATION_MARKER.finditer(sentence):
        index = int(match.group(1))
        if index < 1 or index > len(citations):
            continue
        citation = citations[index - 1]
        chunk = Chunk(
            id=f"diag-{citation.document_id}",
            organization_id=None,
            knowledge_base_id=None,
            document_id=citation.document_id,
            ordinal=0,
            content=citation.snippet,
            heading_path=citation.heading_path,
            source_path=citation.document_name,
            page_no=citation.page_no,
            line_start=citation.line_start,
            line_end=citation.line_end,
            language="zh",
            content_hash="diag",
            metadata={},
        )
        candidates.append(RetrievedChunk(chunk=chunk))
    if not candidates:
        return None
    reranked = await reranker.rerank(sentence, candidates, len(candidates))
    if not reranked:
        return None
    return reranked[0].final_score


async def _run() -> None:
    from app.ragcore.generation.answer_self_checker import AnswerSelfChecker
    from app.ragcore.model import Citation
    from app.ragcore.rerank.openai_compatible import OpenAiCompatibleRerankerClient, RerankProperties

    endpoint = _require_env("RAG_RERANK_ENDPOINT")
    props = RerankProperties(
        enabled=True,
        endpoint=endpoint,
        api_key=os.environ.get("RAG_RERANK_API_KEY") or "",
        model=_require_env("RAG_RERANK_MODEL"),
        timeout_ms=60_000,
    )
    reranker = OpenAiCompatibleRerankerClient(props)
    checker = AnswerSelfChecker(reranker)

    def citation(snippet: str) -> Citation:
        return Citation(
            document_id=uuid.uuid4(),
            document_name="2020届本科生毕业设计.docx",
            heading_path=(),
            snippet=snippet,
            page_no=None,
            line_start=None,
            line_end=None,
            score=None,
        )

    # 三段真实资料原文（来自 rag_chunks_eval_v3 索引，"中国地质大学（北京）2020届本科生
    # 毕业设计"语料）。原样照抄，不改写内容。
    svd_definition = citation(
        "其中，U是m×m阶酉矩阵；Σ是半正定m×n阶对角矩阵；而V*，即V的共轭转置，是n×n阶酉矩阵。"
        "这样的分解就称作M的奇异值分解。Σ对角线上的元素Σi为M的奇异值，通常奇异值由大而小排列。"
    )
    chen_sacchi = citation(
        "Chen和Sacchi（2014）认为奇异值分解（SVD）这种矩阵分解技术是非稳健的，当地震数据中混有"
        "不符合高斯分布的异常值噪声时，SVD无法有效压制不稳定的异常值噪声，于是提出了一种基于随机QR分解的稳健"
        "奇异谱分析方法，以在有效压制随机噪声的同时压制不稳定的异常值噪声。"
    )
    rpca_norms = citation(
        "为使问题可解，我们使用由矩阵S中所有元素绝对值之和定义的L1范数来代替L0范数。同时，我们"
        "考虑用L的核范数代替低秩约束，其中L的核模定义为矩阵L的所有非零奇异值的和。可以证明L1范数是L0范数"
        "最严格的凸松弛（Donoho，2006）。同理，核范数是对低秩约束的紧凸松弛（Fazel，2002）。"
    )
    citations = [svd_definition, chen_sacchi, rpca_norms]

    # 3 条准确复述（预期不拒答）+ 3 条标了引用但内容对不上的句子（预期被标记）。原样照抄。
    cases = [
        _Case(
            "supported-1(SVD定义)",
            "奇异值分解把矩阵M分解成U、Σ和V三个矩阵，U和V均为酉矩阵，Σ为对角矩阵[资料1]。",
            False,
        ),
        _Case(
            "unsupported-1(SVD定义@硬件环境)",
            "这次奇异值分解计算在配备32GB内存的服务器上完成[资料1]。",
            True,
        ),
        _Case(
            "supported-2(Chen-Sacchi)",
            "Chen和Sacchi在2014年指出SVD对不符合高斯分布的异常值噪声处理并不稳健[资料2]。",
            False,
        ),
        _Case(
            "unsupported-2(Chen-Sacchi@RPCA范数,张冠李戴)",
            "该方法用L1范数约束异常值噪声，用核范数约束低秩数据[资料2]。",
            True,
        ),
        _Case(
            "supported-3(RPCA范数)",
            "该方法用L1范数代替L0范数、用核范数代替低秩约束，因为核范数是低秩约束的凸松弛[资料3]。",
            False,
        ),
        _Case(
            "unsupported-3(RPCA范数@迭代耗时)",
            "本文RPCA迭代1500次后收敛，耗时约10分钟[资料3]。",
            True,
        ),
    ]

    correct = 0
    print("[case] label | expectFlagged | actualFlagged | rawScore | 判定详情")
    for c in cases:
        result = await checker.check(c.sentence, citations)
        actual_flagged = result.has_unsupported_claims
        hit = actual_flagged == c.expect_flagged
        if hit:
            correct += 1
        raw_score = await _raw_support_score(reranker, c.sentence, citations)
        print(
            f"[{'OK' if hit else 'MISS'}] {c.label} | expect={c.expect_flagged} "
            f"actual={actual_flagged} | rawScore={raw_score} | {list(result.unsupported_claims)}"
        )

    print()
    print(f"[summary] {correct}/{len(cases)} 命中预期")

    await reranker.aclose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对 AnswerSelfChecker 跑真实回归验证（无 CLI 参数）")
    return parser.parse_args()


def main() -> int:
    _parse_args()
    _eval_common.bootstrap_backend_py()
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
