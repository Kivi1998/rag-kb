/** 文档状态枚举（与后端 DocumentStatus 一致） */
export enum KbDocumentStatus {
  UPLOADING = 'UPLOADING',
  PARSING = 'PARSING',
  READY = 'READY',
  FAILED = 'FAILED'
}

/** 文档 DTO */
export interface KbDocument {
  id: string
  name: string
  status: KbDocumentStatus
  errorMessage?: string
  createdAt: string
}
