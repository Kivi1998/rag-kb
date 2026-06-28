import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { useDocumentPolling } from '../useDocumentPolling'
import { KbDocumentStatus } from '@/types/document'

// Mock docApi
vi.mock('@/api/docApi', () => ({
  docApi: {
    list: vi.fn(),
    get: vi.fn()
  }
}))

import { docApi } from '@/api/docApi'

describe('useDocumentPolling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('初始状态为空', () => {
    const kbId = ref<string | null>(null)
    const { docs, isPolling, timedOut } = useDocumentPolling(kbId)
    
    expect(docs.value).toEqual([])
    expect(isPolling.value).toBe(false)
    expect(timedOut.value).toBe(false)
  })

  it('refresh 调用 docApi.list', async () => {
    vi.mocked(docApi.list).mockResolvedValue([
      { id: '1', name: 'test.pdf', status: KbDocumentStatus.READY, createdAt: '2024-01-01' }
    ])

    const kbId = ref('kb-1')
    const { refresh, docs } = useDocumentPolling(kbId)
    
    await refresh()
    
    expect(docApi.list).toHaveBeenCalledWith('kb-1')
    expect(docs.value).toHaveLength(1)
  })

  it('refresh 对 PARSING 文档额外调详情接口', async () => {
    vi.mocked(docApi.list).mockResolvedValue([
      { id: '1', name: 'test.pdf', status: KbDocumentStatus.PARSING, createdAt: '2024-01-01' }
    ])
    vi.mocked(docApi.get).mockResolvedValue(
      { id: '1', name: 'test.pdf', status: KbDocumentStatus.READY, createdAt: '2024-01-01' }
    )

    const kbId = ref('kb-1')
    const { refresh, docs } = useDocumentPolling(kbId)
    
    await refresh()
    
    expect(docApi.get).toHaveBeenCalledWith('kb-1', '1')
    expect(docs.value[0].status).toBe(KbDocumentStatus.READY)
  })

  it('kbId 为 null 时不清空文档', async () => {
    const kbId = ref<string | null>(null)
    const { docs } = useDocumentPolling(kbId)
    
    // docs 应该是空数组
    expect(docs.value).toEqual([])
  })
})
