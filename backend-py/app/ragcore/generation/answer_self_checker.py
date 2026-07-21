"""生成后自检:对正文逐句核查是否有资料支撑,作为"两道闸"的第二道。

对应 Java 版 `ragcore/generation/AnswerSelfChecker.java`。**只靠 prompt 约束不够**(第一道
闸):模型偶尔会自信地越界,让同一个模型自查自己说服力有限。本类在生成结束后用独立于
生成模型的 `RerankerClient` 对正文逐句核查。

不带 `[资料N]` 标记的实质性句子(>=6 字符)直接判定为疑似未标注断言;带标记的句子把句
子本身当 query、标记对应的 citation snippet 当候选,调用 Reranker 打分,top1 final_score
低于 `MIN_RERANK_SCORE` 视为不被支撑。Reranker 异常或未配置时整体核查视为"无问题",
不影响已生成并展示给用户的正文 —— 这就是"两道闸"里第二道闸的 fail-open 语义,不能
因为"先出功能"删掉。

已知局限(与 Java 版同款,详见 `eval/reports/multi-passage-fusion-and-self-check-validation-20260716.md`):
Reranker 衡量的是语义相关性,不是严格的事实蕴含判断;复用检索阶段已校准的
`MIN_RERANK_SCORE` 只是起步值,不代表对这个新场景也最优。后续若要覆盖"部分相关的
编造"场景,需要专门阈值校准(Java 侧也尚未落地)。
"""

from __future__ import annotations

import logging
import re
import uuid

from app.ragcore.generation.self_check_result import SelfCheckResult
from app.ragcore.model import Chunk, Citation, RetrievedChunk
from app.ragcore.rerank.client import RerankerClient
from app.ragcore.rerank.thresholds import MIN_RERANK_SCORE

logger = logging.getLogger(__name__)

# 中文/全角标点 + 换行符作为句末分隔。Java 版 `SENTENCE_BOUNDARY` 同款 pattern。
# 使用 lookbehind 在句末标点后切分,切点零宽,正文原样保留。
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？\n])")

# 抽取 `[资料N]` 形式的引用编号,N 为 1 个以上数字。Java 版同款 pattern。
_CITATION_MARKER = re.compile(r"\[资料(\d+)]")

# 不带引用标记但长度达到这个阈值的句子视为"实质性断言",计入未支撑。Java 版同款常量。
_MIN_SUBSTANTIVE_SENTENCE_LENGTH = 6


class AnswerSelfChecker:
    """生成后自检器。`reranker_client` 为 None 表示自检直接跳过(未启用/未配置)。"""

    def __init__(self, reranker_client: RerankerClient | None) -> None:
        self._reranker = reranker_client

    @property
    def enabled(self) -> bool:
        """`reranker_client` 非空表示启用。与 `NliSelfCheckGate.enabled` 保持一致的语义。"""
        return self._reranker is not None

    async def check(self, answer_text: str | None, citations: list[Citation]) -> SelfCheckResult:
        """对生成正文逐句核查,返回 `SelfCheckResult`。

        Reranker 调用异常时整体 fail-open,返回 `SelfCheckResult.none()` —— 这是
        "不阻塞主问答流程"的核心保证,与 `NliSelfCheckGate` 同款降级模式。
        """
        if not answer_text or not answer_text.strip():
            return SelfCheckResult.none()
        if self._reranker is None:
            # 未启用自检:`unsupported_claims` 留空,与 Java 版"无问题"语义一致;
            # 调用方在结果为空时也不会触发 `SELF_CHECK_WARNING` 事件。
            return SelfCheckResult.none()

        unsupported: list[str] = []
        try:
            for raw_sentence in _SENTENCE_BOUNDARY.split(answer_text):
                sentence = raw_sentence.strip()
                if not sentence:
                    continue
                cited_indexes = _extract_citation_indexes(sentence)
                if not cited_indexes:
                    if len(sentence) >= _MIN_SUBSTANTIVE_SENTENCE_LENGTH:
                        unsupported.append(sentence + "（未标注引用来源）")
                    continue
                if not await self._is_supported_by_citations(sentence, cited_indexes, citations):
                    unsupported.append(sentence + "（标注了引用，但相关性较低）")
        except Exception as exc:  # noqa: BLE001 - fail-open:任何 Reranker 异常都不能拖垮主问答流程
            logger.warning("生成后自检调用 Reranker 失败,本轮跳过自检: %s", exc)
            return SelfCheckResult.none()
        return SelfCheckResult(tuple(unsupported))

    async def _is_supported_by_citations(
        self, sentence: str, cited_indexes: list[int], citations: list[Citation]
    ) -> bool:
        """带引用标记的句子,把这些 citation 转成 synthetic `RetrievedChunk` 后让 Reranker 打分。"""
        if self._reranker is None:
            # 入口处 `check()` 已经判过 None,这里是保险;helper 被外部直接调时也安全。
            return True
        candidates: list[RetrievedChunk] = []
        for index in cited_indexes:
            if index < 1 or index > len(citations):
                # 引用编号越界跳过,与 Java 版同款语义;全部越界时下方空列表分支兜底
                # 视为"无法判断"返回 True,避免对合法正文误伤。
                continue
            candidates.append(_synthetic_chunk(citations[index - 1]))
        if not candidates:
            return True
        # RerankerClient 在 Python 端是 async;Java 版 RerankerClient 是 sync,这里 await
        # 是把同步调用改成异步调用的关键差异。
        reranked = await self._reranker.rerank(sentence, candidates, len(candidates))
        if not reranked:
            return False
        top = reranked[0]
        if top.final_score is None:
            return False
        return top.final_score >= MIN_RERANK_SCORE


def _extract_citation_indexes(sentence: str) -> list[int]:
    """从单句里抽出所有 `[资料N]` 形式的引用编号(N>=1)。"""
    return [int(match.group(1)) for match in _CITATION_MARKER.finditer(sentence)]


def _synthetic_chunk(citation: Citation) -> RetrievedChunk:
    """把 citation 转成 Reranker 输入所需的 `RetrievedChunk`。

    与 Java 版 `syntheticChunk` 字段一一对应:citation snippet 当 chunk content,
    documentName 当 sourcePath(Java 版用 `citation.documentName()` 填 `source_path`,
    这里照搬这个用法——别处都是用真实 sourcePath,这是自检用的合成块,允许略有不同),
    其它定位信息原样复制。chunk id 用 `self-check-<document_id>` 前缀,与 Java 版同款,
    方便审计/调试时把自检用的合成 chunk 跟真实 chunk 区分开。
    """
    document_id = citation.document_id or uuid.uuid4()
    chunk = Chunk(
        id=f"self-check-{document_id}",
        organization_id=None,
        knowledge_base_id=None,
        document_id=document_id,
        ordinal=0,
        content=citation.snippet,
        heading_path=citation.heading_path,
        source_path=citation.document_name,
        page_no=citation.page_no,
        line_start=citation.line_start,
        line_end=citation.line_end,
        language="zh",
        content_hash="self-check",
    )
    return RetrievedChunk(chunk=chunk)
