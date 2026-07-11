import { describe, expect, it, vi } from 'vitest'
import {
  openStream,
  parseSseBlock,
  queryStreamUrl,
  splitSseBlocks,
  toQueryEvent,
  type SseBlock
} from '@/api/queryApi'

/**
 * 构造一个可控的 SSE Response：把若干 SSE 字节流分批塞给 reader。
 */
function makeSseResponse(chunks: string[], ok = true): Response {
  const enc = new TextEncoder()
  let cursor = 0
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (cursor >= chunks.length) {
        controller.close()
        return
      }
      controller.enqueue(enc.encode(chunks[cursor]))
      cursor += 1
    }
  })
  const headers = new Headers({ 'Content-Type': 'text/event-stream' })
  return new Response(stream, {
    status: ok ? 200 : 500,
    statusText: ok ? 'OK' : 'Server Error',
    headers
  })
}

function fetchSpyReturning(response: Response) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(response)
}

/** 构造一个会响应 abort 的 fetch mock：收到 abort 时直接抛 AbortError */
function fetchSpyAbortable() {
  return vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation((_url: unknown, init?: RequestInit) => {
      return new Promise((resolve, reject) => {
        const signal = init?.signal
        if (signal?.aborted) {
          reject(new DOMException('Aborted', 'AbortError'))
          return
        }
        signal?.addEventListener(
          'abort',
          () => reject(new DOMException('Aborted', 'AbortError')),
          { once: true }
        )
        // 用一个永远不结束 + 也不会抛的占位响应避免悬空；
        // 真正的 abort 会在 listener 里触发 reject
        const enc = new TextEncoder()
        const never = new ReadableStream<Uint8Array>({
          start() {
            void enc
          }
        })
        resolve(
          new Response(never, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' }
          })
        )
      })
    })
}

const baseOpts = {
  body: { question: '核辐射在保障范围内吗？' },
  headers: {
    Authorization: 'Bearer test-token',
    'X-Org-Id': 'org-42'
  }
}

describe('parseSseBlock', () => {
  it('解析 event + data 单独一行', () => {
    const b = parseSseBlock('event: chunk\ndata: {"content":"你好"}')
    expect(b).toEqual({ event: 'chunk', data: '{"content":"你好"}' })
  })

  it('空块返回 null', () => {
    expect(parseSseBlock('')).toBeNull()
    expect(parseSseBlock('   \n\n   ')).toBeNull()
  })

  it('只 data 不 event 也可解析（兼容心跳）', () => {
    const b = parseSseBlock('data: {"keepalive":true}')
    expect(b).toEqual({ event: null, data: '{"keepalive":true}' })
  })

  it('兼容 CRLF 与多行 data，并按 SSE 规则拼接', () => {
    const b = parseSseBlock('event: chunk\r\ndata: {"content":\r\ndata: "你好"}')
    expect(b).toEqual({ event: 'chunk', data: '{"content":\n"你好"}' })
  })
})

describe('splitSseBlocks 边界', () => {
  it('不完整的尾块被暂存到 rest', () => {
    const { blocks, rest } = splitSseBlocks('', 'event: chunk\ndata: hi')
    expect(blocks).toHaveLength(0)
    expect(rest).toBe('event: chunk\ndata: hi')
  })

  it('完整块 + 剩余未结束的尾巴', () => {
    const { blocks, rest } = splitSseBlocks(
      '',
      'event: chunk\ndata: a\n\nevent: chunk\ndata: b\n\nevent: cho'
    )
    expect(blocks.map((b: SseBlock) => b.event)).toEqual(['chunk', 'chunk'])
    expect(rest).toBe('event: cho')
  })

  it('跨续拼接：上一块尾巴 + 新到一段应组成完整块', () => {
    const { blocks } = splitSseBlocks(
      'event: chunk\ndata: {"con',
      'tent":"hi"}\n\n'
    )
    expect(blocks).toHaveLength(1)
    expect(blocks[0].event).toBe('chunk')
    expect(blocks[0].data).toBe('{"content":"hi"}')
  })

  it('兼容 CRLF 事件分隔符', () => {
    const { blocks, rest } = splitSseBlocks('', 'event: done\r\ndata: {}\r\n\r\n')
    expect(blocks).toHaveLength(1)
    expect(blocks[0].event).toBe('done')
    expect(rest).toBe('')
  })
})

