"""Rerank 相关性分数拒答门槛，评估集校准得出，禁止随意改动数值。

对应 Java 版 `ragcore/retrieval/HybridRetriever.java` 中的 `MIN_RERANK_SCORE` 常量
（该常量定义在 retrieval 包而非 rerank 包——检索编排层 `HybridRetriever` 尚未移植到
Python，本次只搬运 embedding/rerank/generation/nli 四个客户端模块。这里把校准数值提前
落到 rerank 模块，供 `generation.self_checker` 复用，也供未来移植 retrieval 模块时直接
import，避免像 Java 版那样在两处各写一份容易漂移的字面量 0.06）。

校准依据：2026-07-14 用 150 题人工标注评估集（eval-set-v2）+ bge-reranker-v2-m3 做的分数
分布分析（`eval/scripts/analyze_refusal_threshold.py`）。0.06 是该数据集上拒答 F1 最优点
（F1=0.564，命中 11/25，仅误伤 3/125 可回答题）。详见 `docs/评估指南.md`、
`eval/reports/refusal-threshold-calibration-20260714.md`。

已知局限（勿指望此门槛覆盖所有拒答场景）：rerank 分数衡量的是「主题相关性」而非「事实是否
存在」，对 NO_RETRIEVAL 类（主题高度相关但具体数值/事实缺失）与 SAFETY 类（内容确实可检索
到，但因合规/安全原因应拒答）几乎无区分力，需要独立机制（事实核验、内容安全分类器）解决。

**不得修改此数值**：这是拿评估集调出来的校准结果，改动会让已发布的评测结论失真。
"""

MIN_RERANK_SCORE: float = 0.06
