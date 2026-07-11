/**
 * Query / SSE 事件类型 — v0 契约（11 节）。
 *
 * 五类 SSE 事件固定为：chunk / source / refusal / done / error。
 * Java `QueryEventType` 由 Controller 序列化为同名小写 `event:`；`QueryEvent`
 * 的单个 `citation`、`message` 等载荷字段直接写入 `data:` JSON。
 */

import type { Citation } from './citation'

/** SSE 事件类型枚举 */
export type QueryEventType = 'chunk' | 'source' | 'refusal' | 'done' | 'error'

/**
 * `chunk` 事件载荷——流式正文增量。
 * 多次出现，按到达顺序拼接为最终答案。
 */
export interface ChunkEventPayload {
  /** 本次增量文本 */
  content: string
}

/**
 * `source` 事件载荷——单个引用。
 * 与 Java `QueryEvent.citation` 一一对应。一次回答可推送多次 source，前端累积。
 */
export interface SourceEventPayload {
  citation: Citation
}

/**
 * `refusal` 事件载荷——模型拒答。
 * 出现时意味着检索置信度不足或空召回；
 * 前端据此渲染"无依据可回答"提示，且不应再期待 `chunk` 内容。
 */
export interface RefusalEventPayload {
  /**
   * 拒答原因码。当前 Java 核心仅冻结 `message`，因此该字段是可选扩展；
   * 后端未提供时前端不得假定存在。
   */
  reason?:
    | 'NO_RETRIEVAL'
    | 'LOW_CONFIDENCE'
    | 'OUT_OF_SCOPE'
    | 'SAFETY'
  /** 给用户看的一句话（已脱敏） */
  message: string
}

/**
 * `done` 事件载荷——流结束。
 * Java `QueryEvent.done()` 不携带业务字段，前端用其关闭 loading。
 */
export type DoneEventPayload = Record<string, never>

/**
 * `error` 事件载荷——流错误。
 * 与 `refusal` 不同：错误是异常（不可恢复），拒答是正常业务结果。
 */
export interface ErrorEventPayload {
  message: string
  /** 错误码（非 0；前端可据此 toast） */
  code?: string
}

/** 五类事件的联合类型，使用判别字段 `eventType` */
export type QueryEvent =
  | { eventType: 'chunk'; data: ChunkEventPayload }
  | { eventType: 'source'; data: SourceEventPayload }
  | { eventType: 'refusal'; data: RefusalEventPayload }
  | { eventType: 'done'; data: DoneEventPayload }
  | { eventType: 'error'; data: ErrorEventPayload }

/** 聊天历史中的单条消息 */
export interface Message {
  id: string
  role: 'user' | 'assistant' | 'error' | 'refusal'
  /** 文本内容（assistant 角色的最终答案 / 用户的提问原文 / 错误描述） */
  content: string
  /** assistant 角色附带的引用卡片（与答案同步显示） */
  citations?: Citation[]
  /** 仅 refusal 角色的具体原因码；后端当前可能未提供 */
  refusalReason?: RefusalEventPayload['reason']
  /** 创建时间，前端调试用 */
  createdAt: string
}

/** 提问请求（POST /api/v1/knowledge-bases/{kbId}/query） */
export interface QueryRequest {
  question: string
  /** 历史消息（用于多轮对话；不含当前问题） */
  history?: ReadonlyArray<Pick<Message, 'role' | 'content'>>
  /** 是否开启 Query 改写/HYDE（生产由服务端默认决定；前端可显式覆盖） */
  rewrite?: boolean
}
