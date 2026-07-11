/**
 * Chunk / RetrievedChunk 的 wire DTO。
 *
 * 此文件逐字段对齐 Java `ragcore.model.Chunk` / `RetrievedChunk`，不是可由
 * 浏览器任意构造的领域对象。Java record 未对引用字段施加非空约束；唯一保证
 * 非空的是 primitive `ordinal` 和被构造器标准化后的 `headingPath` / `metadata`。
 */

/** 自然语言定位行（H1 / H2 / …） */
export type HeadingPath = readonly string[]

/**
 * 服务端最终入库的 chunk。
 * `orgId` / `kbId` 由后端注入，前端禁止从客户端构造。
 */
export interface Chunk {
  id: string | null
  /** 来自服务端，前端禁止构造或修改 */
  organizationId: string | null
  /** 来自服务端，前端禁止构造或修改 */
  knowledgeBaseId: string | null
  /** 所属文档 */
  documentId: string | null
  /** 文档内顺序（0-based） */
  ordinal: number
  /** 原始正文（不含位置标签） */
  content: string | null
  /** 标题层级路径，如 ["API", "auth", "POST /login"] */
  headingPath: HeadingPath
  /** 源文件相对路径，便于在文档工作区里跳转定位 */
  sourcePath: string | null
  /** 页码（PDF/DOCX 有，代码/MD 可能为空） */
  pageNo: number | null
  /** 行号范围（解析器输出；用于代码块跳转） */
  lineStart: number | null
  lineEnd: number | null
  /** 用于标识代码语言（前端可着色） */
  language: string | null
  /** chunk 内容的稳定哈希，前端调试时可用于匹配 */
  contentHash: string | null
  /** 任意服务端补充元数据（如配置项 key、错误码） */
  metadata: Readonly<Record<string, string>>
}

/**
 * 检索阶段的输出：原始 chunk + 各路召回分数。
 * 仅后端在 SSE 路径里发出，前端展示时只用 `chunk` + `finalScore`。
 */
export interface RetrievedChunk {
  chunk: Chunk | null
  /** BM25 排名（未召回则为 undefined） */
  bm25Rank: number | null
  /** 向量排名 */
  vectorRank: number | null
  /** RRF 融合分（必填） */
  rrfScore: number | null
  /** Cross-Encoder / Rerank 分（无 Rerank 客户端降级时为 undefined） */
  rerankScore: number | null
  /** 最终进入 prompt 排序的分数 */
  finalScore: number | null
}
