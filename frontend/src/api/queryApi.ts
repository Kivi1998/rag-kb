import { useAuthStore } from '@/stores/authStore'
import type { QueryChunkEvent, QueryEventType } from '@/types/query'

/**
 * SSE 流式查询（原生 fetch，不经过 Axios 拦截器）
 * 手动注入 Authorization + X-Org-Id 认证头
 */
export async function* stream(
  kbId: string,
  question: string,
  signal: AbortSignal
): AsyncGenerator<QueryChunkEvent> {
  const authStore = useAuthStore()

  const response = await fetch(`/api/v1/knowledge-bases/${kbId}/query`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${authStore.token}`,
      'X-Org-Id': authStore.orgId || ''
    },
    body: JSON.stringify({ question }),
    signal
  })

  // 先检查 response.ok
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('ReadableStream not supported')

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        // stream 结束但未收到 done 事件（服务端 5 分钟超时）
        if (buffer.trim()) {
          yield parseSSEBlock(buffer)
        }
        return
      }

      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() || ''

      for (const block of blocks) {
        if (block.trim()) {
          yield parseSSEBlock(block)
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseSSEBlock(block: string): QueryChunkEvent {
  const lines = block.split('\n')
  let eventType = ''
  let data = ''

  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data = line.slice(5).trim()
    }
  }

  let payload = {}
  if (data) {
    try {
      payload = JSON.parse(data)
    } catch {
      return { eventType: 'error', message: '响应数据解析失败' } as QueryChunkEvent
    }
  }
  return { eventType: eventType as QueryEventType, ...payload } as QueryChunkEvent
}
