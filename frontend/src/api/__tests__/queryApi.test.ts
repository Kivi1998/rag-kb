import { describe, it, expect, vi, beforeEach } from 'vitest'
import { stream } from '../queryApi'

// Mock authStore
vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({
    token: 'test-token',
    orgId: 'org-1'
  })
}))

// Mock fetch
const mockFetch = vi.fn()
global.fetch = mockFetch

describe('queryApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('SSE 多行格式解析', async () => {
    const encoder = new TextEncoder()
    const chunks = [
      encoder.encode('event:chunk\ndata:{"content":"Hello"}\n\n'),
      encoder.encode('event:chunk\ndata:{"content":" World"}\n\n'),
      encoder.encode('event:done\ndata:{}\n\n')
    ]

    let chunkIndex = 0
    mockFetch.mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: async () => {
            if (chunkIndex < chunks.length) {
              return { done: false, value: chunks[chunkIndex++] }
            }
            return { done: true }
          },
          releaseLock: vi.fn()
        })
      }
    })

    const events = []
    const generator = stream('kb-1', 'test question', new AbortController().signal)
    for await (const event of generator) {
      events.push(event)
    }

    expect(events).toHaveLength(3)
    expect(events[0].eventType).toBe('chunk')
    expect(events[0].content).toBe('Hello')
    expect(events[1].content).toBe(' World')
    expect(events[2].eventType).toBe('done')
  })

  it('HTTP 4xx 触发错误', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 401,
      statusText: 'Unauthorized'
    })

    const generator = stream('kb-1', 'test', new AbortController().signal)
    
    await expect(async () => {
      for await (const _ of generator) {
        // Should not reach here
      }
    }).rejects.toThrow('HTTP 401')
  })

  it('手动注入 Authorization + X-Org-Id 头', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: async () => ({ done: true }),
          releaseLock: vi.fn()
        })
      }
    })

    const generator = stream('kb-1', 'test', new AbortController().signal)
    for await (const _ of generator) {
      // consume
    }

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/v1/knowledge-bases/kb-1/query',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer test-token',
          'X-Org-Id': 'org-1'
        }),
        body: JSON.stringify({ question: 'test' })
      })
    )
  })
})
