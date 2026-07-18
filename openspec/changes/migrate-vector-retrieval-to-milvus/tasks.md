## 1. 基线与依赖配置

- [ ] 1.1 固化当前 ES BM25+kNN 单元测试和 150 题评测基线，记录 Recall@1/5、MRR 与 P95 复现命令
- [ ] 1.2 在后端加入与目标服务端版本匹配的 Milvus Java SDK，并完成依赖收敛与许可证检查
- [ ] 1.3 新增 `RagMilvusProperties` 和 `VectorProviderProperties`，校验 endpoint、collection、1024 维、模式、超时与 HNSW 参数
- [ ] 1.4 为开发/验收 Compose 增加隔离的 Milvus、etcd、对象存储与健康检查，不提交明文密钥
- [ ] 1.5 增加配置绑定、非法维度、非法 Provider 和缺失凭据的启动测试

## 2. 检索与索引端口拆分

- [ ] 2.1 新增 `LexicalCandidateSource`、`VectorCandidateSource`、`VectorHit`、`ChunkHydrator` 端口及参数校验测试
- [ ] 2.2 将 ES BM25 提取为 `ElasticsearchLexicalCandidateSource`，保持技术标识加权、候选数和租户过滤行为不变
- [ ] 2.3 将 ES kNN 提取为 `ElasticsearchVectorCandidateSource`，作为基线与回滚实现
- [ ] 2.4 实现 `ElasticsearchChunkHydrator` 的批量补齐、顺序恢复、缺失 ID 丢弃和字段转换
- [ ] 2.5 为 ES 补齐增加跨组织、跨知识库和伪造 Chunk ID 安全测试，验证越界候选不会进入 `RetrievedChunk`
- [ ] 2.6 改造 `HybridRetriever` 使用拆分端口，并验证 RRF、Rerank、拒答、Embedding 降级测试全部保持通过

## 3. 双端可见性闸门

- [ ] 3.1 扩展 ES Chunk Mapping 与文档投影，增加 `retrieval_ready`、模型版本和切块版本的严格字段
- [ ] 3.2 为 ES 新增暂存 Upsert、按文档激活、关闭可见性接口及幂等测试
- [ ] 3.3 给 ES BM25、ES kNN、Chunk 补齐和删除查询统一加入 `retrieval_ready=true` 与 org/kb 边界
- [ ] 3.4 增加存量 ES Chunk 可见性回填命令，支持 dry-run、分页、重试和数量校验
- [ ] 3.5 增加半写入、激活失败、跨租户激活和跨租户关闭可见性的安全回归测试

## 4. Milvus Collection 与数据访问

- [ ] 4.1 实现 Milvus 客户端生命周期、鉴权/TLS 配置和连接关闭，补充超时与资源释放测试
- [ ] 4.2 实现 `MilvusCollectionManager`，创建并校验 `rag_chunks_vector_v1` Schema、HNSW/COSINE 索引和加载状态
- [ ] 4.3 实现 `MilvusVectorIndex` 的批量暂存 Upsert、按文档激活、关闭可见性和幂等删除
- [ ] 4.4 实现 `MilvusVectorCandidateSource`，使用 HNSW ANN、配置化 `ef/topK` 和服务端标量过滤
- [ ] 4.5 为 Milvus 查询/写删增加 org+kb+document 边界构造测试，验证空边界及跨租户请求在 SDK 调用前被拒
- [ ] 4.6 实现 Milvus Collection 兼容性健康检查，维度/主键/距离不一致时 fail-fast 且不覆盖已有数据

## 5. 摄取双写与删除补偿

- [ ] 5.1 新增词法/向量投影编排器，按 ES 暂存→Milvus 暂存→Milvus 激活→ES 激活顺序执行
- [ ] 5.2 将摄取 Pipeline 接入投影编排器，只有 ES 最终激活成功才推进 `READY`
- [ ] 5.3 增加各双写步骤故障注入测试，验证确定性 Chunk ID 重试后收敛且暂存数据不可检索
- [ ] 5.4 将删除补偿改为 ES 关闭可见性→Milvus 删除→ES 删除→对象/元数据清理
- [ ] 5.5 增加删除中断、重复删除、Worker 租约接管和跨租户删除安全测试

## 6. Provider、影子读与降级

- [ ] 6.1 实现 `elasticsearch`、`shadow`、`milvus` 三种服务端 Provider 装配，外部请求不得覆盖模式
- [ ] 6.2 实现 Milvus 主查询失败回退 ES kNN、双向量源失败退化 BM25，并记录实际降级路径
- [ ] 6.3 实现影子查询复用同一查询向量，设置独立超时且不改变线上 ES 结果
- [ ] 6.4 实现 ES/Milvus TopK 重合率、差异数、查询延迟、回退和孤儿向量 Micrometer 指标
- [ ] 6.5 增加三种 Provider、影子超时、回退链和所有降级组合的跨租户隔离测试

## 7. 历史回填与一致性校验

- [ ] 7.1 新增 Milvus 回填检查点表、Flyway 迁移和租户隔离实体/Repository 测试
- [ ] 7.2 实现 ES 向量分页读取与模型/维度/Chunk 版本兼容性判断，不兼容项进入待重向量化清单
- [ ] 7.3 实现 Milvus 批量回填、断点续跑、重复批次幂等和失败重试
- [ ] 7.4 实现 ES/Milvus 总数、租户分布、重复主键、孤儿 ID 与抽样向量校验报告
- [ ] 7.5 增加跨租户检查点访问被拒、回填中断恢复和不兼容向量禁止混写的测试

## 8. 集成验收与交付

- [ ] 8.1 在真实 ES+Milvus 环境跑上传→切块→双写→混合检索→引用→删除全链路集成测试
- [ ] 8.2 执行跨组织、跨知识库、指定文档过滤、伪造 Milvus ID 和删除残留安全验收
- [ ] 8.3 运行 150 题 ES/Milvus 对比评测，确认 Recall@1/5、MRR 与拒答指标不低于已签字基线
- [ ] 8.4 执行目标并发压测，记录 ES 与 Milvus 的 P50/P95/P99、吞吐、内存、磁盘和单位查询成本
- [ ] 8.5 更新 README、混合检索指南、Embedding 指南、部署手册和回滚手册，明确 `rag_memory_v1` 未迁移
- [ ] 8.6 运行后端全量测试、Compose 验收和 `openspec validate`，审查差异后提交分支
