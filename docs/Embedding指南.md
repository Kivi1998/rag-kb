# Embedding 选型与向量化指南

本文说明 rag-kb Embedding 环节的选型过程、当前实现与已知待办。

## 当前实现

- **接口**：`EmbeddingClient`（`backend/.../ragcore/embedding/EmbeddingClient.java`），批量输入文本、返回向量列表；
- **实现**：`OpenAiCompatibleEmbeddingClient`（OpenAI 兼容协议），带分批与超时处理；
- **已验证基线模型**：硅基流动（SiliconFlow）在线 API 的 `BAAI/bge-m3`（1024 维，8K 上下文），配置在 `.env`，key 不入库；代码只依赖 OpenAI 兼容协议，不把供应商硬编码为硅基流动；
- **约束**：Elasticsearch 索引（`rag_chunks_v1`）与可选 Milvus Collection
  （`rag_chunks_vector_v1`）的向量维度必须与模型输出维度完全一致（1024）；换成不兼容维度
  或模型版本时应创建新索引/Collection 并回填，不原地混写。

## 选型过程（数字与结论怎么来的）

1. **最初**（2026-07-13 联调期）：内网 Xinference 部署的 `bge-large-zh-v1.5`（1024 维）。
   期间发现内网网关对"HTTP 请求头与请求体分两次写入"处理有 bug（curl 能通、Java/Python
   标准客户端必现 502），细节见[检索与审计验收](检索与审计验收.md)第 1 节的问题记录。
2. **切换**（2026-07-14）：改用硅基流动在线 API。**实测发现 `bge-large-zh-v1.5` 在硅基流动
   对超过 512 token 的输入直接报错（code 20015）**，不可用于 chunk 侧向量化（V3 切块的
   chunk 上限约 1200 字符，常超 512 token）；`BAAI/bge-m3` 8K 上下文实测通过，且同为
   1024 维，不需要重建索引。切换零代码改动（OpenAI 兼容客户端），只改 `.env`。
3. **正式评测**：150 题人工标注评估集（`eval-set-v2.jsonl`）× bge-m3 kNN + BM25 + RRF +
   rerank 完整链路，Recall@5 = 0.904（权威基线报告
   `eval/reports/eval-v2-calibrated-20260714.md`；评测方法见[评估指南](评估指南.md)）。

## 降级行为

Embedding 服务不可用时检索不中断：`HybridRetriever` 自动降级为 BM25-only（若 BM25 有
命中仍返回结果），记录 `embedding_fallback` 审计标记并告警，不输出 Key/Prompt/文档正文。

## 已知待办（记录于 `TODOS.md`）

- **BGE query 指令前缀**：BGE 系列是非对称检索模型，官方建议 query 侧加指令前缀（如
  "为这个句子生成表示以用于检索相关文章："）。bge-m3 密集检索模式对前缀不敏感，当前
  未加、优先级低；**若换回 bge 非对称模型则必须加**。

## 相关文档

| 文档 | 内容 |
|---|---|
| [总体架构](architecture.md) 决策 2 | 直接使用基础设施、不用高层 RAG 框架的选型理由 |
| [评估指南](评估指南.md) | 评测方法论与权威基线数字的完整来源 |
