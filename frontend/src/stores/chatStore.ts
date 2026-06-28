import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useKbStore } from '@/stores/kbStore'
import { stream } from '@/api/queryApi'
import type { Message, Source } from '@/types/query'

export const useChatStore = defineStore('chat', () => {
  // State
  const histories = ref<Record<string, Message[]>>({})
  const streaming = ref(false)
  const currentAnswer = ref('')
  const pendingSources = ref<Source[]>([])
  const currentAbortController = ref<AbortController | null>(null)

  // Getters
  function getHistory(kbId: string): Message[] {
    return histories.value[kbId] || []
  }

  // Actions
  function handleChunk(content: string) {
    currentAnswer.value += content
  }

  function handleSource(source: Source) {
    pendingSources.value.push(source)
  }

  function handleDone(kbId: string) {
    if (currentAnswer.value) {
      if (!histories.value[kbId]) {
        histories.value[kbId] = []
      }
      histories.value[kbId].push({
        role: 'assistant',
        content: currentAnswer.value,
        sources: pendingSources.value.length > 0 ? [...pendingSources.value] : undefined
      })
    }
    currentAnswer.value = ''
    pendingSources.value = []
    streaming.value = false
    currentAbortController.value = null
  }

  function handleError(msg: string, kbId: string) {
    if (!histories.value[kbId]) {
      histories.value[kbId] = []
    }
    histories.value[kbId].push({
      role: 'error',
      content: msg
    })
    currentAnswer.value = ''
    pendingSources.value = []
    streaming.value = false
    currentAbortController.value = null
  }

  function switchKb(newKbId: string) {
    // 1. abort 当前请求
    if (currentAbortController.value) {
      currentAbortController.value.abort()
      currentAbortController.value = null
    }
    // 2. 清空状态
    currentAnswer.value = ''
    streaming.value = false
    // 3. 更新 selectedKbId
    const kbStore = useKbStore()
    kbStore.selectedKbId = newKbId
  }

  async function sendQuestion(kbId: string, question: string) {
    if (streaming.value) return

    // 添加用户消息
    if (!histories.value[kbId]) {
      histories.value[kbId] = []
    }
    histories.value[kbId].push({ role: 'user', content: question })

    streaming.value = true
    currentAnswer.value = ''
    pendingSources.value = []
    currentAbortController.value = new AbortController()

    try {
      const generator = stream(kbId, question, currentAbortController.value.signal)
      for await (const event of generator) {
        switch (event.eventType) {
          case 'chunk':
            handleChunk(event.content || '')
            break
          case 'source':
            handleSource({
              documentName: event.documentName || '',
              content: event.content || '',
              score: event.score || 0
            })
            break
          case 'done':
            handleDone(kbId)
            break
          case 'error':
            handleError(event.message || '查询失败', kbId)
            break
        }
      }
      // stream 正常结束但未收到 done 事件
      if (streaming.value) {
        handleDone(kbId)
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        handleError(err.message || '查询失败', kbId)
      }
    } finally {
      streaming.value = false
      currentAbortController.value = null
    }
  }

  return {
    histories, streaming, currentAnswer, pendingSources, currentAbortController,
    getHistory, handleChunk, handleSource, handleDone, handleError, switchKb, sendQuestion
  }
})
