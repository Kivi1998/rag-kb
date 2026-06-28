import { ref, watch, onUnmounted, type Ref } from 'vue'
import { KbDocumentStatus } from '@/types/document'
import { docApi } from '@/api/docApi'
import type { KbDocument } from '@/types/document'

const POLL_INTERVAL = 3000
const TIMEOUT = 10 * 60 * 1000 // 10 分钟

export function useDocumentPolling(kbId: Ref<string | null>) {
  const docs = ref<KbDocument[]>([])
  const isPolling = ref(false)
  const timedOut = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null
  let startTime = 0
  let running = false // 防止并发 poll 执行

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    isPolling.value = false
  }

  async function poll() {
    if (running) return
    const currentKbId = kbId.value
    if (!currentKbId) return

    running = true
    try {
      // 1. 获取全量列表
      docs.value = await docApi.list(currentKbId)

      // 2. 对每个 PARSING 文档额外调详情接口触发状态刷新
      const parsingDocs = docs.value.filter((d) => d.status === KbDocumentStatus.PARSING)
      for (const doc of parsingDocs) {
        if (kbId.value !== currentKbId) return // kbId 已切换，丢弃本次结果
        const updated = await docApi.get(currentKbId, doc.id)
        const idx = docs.value.findIndex((d) => d.id === doc.id)
        if (idx !== -1) {
          docs.value[idx] = updated
        }
      }

      if (kbId.value !== currentKbId) return

      // 3. 检查是否全部完成
      const hasPending = docs.value.some(
        (d) => d.status === KbDocumentStatus.UPLOADING || d.status === KbDocumentStatus.PARSING
      )
      if (!hasPending) {
        stopPolling()
        return
      }

      // 4. 检查超时
      if (Date.now() - startTime > TIMEOUT) {
        timedOut.value = true
        stopPolling()
      }
    } catch {
      // 错误时继续轮询
    } finally {
      running = false
    }
  }

  function startPolling() {
    stopPolling()
    running = false
    startTime = Date.now()
    timedOut.value = false
    isPolling.value = true
    poll()
    timer = setInterval(poll, POLL_INTERVAL)
  }

  // 监听 kbId 变化（immediate: 首次挂载时 kbId 已有值也立即启动）
  watch(kbId, (newId) => {
    if (newId) {
      startPolling()
    } else {
      stopPolling()
      docs.value = []
    }
  }, { immediate: true })

  onUnmounted(() => {
    stopPolling()
  })

  return { docs, isPolling, timedOut, refresh: poll }
}
