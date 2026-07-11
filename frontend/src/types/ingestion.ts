/**
 * 摄取任务状态机 — v0 契约（11 节）。
 * 与后端 T003/T102 在 `ingestion_job.status` 字段强制使用同一枚举；
 * 任何新增态必须由 GPT-5.6 在 PR 中同步追加，禁止前端自创。
 */
export type IngestionStatus =
  | 'QUEUED'
  | 'PARSING'
  | 'CHUNKING'
  | 'EMBEDDING'
  | 'INDEXING'
  | 'READY'
  | 'FAILED'
  | 'DELETING'

/** 摄取状态集合（用于状态徽章配色 / 按钮禁用判断） */
export const INGESTION_TERMINAL_STATES: ReadonlySet<IngestionStatus> = new Set([
  'READY',
  'FAILED'
])

export const INGESTION_IN_FLIGHT_STATES: ReadonlySet<IngestionStatus> = new Set([
  'QUEUED',
  'PARSING',
  'CHUNKING',
  'EMBEDDING',
  'INDEXING'
])

/** 健康状态（用于 KB 列表的可用性筛选） */
export const INGESTION_HEALTHY_STATE: IngestionStatus = 'READY'

/**
 * KB 维度下的文档抽象。
 * `documentId` 与后端文档主键一致；`kbId` 由服务端注入，前端不允许构造。
 */
export interface Document {
  /** 文档主键（org 内唯一） */
  documentId: string
  /** 所属 KB（org 内唯一，前端禁止构造，仅由后端在响应里返回） */
  kbId: string
  /** 文件名 */
  name: string
  /** 字节数 */
  size: number
  /** MIME 类型 */
  contentType: string
  /** 当前摄取状态 */
  status: IngestionStatus
  /** 失败时的错误信息（服务端脱敏后的） */
  errorMessage?: string
  /** 当前已重试次数 */
  retryCount?: number
  /** 是否还可重试（服务端根据重试上限计算） */
  retryable?: boolean
  /** 上传时间 ISO 8601 */
  uploadedAt: string
  /** READY 时间 ISO 8601（READY 之前为空） */
  readyAt?: string
  /** 服务端可选 metadata 中的 sourcePath/key，便于做审计追溯 */
  sourcePath?: string
}

/**
 * 摄取任务（一次上传对应一条任务；文档可能因为重建产生多条历史任务）。
 */
export interface IngestionJob {
  jobId: string
  documentId: string
  kbId: string
  status: IngestionStatus
  progress?: {
    /** 总 chunk 数（READY 时已知；其他状态下为估算） */
    total?: number
    /** 已完成 chunk 数 */
    done?: number
  }
  errorMessage?: string
  /** 重试上限（管理员手动重试时显示） */
  retryLimit?: number
  /** 是否可重试 */
  retryable?: boolean
  createdAt: string
  updatedAt: string
}
