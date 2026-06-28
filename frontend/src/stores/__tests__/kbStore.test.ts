import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useKbStore } from '../kbStore'

// Mock kbApi
vi.mock('@/api/kbApi', () => ({
  kbApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn()
  }
}))

// Mock ElMessage
vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn()
  }
}))

import { kbApi } from '@/api/kbApi'

describe('kbStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadKbs 加载知识库列表', async () => {
    const mockKbs = [
      { id: '1', name: 'KB 1', status: 'ACTIVE', createdAt: '2024-01-01' },
      { id: '2', name: 'KB 2', status: 'ACTIVE', createdAt: '2024-01-02' }
    ]
    vi.mocked(kbApi.list).mockResolvedValue(mockKbs as any)

    const store = useKbStore()
    await store.loadKbs()

    expect(store.kbs).toEqual(mockKbs)
    expect(store.selectedKbId).toBe('1') // 自动选中第一个
  })

  it('loadKbs 空列表时不自动选中', async () => {
    vi.mocked(kbApi.list).mockResolvedValue([])

    const store = useKbStore()
    await store.loadKbs()

    expect(store.kbs).toEqual([])
    expect(store.selectedKbId).toBeNull()
  })

  it('createKb 创建知识库', async () => {
    const newKb = { id: '3', name: 'New KB', status: 'ACTIVE', createdAt: '2024-01-03' }
    vi.mocked(kbApi.create).mockResolvedValue(newKb as any)

    const store = useKbStore()
    const result = await store.createKb('New KB')

    expect(result).toBe(true)
    expect(store.kbs).toContainEqual(newKb)
    expect(store.selectedKbId).toBe('3')
  })

  it('createKb 失败返回 false', async () => {
    vi.mocked(kbApi.create).mockRejectedValue(new Error('创建失败'))

    const store = useKbStore()
    const result = await store.createKb('Fail KB')

    expect(result).toBe(false)
  })

  it('renameKb 重命名知识库', async () => {
    const updatedKb = { id: '1', name: 'Updated', status: 'ACTIVE', createdAt: '2024-01-01' }
    vi.mocked(kbApi.update).mockResolvedValue(updatedKb as any)

    const store = useKbStore()
    store.kbs = [{ id: '1', name: 'Old', status: 'ACTIVE', createdAt: '2024-01-01' }] as any
    
    const result = await store.renameKb('1', 'Updated')

    expect(result).toBe(true)
    expect(store.kbs[0].name).toBe('Updated')
  })

  it('deleteKb code=0 完全删除', async () => {
    // interceptor 对 code=0 返回内层 data（字符串"已删除"），而非 { code: 0 }
    vi.mocked(kbApi.remove).mockResolvedValue('已删除' as any)

    const store = useKbStore()
    store.kbs = [
      { id: '1', name: 'KB 1', status: 'ACTIVE', createdAt: '2024-01-01' },
      { id: '2', name: 'KB 2', status: 'ACTIVE', createdAt: '2024-01-02' }
    ] as any
    store.selectedKbId = '1'
    
    await store.deleteKb('1')

    expect(store.kbs).toHaveLength(1)
    expect(store.kbs[0].id).toBe('2')
    expect(store.selectedKbId).toBe('2')
  })

  it('deleteKb code=202 标记 PENDING_CLEANUP', async () => {
    vi.mocked(kbApi.remove).mockResolvedValue({ code: 202, message: '待清理' })

    const store = useKbStore()
    store.kbs = [{ id: '1', name: 'KB 1', status: 'ACTIVE', createdAt: '2024-01-01' }] as any
    
    await store.deleteKb('1')

    expect(store.kbs).toHaveLength(1)
    expect(store.kbs[0].status).toBe('PENDING_CLEANUP')
  })
})
