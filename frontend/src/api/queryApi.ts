/**
 * 知识库 SSE 流式问答契约（T203 / T205）。
 *
 * 设计要点：
 * - 六类事件：chunk / source / refusal / self_check_warning / done / error
 * - `event:` 是 Java QueryEventType 的小写值；source 的 data 为单个 citation，
 *   refusal 的 data 为 message（可选 reason 由未来 Controller 扩展）；
 *   self_check_warning 的 data 为 message，出现代表生成后自检发现疑似未支撑断言
 * - 使用原生 fetch + reader 避开 axios 的拦截器（SSE 流不应被 response 拦截
 *   解包逻辑污染）；与 4c41e4f 旧 queryApi.ts 的 SSE 解析形态保持一致
 * - 通过 AbortSignal 支持取消请求；网络中断由调用方捕获/重试
 * - Authorization / X-Org-Id 头由调用方注入到 header 中，避免对 Pinia 全局
 *   状态在测试时产生耦合（store 在测试里未挂载）
 */

import type { Citation } from '@/types/citation'
import type {
  ChatSessionSummary,
  ChunkEventPayload,
  DoneEventPayload,
  ErrorEventPayload,
  Message,
  QueryEvent,
  RefusalEventPayload,
  SelfCheckWarningEventPayload,
  SourceEventPayload
} from '@/types/query'

export type { QueryEvent }

/** SSE 原始块（`event:` + `data:` 多行） */
export interface SseBlock {
  event: string | null
  data: string | null
}

/**
 * 工具：从文本流里切出 SSE 块（兼容 LF/CRLF，剩余部分 buffer 起来跨 chunk 续拼）。
 */
export function splitSseBlocks(
  bufferIn: string,
  chunk: string
): { blocks: SseBlock[]; rest: string } {
  const merged = bufferIn + chunk
  const parts = merged.split(/\r?\n\r?\n/)
  const rest = parts.pop() ?? ''
  const blocks: SseBlock[] = []
  for (const part of parts) {
    const parsed = parseSseBlock(part)
    if (parsed) blocks.push(parsed)
  }
  return { blocks, rest }
}

/**
 * 解析单个 SSE 块；空块返回 null。
 */
export function parseSseBlock(block: string): SseBlock | null {
  if (!block.trim()) return null
  let event: string | null = null
  const dataLines: string[] = []
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      // SSE 允许一个事件有多条 data 行，换行后再作为 JSON 交给调用方。
      dataLines.push(line.slice(5).replace(/^ /, ''))
    }
  }
  const data = dataLines.length ? dataLines.join('\n') : null
  if (event === null && data === null) return null
  return { event, data }
}

/** 把 SSE 块转换为 QueryEvent；非法事件按 error 处理（防御式） */
export function toQueryEvent(block: SseBlock): QueryEvent {
  const parsed = parseJsonSafe(block.data)
  if (!parsed.ok) return protocolError(parsed.message)
  const payload = parsed.value
  switch (block.event) {
    case 'chunk':
      if (!isRecord(payload) || typeof payload.content !== 'string') {
        return protocolError('chunk 事件缺少字符串 content')
      }
      return {
        eventType: 'chunk',
        data: { content: payload.content } satisfies ChunkEventPayload
      }
    case 'source':
      if (!isRecord(payload) || !isRecord(payload.citation)) {
        return protocolError('source 事件缺少 citation')
      }
      return {
        eventType: 'source',
        data: { citation: payload.citation as unknown as SourceEventPayload['citation'] }
      }
    case 'refusal':
      if (!isRecord(payload) || typeof payload.message !== 'string') {
        return protocolError('refusal 事件缺少字符串 message')
      }
      if (payload.reason !== undefined && !isRefusalReason(payload.reason)) {
        return protocolError('refusal 事件含无效 reason')
      }
      return {
        eventType: 'refusal',
        data: {
          message: payload.message,
          ...(payload.reason === undefined ? {} : { reason: payload.reason })
        } satisfies RefusalEventPayload
      }
    case 'self_check_warning':
      if (!isRecord(payload) || typeof payload.message !== 'string') {
        return protocolError('self_check_warning 事件缺少字符串 message')
      }
      return {
        eventType: 'self_check_warning',
        data: { message: payload.message } satisfies SelfCheckWarningEventPayload
      }
    case 'done':
      if (!isRecord(payload) || Object.keys(payload).length !== 0) {
        return protocolError('done 事件不应携带业务载荷')
      }
      return {
        eventType: 'done',
        data: {} as DoneEventPayload
      }
    case 'error':
      if (!isRecord(payload) || typeof payload.message !== 'string') {
        return protocolError('error 事件缺少字符串 message')
      }
      return {
        eventType: 'error',
        data: {
          message: payload.message,
          ...(typeof payload.code === 'string' ? { code: payload.code } : {})
        } satisfies ErrorEventPayload
      }
    default:
      return protocolError(`未知事件类型: ${String(block.event)}`)
  }
}

