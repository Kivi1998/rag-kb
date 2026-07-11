/**
 * 知识库 SSE 流式问答 API 占位 Mock 契约（11 节 + T005 / T203 / T205）。
 *
 * 设计要点：
 * - 五类事件固定：chunk / source / refusal / done / error，禁止自创
 * - `event:` 是 Java QueryEventType 的小写值；source 的 data 为单个 citation，
 *   refusal 的 data 为 message（可选 reason 由未来 Controller 扩展）
 * - 使用原生 fetch + reader 避开 axios 的拦截器（SSE 流不应被 response 拦截
 *   解包逻辑污染）；与 4c41e4f 旧 queryApi.ts 的 SSE 解析形态保持一致
 * - 通过 AbortSignal 支持取消请求；网络中断由调用方捕获/重试
 * - Authorization / X-Org-Id 头由调用方注入到 header 中，避免对 Pinia 全局
 *   状态在测试时产生耦合（store 在测试里未挂载）
 */

import type {
  ChunkEventPayload,
  DoneEventPayload,
  ErrorEventPayload,
  QueryEvent,
  RefusalEventPayload,
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
 * - 5 类事件按到达顺序 yield；任何非五类事件（如服务端推送注释、空块）被静默跳过
 * - 当前为前端占位实现；后端 T203 未实现前，不能视为已完成接口联调
 */
export interface OpenStreamOptions {
  url: string
  body: { question: string; history?: ReadonlyArray<{ role: string; content: string }>; rewrite?: boolean }
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
