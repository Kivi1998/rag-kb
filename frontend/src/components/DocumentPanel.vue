<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Delete, RefreshRight, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { documentsApi } from '@/api/documentsApi'
import { INGESTION_IN_FLIGHT_STATES, type Document, type IngestionStatus } from '@/types/ingestion'

const props = defineProps<{ kbId: string }>()

const documents = ref<Document[]>([])
const loading = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const fileInput = ref<HTMLInputElement | null>(null)
let pollTimer: ReturnType<typeof setInterval> | undefined

const statusMeta: Record<IngestionStatus, { label: string; type: 'info' | 'warning' | 'success' | 'danger' }> = {
  QUEUED: { label: '排队中', type: 'info' },
  PARSING: { label: '解析中', type: 'warning' },
  CHUNKING: { label: '切块中', type: 'warning' },
  EMBEDDING: { label: '向量化中', type: 'warning' },
  INDEXING: { label: '索引中', type: 'warning' },
  READY: { label: '可检索', type: 'success' },
  FAILED: { label: '失败', type: 'danger' },
  DELETING: { label: '删除中', type: 'warning' }
}

const hasActiveJob = computed(() => documents.value.some((document) =>
  INGESTION_IN_FLIGHT_STATES.has(document.status) || document.status === 'DELETING'
))

async function loadDocuments(silent = false) {
  if (!props.kbId) return
  if (!silent) loading.value = true
  try {
    documents.value = await documentsApi.list({ kbId: props.kbId })
  } finally {
    if (!silent) loading.value = false
    resetPolling()
  }
}

function resetPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
  if (hasActiveJob.value) {
    pollTimer = setInterval(() => void loadDocuments(true), 3_000)
  }
}

function chooseFile() {
  fileInput.value?.click()
}

async function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  uploadProgress.value = 0
  try {
    await documentsApi.upload(props.kbId, file, (value) => { uploadProgress.value = value })
    ElMessage.success('文件已上传，正在异步解析与建立索引')
    await loadDocuments(true)
  } finally {
    uploading.value = false
  }
}

async function retry(document: Document) {
  if (!document.jobId) {
    ElMessage.error('该文档缺少摄取任务标识，无法安全重试')
    return
  }
  await documentsApi.retry(props.kbId, document.jobId)
  ElMessage.success('已重新加入摄取队列')
  await loadDocuments(true)
}

async function remove(document: Document) {
  await ElMessageBox.confirm(`确定删除「${document.name}」？删除后将清理原文件和检索索引。`, '删除文档', {
    type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消'
  })
  await documentsApi.remove(props.kbId, document.documentId)
  ElMessage.success('已提交删除请求')
  await loadDocuments(true)
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** Element Plus 表格插槽默认为 DefaultRow；数据源只来自 Document[]，在边界处收紧类型。 */
function asDocument(row: unknown): Document {
  return row as Document
}

watch(() => props.kbId, () => void loadDocuments())
onMounted(() => void loadDocuments())
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <section class="document-panel" data-testid="document-panel">
    <header class="panel-header">
      <div>
        <h2>技术文档</h2>
        <p>上传后将自动解析、切块、向量化并建立检索索引。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="RefreshRight" :loading="loading" @click="loadDocuments()">刷新</el-button>
        <el-button type="primary" :icon="UploadFilled" :loading="uploading" @click="chooseFile">上传文档</el-button>
        <input ref="fileInput" class="file-input" type="file" accept=".md,.markdown,.txt,.pdf,.docx,.json,.yaml,.yml,.xml,.java,.py,.js,.ts,.tsx,.jsx,.go,.rs,.sql,.sh,.bash,.properties,.conf,.ini,.gradle,.pom" @change="handleFileChange" />
      </div>
    </header>

    <el-progress v-if="uploading" :percentage="uploadProgress" :indeterminate="uploadProgress === 0" />

    <el-table v-loading="loading" :data="documents" empty-text="暂无文档，请上传技术资料" class="document-table">
      <el-table-column prop="name" label="文件" min-width="190" show-overflow-tooltip />
      <el-table-column label="大小" width="92">
        <template #default="{ row }">{{ formatBytes(asDocument(row).size) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="105">
        <template #default="{ row }">
          <el-tag :type="statusMeta[asDocument(row).status].type" effect="light">{{ statusMeta[asDocument(row).status].label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="失败原因" min-width="170" show-overflow-tooltip>
        <template #default="{ row }">{{ asDocument(row).errorMessage || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="145" fixed="right">
        <template #default="{ row }">
          <el-button v-if="asDocument(row).retryable" text type="primary" size="small" :disabled="!asDocument(row).jobId" @click="retry(asDocument(row))">重试</el-button>
          <el-button text type="danger" size="small" :icon="Delete" :disabled="asDocument(row).status === 'DELETING'" @click="remove(asDocument(row))">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<style scoped>
.document-panel { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 14px; }
.panel-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.panel-header h2 { margin: 0; font-size: 18px; }
.panel-header p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.header-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.file-input { display: none; }
.document-table { flex: 1; }
@media (max-width: 760px) { .panel-header { flex-direction: column; } .header-actions { justify-content: flex-start; } }
</style>
