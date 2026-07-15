<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Close, Delete, RefreshRight, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { documentsApi } from '@/api/documentsApi'
import { INGESTION_IN_FLIGHT_STATES, type Document, type IngestionStatus } from '@/types/ingestion'

/** 同时进行的上传请求数上限；避免一次选择几十个文件时把浏览器/网关连接数打满。 */
const MAX_CONCURRENT_UPLOADS = 3

/** 文档列表每页展示数量。后端 GET /api/v1/documents 目前一次性返回全部文档
 * （分页仍是 TODOS.md 里的后端待办），这里先做前端分页，避免长列表把整页撑爆。 */
const PAGE_SIZE = 20

type UploadItemStatus = 'pending' | 'uploading' | 'success' | 'error'

interface UploadQueueItem {
  id: string
  file: File
  status: UploadItemStatus
  progress: number
  errorMessage?: string
}

const props = defineProps<{ kbId: string }>()

const documents = ref<Document[]>([])
const loading = ref(false)
const uploadQueue = ref<UploadQueueItem[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const currentPage = ref(1)
let pollTimer: ReturnType<typeof setInterval> | undefined
let activeUploadCount = 0

const uploading = computed(() => uploadQueue.value.some((item) => item.status === 'pending' || item.status === 'uploading'))
const pagedDocuments = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return documents.value.slice(start, start + PAGE_SIZE)
})

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

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files ? Array.from(input.files) : []
  input.value = '' // 允许用户重新选择同名文件
  if (files.length === 0) return
  for (const file of files) {
    uploadQueue.value.push({ id: `${file.name}-${file.size}-${Date.now()}-${Math.random()}`, file, status: 'pending', progress: 0 })
  }
  pumpUploadQueue()
}

/** 并发上限调度器：每有一个上传槽位空出来，就从队列里取下一个待上传项。 */
function pumpUploadQueue() {
  while (activeUploadCount < MAX_CONCURRENT_UPLOADS) {
    const next = uploadQueue.value.find((item) => item.status === 'pending')
    if (!next) break
    void runUpload(next)
  }
}

async function runUpload(item: UploadQueueItem) {
  activeUploadCount += 1
  item.status = 'uploading'
  item.progress = 0
  try {
    await documentsApi.upload(props.kbId, item.file, (value) => { item.progress = value })
    item.status = 'success'
    await loadDocuments(true)
  } catch (error) {
    item.status = 'error'
    item.errorMessage = error instanceof Error ? error.message : '上传失败'
  } finally {
    activeUploadCount -= 1
    pumpUploadQueue()
  }
}

/** 失败的文件允许原样重新入队重试，不需要用户重新选择文件。 */
function retryUploadItem(item: UploadQueueItem) {
  item.status = 'pending'
  item.errorMessage = undefined
  pumpUploadQueue()
}

function dismissUploadItem(item: UploadQueueItem) {
  uploadQueue.value = uploadQueue.value.filter((entry) => entry !== item)
}

function clearFinishedUploads() {
  uploadQueue.value = uploadQueue.value.filter((item) => item.status === 'pending' || item.status === 'uploading')
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

/** 文档被删除后，若当前页超出了剩余页数（如删掉了最后一页的最后一条），回退到最后一页。 */
watch(documents, () => {
  const maxPage = Math.max(1, Math.ceil(documents.value.length / PAGE_SIZE))
  if (currentPage.value > maxPage) currentPage.value = maxPage
})

watch(() => props.kbId, () => { currentPage.value = 1; void loadDocuments() })
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
        <input
          ref="fileInput"
          class="file-input"
          type="file"
          multiple
          accept=".md,.markdown,.txt,.pdf,.docx,.pptx,.srt,.vtt,.json,.yaml,.yml,.xml,.png,.jpg,.jpeg,.tif,.tiff,.mp3,.wav,.mp4,.mov,.mkv,.java,.py,.js,.ts,.tsx,.jsx,.go,.rs,.sql,.sh,.bash,.properties,.conf,.ini,.gradle,.pom"
          @change="handleFileChange"
        />
      </div>
    </header>

    <div v-if="uploadQueue.length > 0" class="upload-queue" data-testid="upload-queue">
      <div class="upload-queue-header">
        <span>本次选择 {{ uploadQueue.length }} 个文件</span>
        <el-button text size="small" @click="clearFinishedUploads">清除已完成</el-button>
      </div>
      <ul class="upload-queue-list">
        <li v-for="item in uploadQueue" :key="item.id" class="upload-queue-item">
          <span class="upload-queue-name" :title="item.file.name">{{ item.file.name }}</span>
          <el-progress
            v-if="item.status === 'uploading' || item.status === 'pending'"
            class="upload-queue-progress"
            :percentage="item.progress"
            :indeterminate="item.status === 'pending' || item.progress === 0"
          />
          <el-tag v-else-if="item.status === 'success'" type="success" effect="light">已上传</el-tag>
          <el-tag v-else type="danger" effect="light" :title="item.errorMessage">失败：{{ item.errorMessage || '未知错误' }}</el-tag>
          <el-button v-if="item.status === 'error'" text type="primary" size="small" @click="retryUploadItem(item)">重试</el-button>
          <el-button text size="small" :icon="Close" @click="dismissUploadItem(item)" />
        </li>
      </ul>
    </div>

    <el-table v-loading="loading" :data="pagedDocuments" height="100%" empty-text="暂无文档，请上传技术资料" class="document-table">
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

    <el-pagination
      v-if="documents.length > PAGE_SIZE"
      v-model:current-page="currentPage"
      :page-size="PAGE_SIZE"
      :total="documents.length"
      layout="total, prev, pager, next"
      class="document-pagination"
    />
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
.document-pagination { flex: 0 0 auto; justify-content: flex-end; padding-top: 4px; }
.upload-queue { border: 1px solid var(--el-border-color); border-radius: 6px; padding: 10px 12px; background: var(--el-fill-color-lighter); }
.upload-queue-header { display: flex; align-items: center; justify-content: space-between; font-size: 13px; color: var(--el-text-color-secondary); margin-bottom: 6px; }
.upload-queue-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; max-height: 180px; overflow-y: auto; }
.upload-queue-item { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.upload-queue-name { flex: 0 0 auto; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.upload-queue-progress { flex: 1; min-width: 80px; }
@media (max-width: 760px) { .panel-header { flex-direction: column; } .header-actions { justify-content: flex-start; } }
</style>
