/**
 * Citation 的 HTTP/SSE wire DTO。
 *
 * 字段、字段名和可空性与 Java `ragcore.model.Citation` 一一对应：Java record
 * 没有为这些引用类型施加非空约束，只有 `headingPath` 会被标准化为空数组。
 * 一个 `source` SSE 事件只携带一个 Citation；调用方可自行累积成引用卡片列表。
 */
export interface Citation {
  /** 文档主键（点击引用卡片可跳转） */
  documentId: string | null
  /** 文档名（前端展示） */
  documentName: string | null
  /** chunk 标题层级路径（如 ["API", "auth", "POST /login"]） */
  headingPath: readonly string[]
  /** 片段（截短后的原文） */
  snippet: string | null
  /** 页码（可选） */
  pageNo: number | null
  /** 起始行号（可选） */
  lineStart: number | null
  /** 结束行号（可选） */
  lineEnd: number | null
  /** 综合相关分（前端的"按相关度排序"依据） */
  score: number | null
}
