# 评测 JSONL Schema — v0（T301）

本目录所有 JSONL 走同一组字段；评测脚本 (`eval/runner.py`) 严格按字段名解析。
schema 变更请同步更新本文件 + `eval/metrics.py` + `eval/README.md`。

## 文件类型

| 文件 | 字段子集 | 用途 |
|---|---|---|
| `*-ground-truth.jsonl` | 全字段 | 评测集（标准答案 + 期望拒答） |
| `*-predicted.jsonl` | 子集字段 | 检索系统对每题的输出（chunk_ids + refusal） |

> 第二类文件可由后端 dump 或人工填写；评测脚本按 `id` 关联两文件。

## Ground Truth 必填字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `string` | 题号，全局唯一；与 prediction 通过 `id` 关联 |
| `kb_id` | `string` | 题目所属 KB（与后端 chunk 的 `knowledgeBaseId` 同源；runner 用于审计） |
| `org_id` | `string` | 题目所属组织 |
| `question` | `string` | 用户查询原文 |
| `ground_truth_chunk_ids` | `string[]` | 标准答案涉及的 chunk_id（1 个或多个）；命中任一即视为命中 |
| `expect_refusal` | `bool` | 是否期望模型拒答；`true` 时表示"无依据/越界/不安全" |
| `refusal_reason` | `string \| null` | 可选；`OUT_OF_SCOPE` / `SAFETY` / `LOW_CONFIDENCE` / `NO_RETRIEVAL` |

## Ground Truth 可选字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `category` | `string` | api / error-code / config / class-name / module / data-structure / troubleshoot / out-of-scope |
| `difficulty` | `string` | easy / medium / hard |
| `notes` | `string` | 评测备注 |

## Prediction 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `string` | 与 ground truth 同名 |
| `predicted_chunk_ids` | `string[]` | 检索系统给出的 chunk 列表，按分数降序 |
| `predicted_refusal` | `bool` | 系统最终是否拒答 |
| `predicted_refusal_reason` | `string \| null` | 系统给出的拒答原因（与 ground truth 同义词表） |
| `reranked` | `bool` | 是否经过 rerank（仅用于版本审计；当前不单列 rerank 指标） |

## 拒答原因枚举（强约束）

来自前端类型 `RefusalEventPayload.reason` 与后端 11 节 v0 契约：

```
NO_RETRIEVAL | LOW_CONFIDENCE | OUT_OF_SCOPE | SAFETY
```

禁止新增枚举值；如需新增，先更新 frontend/src/types/query.ts + 后端 Java 枚举 + 本 schema。

## 校验规则

评测 runner **不**会容忍以下错误；启动时应自检：

1. ground truth 或 prediction 的 `id` 重复 → 报错并退出码 `2`。
2. prediction 的 `id` 不在 ground truth → 报错并退出码 `2`。
3. `expect_refusal=false` 时 `ground_truth_chunk_ids` 必须非空；`expect_refusal=true` 时必须为空。
4. `predicted_refusal=true` 时 `predicted_chunk_ids` 必须为空；非拒答 prediction 不得带 `predicted_refusal_reason`。
5. `predicted_chunk_ids` 中的非 gold chunk 是合法检索噪声，不作为 schema 错误。
6. unknown field 忽略，向前兼容。
