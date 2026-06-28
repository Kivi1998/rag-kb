import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { kbApi } from '@/api/kbApi'
import type { KnowledgeBase } from '@/types/kb'

export const useKbStore = defineStore('kb', () => {
  // State
  const kbs = ref<KnowledgeBase[]>([])
  const selectedKbId = ref<string | null>(null)

  // Actions
  async function loadKbs() {
    try {
      kbs.value = await kbApi.list()
      // 自动选中第一个 KB
      if (kbs.value.length > 0 && !selectedKbId.value) {
        selectedKbId.value = kbs.value[0].id
      }
    } catch {
      // http.ts 拦截器已处理错误提示
    }
  }

  async function createKb(name: string): Promise<boolean> {
    try {
      const kb = await kbApi.create(name)
      kbs.value.push(kb)
      selectedKbId.value = kb.id
      return true
    } catch {
      return false
    }
  }

  async function renameKb(id: string, name: string): Promise<boolean> {
    try {
      const updated = await kbApi.update(id, name)
      const idx = kbs.value.findIndex((k) => k.id === id)
      if (idx !== -1) {
        kbs.value[idx] = updated
      }
      return true
    } catch {
      return false
    }
  }

  async function deleteKb(id: string): Promise<void> {
    try {
      const res = await kbApi.remove(id)
      if (res.code === 0) {
        // 完全删除
        kbs.value = kbs.value.filter((k) => k.id !== id)
        if (selectedKbId.value === id) {
          selectedKbId.value = kbs.value.length > 0 ? kbs.value[0].id : null
        }
      } else if (res.code === 202) {
        // PENDING_CLEANUP：标记状态
        const kb = kbs.value.find((k) => k.id === id)
        if (kb) {
          kb.status = 'PENDING_CLEANUP'
        }
        ElMessage.warning(res.message || '知识库已标记待清理')
      }
    } catch {
      // http.ts 拦截器已处理错误提示
    }
  }

  return { kbs, selectedKbId, loadKbs, createKb, renameKb, deleteKb }
})
