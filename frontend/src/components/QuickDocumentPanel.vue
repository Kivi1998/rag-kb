<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Close, Loading, Paperclip } from '@element-plus/icons-vue'
import { quickDocumentApi, type QuickDocumentSummary } from '@/api/quickDocumentApi'

/** 只用于前端展示"已用 X/15000 字符"；真正的额度校验在后端，这里的数字仅供参考，
 * 后端上限变化（rag.quick-document.max-total-characters）不会同步到这个展示值。 */
const DISPLAY_QUOTA_CHARACTERS = 15000

/**
 * 会话是懒创建的：用户可能在发第一条消息之前就想先挂一个临时文档。`ensureSession`
 * 由父组件（ChatPanel）注入——复用它自己在 ask() 里"发第一条消息时懒创建会话"的
 * 同一段逻辑（含 localStorage 记录），避免这里重复实现一遍创建会话 + 注入认证头。
 */
const props = defineProps<{ kbId: string; sessionId: string | null; ensureSession: () => Promise<string | null> }>()

const documents = ref<QuickDocumentSummary[]>([])
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const usedCharacters = computed(() => documents.value.reduce((sum, doc) => sum + doc.characterCount, 0))

async function refresh() {
  if (!props.sessionId) {
    documents.value = []
    return
  }
  try {
    documents.value = await quickDocumentApi.list(props.kbId, props.sessionId)
  } catch {
    // http.ts 拦截器已经弹出错误提示，这里只需要保持列表不变，不重复报错。
  }
}

function chooseFile() {
  fileInput.value?.click()
}

async function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许用户重新选择同名文件
  if (!file) return
  uploading.value = true
  try {
    const sessionId = props.sessionId ?? (await props.ensureSession())
    if (!sessionId) return
    await quickDocumentApi.upload(props.kbId, sessionId, file)
    await refresh()
  } catch {
    // http.ts 拦截器已经弹出错误提示（超额度/格式不支持等），不重复处理。
  } finally {
    uploading.value = false
  }
}

async function remove(docId: string) {
  if (!props.sessionId) return
  try {
    await quickDocumentApi.remove(props.kbId, props.sessionId, docId)
    await refresh()
  } catch {
    // 同上，拦截器已提示错误。
  }
}

watch(() => props.sessionId, () => void refresh(), { immediate: true })

defineExpose({ refresh })
</script>

<template>
  <div class="quick-document-panel" data-testid="quick-document-panel">
    <input ref="fileInput" type="file" class="hidden-input" @change="handleFileChange" />
    <div class="quick-document-header">
      <el-button size="small" :icon="Paperclip" :loading="uploading" @click="chooseFile">
        临时文档
      </el-button>
      <span v-if="documents.length" class="quota-hint">
        已用 {{ usedCharacters }}/{{ DISPLAY_QUOTA_CHARACTERS }} 字符
      </span>
    </div>
    <ul v-if="documents.length" class="quick-document-list">
      <li v-for="doc in documents" :key="doc.docId" class="quick-document-item">
        <span class="quick-document-name" :title="doc.filename">{{ doc.filename }}</span>
        <span class="quick-document-size">{{ doc.characterCount }} 字</span>
        <el-icon class="quick-document-remove" @click="remove(doc.docId)"><Close /></el-icon>
      </li>
    </ul>
    <p v-if="uploading" class="quick-document-uploading">
      <el-icon class="is-loading"><Loading /></el-icon> 正在解析上传的文档…
    </p>
  </div>
</template>

<style scoped>
.quick-document-panel { display: flex; flex-direction: column; gap: 6px; }
.hidden-input { display: none; }
.quick-document-header { display: flex; align-items: center; gap: 10px; }
.quota-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.quick-document-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.quick-document-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 14px;
  background: var(--el-fill-color-light);
  font-size: 12px;
  max-width: 220px;
}
.quick-document-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.quick-document-size { flex-shrink: 0; color: var(--el-text-color-secondary); }
.quick-document-remove { cursor: pointer; color: var(--el-text-color-secondary); flex-shrink: 0; }
.quick-document-remove:hover { color: var(--el-color-danger); }
.quick-document-uploading {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
