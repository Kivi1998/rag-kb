<script setup lang="ts">
import { ref } from 'vue'
import { useKbStore } from '@/stores/kbStore'
import { useChatStore } from '@/stores/chatStore'
import { ElMessageBox, ElMessage } from 'element-plus'
import { Plus, Edit, Delete } from '@element-plus/icons-vue'
import type { KnowledgeBase } from '@/types/kb'

const kbStore = useKbStore()
const chatStore = useChatStore()

// 创建 KB 弹窗
const showCreateDialog = ref(false)
const newKbName = ref('')
const creating = ref(false)

// 重命名 KB 弹窗
const showRenameDialog = ref(false)
const renameKbId = ref('')
const renameKbName = ref('')
const renaming = ref(false)

async function handleCreate() {
  if (!newKbName.value.trim()) return
  creating.value = true
  try {
    const success = await kbStore.createKb(newKbName.value.trim())
    if (success) {
      showCreateDialog.value = false
      newKbName.value = ''
      ElMessage.success('创建成功')
    }
  } finally {
    creating.value = false
  }
}

function openRenameDialog(kb: KnowledgeBase) {
  renameKbId.value = kb.id
  renameKbName.value = kb.name
  showRenameDialog.value = true
}

async function handleRename() {
  if (!renameKbName.value.trim()) return
  renaming.value = true
  try {
    const success = await kbStore.renameKb(renameKbId.value, renameKbName.value.trim())
    if (success) {
      showRenameDialog.value = false
      ElMessage.success('重命名成功')
    }
  } finally {
    renaming.value = false
  }
}

async function handleDelete(kb: KnowledgeBase) {
  try {
    await ElMessageBox.confirm(`确定删除知识库「${kb.name}」？`, '确认删除', {
      type: 'warning'
    })
    await kbStore.deleteKb(kb.id)
  } catch {
    // 用户取消
  }
}
</script>

<template>
  <div class="kb-sidebar">
    <div class="header">
      <span>知识库</span>
      <el-button :icon="Plus" circle size="small" @click="showCreateDialog = true" />
    </div>
    <el-menu :default-active="kbStore.selectedKbId || ''" @select="chatStore.switchKb($event)">
      <el-menu-item v-for="kb in kbStore.kbs" :key="kb.id" :index="kb.id">
        <div class="kb-item">
          <span class="kb-name">{{ kb.name }}</span>
          <el-tag v-if="kb.status === 'PENDING_CLEANUP'" type="warning" size="small">待清理</el-tag>
          <div class="kb-actions">
            <el-button :icon="Edit" text size="small" @click.stop="openRenameDialog(kb)" />
            <el-button :icon="Delete" text size="small" @click.stop="handleDelete(kb)" />
          </div>
        </div>
      </el-menu-item>
    </el-menu>

    <!-- 创建弹窗 -->
    <el-dialog v-model="showCreateDialog" title="新建知识库" width="400px">
      <el-form @submit.prevent="handleCreate">
        <el-form-item label="名称">
          <el-input v-model="newKbName" placeholder="请输入知识库名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 重命名弹窗 -->
    <el-dialog v-model="showRenameDialog" title="重命名知识库" width="400px">
      <el-form @submit.prevent="handleRename">
        <el-form-item label="名称">
          <el-input v-model="renameKbName" placeholder="请输入新名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRenameDialog = false">取消</el-button>
        <el-button type="primary" :loading="renaming" @click="handleRename">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kb-sidebar .header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-weight: bold;
}
.kb-item {
  display: flex;
  align-items: center;
  width: 100%;
}
.kb-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kb-actions {
  display: none;
  margin-left: 8px;
}
.kb-item:hover .kb-actions {
  display: flex;
}
</style>