describe('toQueryEvent', () => {
  it('未知事件类型降级为 error', () => {
    const evt = toQueryEvent({ event: 'foo', data: '{}' })
    expect(evt.eventType).toBe('error')
  })

  it('chunk 事件载荷完整', () => {
    const evt = toQueryEvent({ event: 'chunk', data: '{"content":"部分正文"}' })
    expect(evt.eventType).toBe('chunk')
    if (evt.eventType === 'chunk') {
      expect(evt.data.content).toBe('部分正文')
    }
  })

  it('refusal 事件载荷完整', () => {
    const evt = toQueryEvent({
      event: 'refusal',
      data: '{"reason":"NO_RETRIEVAL","message":"未检索到相关知识"}'
    })
    expect(evt.eventType).toBe('refusal')
    if (evt.eventType === 'refusal') {
      expect(evt.data.reason).toBe('NO_RETRIEVAL')
    }
  })

  it('refusal 兼容当前 Java 核心只提供 message 的契约', () => {
    const evt = toQueryEvent({ event: 'refusal', data: '{"message":"未检索到相关知识"}' })
    expect(evt).toEqual({ eventType: 'refusal', data: { message: '未检索到相关知识' } })
  })

  it('source 使用 Java QueryEvent 的单个 citation 字段', () => {
    const evt = toQueryEvent({
      event: 'source',
      data: '{"citation":{"documentId":"d1","documentName":"a.md","headingPath":[],"snippet":"...","pageNo":null,"lineStart":null,"lineEnd":null,"score":null}}'
    })
    expect(evt.eventType).toBe('source')
    if (evt.eventType === 'source') expect(evt.data.citation.documentId).toBe('d1')
  })

  it('非法 JSON 转换为可观测的协议 error，而不是伪造合法事件', () => {
    const evt = toQueryEvent({ event: 'chunk', data: 'not-json' })
    expect(evt).toEqual({ eventType: 'error', data: { message: 'SSE 协议错误: SSE data 不是合法 JSON' } })
  })
})

describe('openStream 接口契约', () => {
  it('chunk + source + done 按顺序产出', async () => {
    fetchSpyReturning(
      makeSseResponse([
        'event: chunk\ndata: {"content":"答"}\n\n',
        'event: chunk\ndata: {"content":"案"}\n\n',
        'event: source\ndata: {"citation":{"documentId":"d1","documentName":"a.md","headingPath":["h1"],"snippet":"...","pageNo":null,"lineStart":null,"lineEnd":null,"score":0.9}}\n\n',
        'event: done\ndata: {}\n\n'
      ])
    )

    const events: string[] = []
    for await (const evt of openStream({ ...baseOpts, url: '/x' })) {
      events.push(evt.eventType)
    }
    expect(events).toEqual(['chunk', 'chunk', 'source', 'done'])
  })

  it('refusal 单独路径：refusal 后无须再期待 chunk', async () => {
    fetchSpyReturning(
      makeSseResponse([
        'event: refusal\ndata: {"message":"未检索到相关知识"}\n\n',
        'event: done\ndata: {}\n\n'
      ])
    )

    const types: string[] = []
    for await (const evt of openStream({ ...baseOpts, url: '/x' })) {
      types.push(evt.eventType)
    }
    expect(types).toEqual(['refusal', 'done'])
  })

  it('SSE 块被 cut 在中途时，下一次到达会自动续拼', async () => {
    fetchSpyReturning(
      makeSseResponse([
        'event: chunk\ndata: {"content":"完',
        '整的片段"}\n\nevent: done\ndata: {}\n\n'
      ])
    )

    const contents: string[] = []
    for await (const evt of openStream({ ...baseOpts, url: '/x' })) {
      if (evt.eventType === 'chunk') contents.push(evt.data.content)
    }
    expect(contents).toEqual(['完整的片段'])
  })

  it('流结尾的缓冲残留也按块解析', async () => {
    fetchSpyReturning(
      makeSseResponse(['event: done\ndata: {}'], /* ok */ true)
    )

    const types: string[] = []
    for await (const evt of openStream({ ...baseOpts, url: '/x' })) {
      types.push(evt.eventType)
    }
    expect(types).toEqual(['done'])
  })

  it('非 2xx HTTP 立即产出 error 事件并终止', async () => {
    fetchSpyReturning(makeSseResponse([], /* ok */ false))
    const types: string[] = []
    for await (const evt of openStream({ ...baseOpts, url: '/x' })) {
      types.push(evt.eventType)
    }
    expect(types).toEqual(['error'])
  })

  it('请求头里强制携带 token 与 X-Org-Id（toB 多租户隔离红线）', async () => {
    const spy = fetchSpyReturning(makeSseResponse(['event: done\ndata: {}\n\n']))
    // 触发一次消费
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    for await (const _evt of openStream({ ...baseOpts, url: '/x' })) {
      // 消费掉
    }
    const called = spy.mock.calls[0]
    expect(called).toBeDefined()
    const init = called[1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers['Authorization']).toBe('Bearer test-token')
    expect(headers['X-Org-Id']).toBe('org-42')
  })

  it('请求体携带 kbId 经 URL 显式带出，后端做服务端过滤', async () => {
    const spy = fetchSpyReturning(makeSseResponse(['event: done\ndata: {}\n\n']))
    const url = queryStreamUrl('http://api.example.com', 'kb/with/slash')
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    for await (const _evt of openStream({ ...baseOpts, url })) {
      // 消费
    }
    const called = spy.mock.calls[0]
    const reqUrl = called[0] as string
    // kbId 中的 `/` 必须 encode，避免 URL 解析歧义；后端按 path 段校验 kb 归属
    expect(reqUrl).toBe('http://api.example.com/api/v1/knowledge-bases/kb%2Fwith%2Fslash/query')
  })

  it('AbortSignal 触发时迭代器立即终止', async () => {
    fetchSpyAbortable()
    const ac = new AbortController()
    const iter = openStream({ ...baseOpts, url: '/x', signal: ac.signal })
    // 先暂停一下让 fetch 启动；然后 abort；iter 的首个 next() 会 reject
    await new Promise((r) => setTimeout(r, 5))
    ac.abort()
    await expect(async () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      for await (const _evt of iter) {
        // 不应进入
      }
    }).rejects.toThrow()
  })
})
