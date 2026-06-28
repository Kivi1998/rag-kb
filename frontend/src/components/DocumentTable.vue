<script setup lang="ts">
import { computed } from 'vue'
import { useKbStore } from '@/stores/kbStore'
import { useDocumentPolling } from '@/composables/useDocumentPolling'
import { ElMessageBox, ElMessage } from 'element-plus'
import { Upload, Loading, CircleCheck, Warning } from '@element-plus/icons-vue'
import { KbDocumentStatus } from '@/types/document'
import { docApi } from '@/api/docApi'
import type { KbDocument } from '@/types/document'

const kbStore = useKbStore()
const { docs, isPolling, timedOut, refresh } = useDocumentPolling(
  computed(() => kbStore.selectedKbId)
)

function statusIcon(status: KbDocumentStatus) {
  switch (status) {
    case KbDocumentStatus.UPLOADING:
      return Loading
    case KbDocumentStatus.PARSING:
      return Loading
    case KbDocumentStatus.READY:
      return CircleCheck
    case KbDocumentStatus.FAILED:
      return Warning
  }
}

function statusType(status: KbDocumentStatus) {
  switch (status) {
    case KbDocumentStatus.UPLOADING:
      return 'info'
    case KbDocumentStatus.PARSING:
      return 'primary'
    case KbDocumentStatus.READY:
      return 'success'
    case KbDocumentStatus.FAILED:
      return 'danger'
  }
}

function statusText(status: KbDocumentStatus) {
  switch (status) {
    case KbDocumentStatus.UPLOADING:
      return '上传中'
    case KbDocumentStatus.PARSING:
      return '解析中'
    case KbDocumentStatus.READY:
      return '就绪'
    case KbDocumentStatus.FAILED:
      return '失败'
  }
}

async function handleUpload(uploadFile: any) {
  if (!kbStore.selectedKbId) return
  try {
    await docApi.upload(kbStore.selectedKbId, uploadFile.raw)
    ElMessage.success('上传成功')
    refresh()
  } catch {
    // http.ts 拦截器已处理
  }
}

async function handleDelete(doc: KbDocument) {
  if (!kbStore.selectedKbId) return
  try {
    await ElMessageBox.confirm(`确定删除文档「${doc.name}」？`, '确认删除', { type: 'warning' })
    await docApi.remove(kbStore.selectedKbId, doc.id)
    docs.value = docs.value.filter((d) => d.id !== doc.id)
    ElMessage.success('删除成功')
  } catch {
    // 用户取消
  }
}
</script>

<template>
  <div class="document-table">
    <el-alert v-if="timedOut" type="warning" :closable="false" show-icon
      title="部分文档处理超时，请手动刷新" style="margin-bottom: 12px" />

    <el-upload drag :auto-upload="false" :on-change="handleUpload" :show-file-list="false">
      <el-icon class="el-icon--upload"><Upload /></el-icon>
      <div class="el-upload__text">拖拽文件到此处或<em>点击上传</em></div>
    </el-upload>

    <el-table :data="docs" style="margin-top: 12px">
      <el-table-column prop="name" label="文档名称" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" :icon="statusIcon(row.status)" size="small">
            {{ statusText(row.status) }}
          </el-tag>
          <el-tooltip v-if="row.status === KbDocumentStatus.FAILED && row.errorMessage" :content="row.errorMessage">
            <el-icon style="margin-left: 4px; cursor: pointer"><Warning /></el-icon>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column prop="createdAt" label="上传时间" width="180">
        <template #default="{ row }">
          {{ new Date(row.createdAt).toLocaleString() }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button text type="danger" size="small" @click="handleDelete(row as KbDocument)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="isPolling" class="polling-tip">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>正在刷新文档状态...</span>
    </div>
  </div>
</template>

<style scoped>
.document-table {
  margin-top: 12px;
}
.polling-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  color: #909399;
  font-size: 14px;
}
</style>
