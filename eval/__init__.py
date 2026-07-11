"""自研 RAG 离线评测框架 —— v0（T301）。

设计目标（任务清单 §7 T301）：
- JSONL 评测格式
- 至少 50 个脱敏技术问题
- Recall@5 / MRR / 拒答率计算
- 一条命令输出报告
- 模型 / 切块版本可追溯

来源声明（任务清单 §1 + §12）：
- 移植自 rag-from-zero（MIT）：
    - rag_project/tests/sample_qa.jsonl（JSONL 结构）
    - chapters/ch10-evaluation/eval_demo.py（recall_at_k / mrr 实现思路）
- 本目录下的 `LICENSE_THIRD_PARTY` 列出了完整许可与归属；任何后续修改
  必须保留该许可证声明，不得删除原始版权。
- 用 Python 标准库实现，零第三方依赖，避免污染主后端依赖树。
"""
