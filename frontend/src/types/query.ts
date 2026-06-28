/** SSE 查询事件类型 */
export type QueryEventType = 'chunk' | 'source' | 'done' | 'error'

/** SSE 事件 DTO */
export interface QueryChunkEvent {
  eventType: QueryEventType
  content?: string
  documentName?: string
  score?: number
  message?: string
}

/** 消息来源 */
export interface Source {
  documentName: string
  content: string
  score: number
}

/** 聊天消息 */
export interface Message {
  role: 'user' | 'assistant' | 'error'
  content: string
  sources?: Source[]
}