function parseJsonSafe(raw: string | null): { ok: true; value: unknown } | { ok: false; message: string } {
  if (!raw) return { ok: false, message: 'SSE 事件缺少 data JSON' }
  try {
    return { ok: true, value: JSON.parse(raw) }
  } catch {
    return { ok: false, message: 'SSE data 不是合法 JSON' }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isRefusalReason(value: unknown): value is NonNullable<RefusalEventPayload['reason']> {
  return value === 'NO_RETRIEVAL' || value === 'LOW_CONFIDENCE' || value === 'OUT_OF_SCOPE' || value === 'SAFETY'
}

function protocolError(message: string): QueryEvent {
  return { eventType: 'error', data: { message: `SSE 协议错误: ${message}` } }
}

/**
 * 启动流式问答。
 *
 * 行为契约：
 * - 后端 URI 路径由调用方传入完整 URL（kbId 必须在 URL 中显式带出，方便后端
 *   做服务端 org/kb 过滤；前端不传 org/kb 参数，也不允许覆盖 X-Org-Id 之外的
 *   路径参数）
 * - 调用方负责把 token / X-Org-Id 放到 headers 中
 * - AbortSignal 触发时，闭包内 fetch 自动抛 AbortError，AsyncGenerator 终止
 * - 六类事件按到达顺序 yield；任何不认识的事件（如服务端推送注释、空块）被静默跳过
 * - 后端已实现该协议；真实 ES/模型环境仍需按部署手册完成端到端验收
 */
export interface OpenStreamOptions {
  url: string
  body: { question: string; sessionId: string }
  headers: Readonly<Record<string, string>>
  signal?: AbortSignal
}

export async function* openStream(opts: OpenStreamOptions): AsyncGenerator<QueryEvent> {
  const response = await fetch(opts.url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...opts.headers
    },
    body: JSON.stringify(opts.body),
    signal: opts.signal
  })

  if (!response.ok) {
    yield {
      eventType: 'error',
      data: { message: `HTTP ${response.status} ${response.statusText}` }
    }
    return
  }

  const reader = response.body?.getReader()
  if (!reader) {
    yield {
      eventType: 'error',
      data: { message: 'ReadableStream not supported' }
    }
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        if (buffer.trim()) {
          const final = parseSseBlock(buffer)
          if (final) yield toQueryEvent(final)
        }
        return
      }
      buffer += decoder.decode(value, { stream: true })
      const { blocks, rest } = splitSseBlocks('', buffer)
      buffer = rest
      for (const block of blocks) {
        yield toQueryEvent(block)
      }
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      // ignore - 已经释放
    }
  }
}

/** 默认问答路径（kbId 拼到 URL 里） */
export function queryStreamUrl(baseUrl: string, kbId: string): string {
  return `${baseUrl.replace(/\/$/, '')}/api/v1/knowledge-bases/${encodeURIComponent(kbId)}/query`
}

