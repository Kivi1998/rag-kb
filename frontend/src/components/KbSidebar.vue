<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useKbStore } from '@/stores/kbStore'
import { ElMessageBox, ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import type { KnowledgeBase } from '@/types/kb'

const router = useRouter()

const kbStore = useKbStore()

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

function goToDocuments(kb: KnowledgeBase) {
  router.push({ name: 'kb-documents', params: { kbId: kb.id } })
}

/** 右键菜单三项的统一入口；命令名与 <el-dropdown-item command="..."> 一一对应。 */
function handleCommand(command: 'rename' | 'delete' | 'documents', kb: KnowledgeBase) {
  if (command === 'rename') openRenameDialog(kb)
  else if (command === 'delete') void handleDelete(kb)
  else goToDocuments(kb)
}
</script>

<template>
  <div class="kb-sidebar">
    <div class="header">
      <span>知识库</span>
      <el-button :icon="Plus" circle size="small" @click="showCreateDialog = true" />
    </div>
    <el-menu :default-active="kbStore.selectedKbId || ''" @select="kbStore.selectedKbId = $event">
      <el-menu-item v-for="kb in kbStore.kbs" :key="kb.id" :index="kb.id">
        <el-dropdown
          trigger="contextmenu"
          class="kb-item-dropdown"
          @command="(command: 'rename' | 'delete' | 'documents') => handleCommand(command, kb)"
        >
          <div class="kb-item">
            <span class="kb-name">{{ kb.name }}</span>
            <el-tag v-if="kb.status === 'PENDING_CLEANUP'" type="warning" size="small">待清理</el-tag>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="rename">重命名</el-dropdown-item>
              <el-dropdown-item command="delete">删除</el-dropdown-item>
              <el-dropdown-item command="documents" divided>技术文档</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
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
.kb-item-dropdown {
  display: block;
  width: 100%;
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
</style>
