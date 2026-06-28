<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useTeamStore } from '@/stores/teamStore'

const teamStore = useTeamStore()

// 新建弹窗
const createDialogVisible = ref(false)
const teamForm = ref({ name: '' })
const createLoading = ref(false)

onMounted(() => {
  teamStore.loadTeams()
})

function openCreateDialog() {
  teamForm.value.name = ''
  createDialogVisible.value = true
}

async function handleCreate() {
  if (!teamForm.value.name.trim()) {
    ElMessage.warning('请输入团队名称')
    return
  }
  createLoading.value = true
  const ok = await teamStore.createTeam(teamForm.value.name.trim())
  createLoading.value = false
  if (ok) {
    ElMessage.success('团队创建成功')
    createDialogVisible.value = false
  }
}

function retryLoad() {
  teamStore.loadTeams()
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN')
}
</script>

<template>
  <div class="admin-teams">
    <div class="page-header">
      <h2>团队管理</h2>
      <el-button type="primary" @click="openCreateDialog">新建团队</el-button>
    </div>

    <!-- 加载失败 -->
    <el-alert
      v-if="teamStore.error"
      :title="teamStore.error"
      type="error"
      show-icon
      :closable="false"
    >
      <el-button size="small" @click="retryLoad">重试</el-button>
    </el-alert>

    <!-- 空状态 -->
    <el-empty
      v-if="!teamStore.loading && !teamStore.error && teamStore.teams.length === 0"
      description="暂无团队"
    >
      <el-button type="primary" @click="openCreateDialog">创建第一个团队</el-button>
    </el-empty>

    <!-- 团队列表 -->
    <el-table
      v-if="teamStore.teams.length > 0"
      v-loading="teamStore.loading"
      :data="teamStore.teams"
      stripe
      style="width: 100%"
    >
      <el-table-column prop="name" label="团队名称" min-width="200" />
      <el-table-column label="创建时间" width="200">
        <template #default="{ row }">
          {{ formatTime(row.createdAt) }}
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建弹窗 -->
    <el-dialog v-model="createDialogVisible" title="新建团队" width="420px">
      <el-form :model="teamForm" label-width="80px">
        <el-form-item label="团队名称">
          <el-input v-model="teamForm.name" placeholder="输入团队名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createLoading" @click="handleCreate">
          确认创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-teams {
  max-width: 960px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h2 {
  margin: 0;
  font-size: 20px;
}
</style>