/** 会话创建路径。 */
export function sessionUrl(baseUrl: string, kbId: string): string {
  return `${baseUrl.replace(/\/$/, '')}/api/v1/knowledge-bases/${encodeURIComponent(kbId)}/sessions`
}

/**
 * 创建多轮对话会话，返回 sessionId。切换知识库/新建对话时调用，
 * 之后同一对话内的每次提问都携带同一个 sessionId。
 */
export async function createSession(
  baseUrl: string,
  kbId: string,
  headers: Readonly<Record<string, string>>
): Promise<string> {
  const response = await fetch(sessionUrl(baseUrl, kbId), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers }
  })
  if (!response.ok) {
    throw new Error(`创建会话失败: HTTP ${response.status} ${response.statusText}`)
  }
  const payload = (await response.json()) as { data?: { sessionId?: string } }
  const sessionId = payload.data?.sessionId
  if (!sessionId) {
    throw new Error('创建会话响应缺少 sessionId')
  }
  return sessionId
}

/** 单个会话消息查询路径。 */
export function sessionMessagesUrl(baseUrl: string, kbId: string, sessionId: string): string {
  return `${sessionUrl(baseUrl, kbId)}/${encodeURIComponent(sessionId)}/messages`
}

/** 单个会话资源路径（删除用）。 */
export function sessionResourceUrl(baseUrl: string, kbId: string, sessionId: string): string {
  return `${sessionUrl(baseUrl, kbId)}/${encodeURIComponent(sessionId)}`
}

/** 查询某知识库下当前成员最近活跃的历史会话列表，按最后活跃时间倒序。 */
export async function listSessions(
  baseUrl: string,
  kbId: string,
  headers: Readonly<Record<string, string>>
): Promise<ChatSessionSummary[]> {
  const response = await fetch(sessionUrl(baseUrl, kbId), { headers })
  if (!response.ok) {
    throw new Error(`查询历史会话失败: HTTP ${response.status} ${response.statusText}`)
  }
  const payload = (await response.json()) as { data?: ChatSessionSummary[] }
  return payload.data ?? []
}

/**
 * 拉取某会话的历史消息，转换为前端 `Message[]`。citations 只有 assistant 消息、且这个
 * 字段上线后新产生的消息才会有值；上线前的旧消息该字段为空，恢复出来跟没有引用一样，
 * 不做历史回填（已与用户确认接受）。
 */
export async function getSessionMessages(
  baseUrl: string,
  kbId: string,
  sessionId: string,
  headers: Readonly<Record<string, string>>
): Promise<Message[]> {
  const response = await fetch(sessionMessagesUrl(baseUrl, kbId, sessionId), { headers })
  if (!response.ok) {
    throw new Error(`查询会话消息失败: HTTP ${response.status} ${response.statusText}`)
  }
  const payload = (await response.json()) as {
    // 后端 Jackson 对 null 字段不做 NON_NULL 过滤，旧消息/user 消息这里拿到的是显式的
    // JSON null，不是字段缺失（undefined）——用 `| null` 如实标注，归一化到 undefined
    // 时才不会有类型和真实响应形状对不上的问题。
    data?: Array<{ role: string; content: string; createdAt: string; citations?: Citation[] | null }>
  }
  return (payload.data ?? []).map((message) => ({
    id: crypto.randomUUID(),
    role: message.role === 'assistant' ? 'assistant' : 'user',
    content: message.content,
    createdAt: message.createdAt,
    citations: message.citations ?? undefined
  }))
}

/** 硬删除某个历史会话，级联清理服务端全部相关数据。 */
export async function deleteSession(
  baseUrl: string,
  kbId: string,
  sessionId: string,
  headers: Readonly<Record<string, string>>
): Promise<void> {
  const response = await fetch(sessionResourceUrl(baseUrl, kbId, sessionId), {
    method: 'DELETE',
    headers
  })
  if (!response.ok) {
    throw new Error(`删除会话失败: HTTP ${response.status} ${response.statusText}`)
  }
}
