import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '../chatStore'
import { useKbStore } from '../kbStore'

// Mock queryApi
vi.mock('@/api/queryApi', () => ({
  stream: vi.fn()
}))

import { stream } from '@/api/queryApi'

describe('chatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('多 kbId 历史隔离', () => {
    const store = useChatStore()
    
    store.handleChunk('answer1')
    store.handleDone('kb-1')
    
    store.handleChunk('answer2')
    store.handleDone('kb-2')
    
    expect(store.getHistory('kb-1')).toHaveLength(1)
    expect(store.getHistory('kb-1')[0].content).toBe('answer1')
    expect(store.getHistory('kb-2')).toHaveLength(1)
    expect(store.getHistory('kb-2')[0].content).toBe('answer2')
  })

  it('chunk 事件拼接 currentAnswer', () => {
    const store = useChatStore()
    
    store.handleChunk('Hello')
    store.handleChunk(' World')
    
    expect(store.currentAnswer).toBe('Hello World')
  })

  it('done 事件归档 Message + 清空 currentAnswer', () => {
    const store = useChatStore()
    
    store.handleChunk('test answer')
    store.handleDone('kb-1')
    
    expect(store.currentAnswer).toBe('')
    expect(store.getHistory('kb-1')).toHaveLength(1)
    expect(store.getHistory('kb-1')[0]).toEqual({
      role: 'assistant',
      content: 'test answer',
      sources: undefined
    })
  })

  it('source 事件追加 pendingSources', () => {
    const store = useChatStore()
    
    store.handleSource({ documentName: 'doc1.pdf', content: 'snippet', score: 0.95 })
    store.handleSource({ documentName: 'doc2.pdf', content: 'snippet2', score: 0.85 })
    
    expect(store.pendingSources).toHaveLength(2)
    expect(store.pendingSources[0].documentName).toBe('doc1.pdf')
  })

  it('error 事件插入错误气泡', () => {
    const store = useChatStore()
    
    store.handleError('查询失败', 'kb-1')
    
    expect(store.getHistory('kb-1')).toHaveLength(1)
    expect(store.getHistory('kb-1')[0]).toEqual({
      role: 'error',
      content: '查询失败'
    })
    expect(store.streaming).toBe(false)
  })

  it('switchKb 按顺序 abort/clear/switch', () => {
    const store = useChatStore()
    const kbStore = useKbStore()
    
    const abortSpy = vi.fn()
    store.currentAbortController = { abort: abortSpy } as any
    store.currentAnswer = 'streaming...'
    store.streaming = true
    
    store.switchKb('new-kb')
    
    expect(abortSpy).toHaveBeenCalled()
    expect(store.currentAnswer).toBe('')
    expect(store.streaming).toBe(false)
    expect(kbStore.selectedKbId).toBe('new-kb')
  })
})
