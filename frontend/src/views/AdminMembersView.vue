<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useMemberStore } from '@/stores/memberStore'
import { useAuthStore } from '@/stores/authStore'
import type { MemberRole } from '@/types/member'

const memberStore = useMemberStore()
const authStore = useAuthStore()
const isOwner = authStore.role === 'OWNER'

// 邀请弹窗
const inviteDialogVisible = ref(false)
const inviteForm = ref({ subjectId: '', role: 'MEMBER' as MemberRole })
const inviteLoading = ref(false)

// 临时密码展示
const tempPasswordVisible = ref(false)
const tempPassword = ref('')

onMounted(() => {
  memberStore.loadMembers()
})

function openInviteDialog() {
  inviteForm.value = { subjectId: '', role: 'MEMBER' }
  inviteDialogVisible.value = true
}

async function handleInvite() {
  if (!inviteForm.value.subjectId.trim()) {
    ElMessage.warning('请输入用户 ID')
    return
  }
  inviteLoading.value = true
  const ok = await memberStore.inviteMember(inviteForm.value.subjectId, inviteForm.value.role)
  inviteLoading.value = false
  if (ok) {
    ElMessage.success('成员添加成功')
    inviteDialogVisible.value = false
  }
}

async function handleRoleChange(memberId: string, newRole: MemberRole) {
  await memberStore.updateRole(memberId, newRole)
}

async function handleResetPassword(memberId: string, subjectId: string) {
  try {
    await ElMessageBox.confirm(
      `确认重置用户 ${subjectId} 的密码？重置后将生成临时密码。`,
      '重置密码',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return // 用户取消
  }

  const pwd = await memberStore.resetPassword(memberId)
  if (pwd) {
    tempPassword.value = pwd
    tempPasswordVisible.value = true
  }
}

function copyTempPassword() {
  navigator.clipboard.writeText(tempPassword.value)
  ElMessage.success('已复制到剪贴板')
}

function retryLoad() {
  memberStore.loadMembers()
}
</script>

<template>
  <div class="admin-members">
    <div class="page-header">
      <h2>成员管理</h2>
      <el-button type="primary" @click="openInviteDialog">添加成员</el-button>
    </div>

    <!-- 加载失败 -->
    <el-alert
      v-if="memberStore.error"
      :title="memberStore.error"
      type="error"
      show-icon
      :closable="false"
    >
      <el-button size="small" @click="retryLoad">重试</el-button>
    </el-alert>

    <!-- 成员列表 -->
    <el-table
      v-loading="memberStore.loading"
      :data="memberStore.members"
      stripe
      style="width: 100%"
    >
      <el-table-column prop="subjectId" label="用户 ID" min-width="200" />
      <el-table-column label="角色" width="180">
        <template #default="{ row }">
          <template v-if="isOwner">
            <el-select
              :model-value="row.role"
              size="small"
              @change="(val: MemberRole) => handleRoleChange(row.id, val)"
            >
              <el-option label="OWNER" value="OWNER" />
              <el-option label="ADMIN" value="ADMIN" />
              <el-option label="MEMBER" value="MEMBER" />
            </el-select>
          </template>
          <template v-else>
            <el-tag
              :type="row.role === 'OWNER' ? 'danger' : row.role === 'ADMIN' ? 'warning' : 'info'"
              size="small"
            >
              {{ row.role }}
            </el-tag>
          </template>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="warning"
            size="small"
            @click="handleResetPassword(row.id, row.subjectId)"
          >
            重置密码
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 邀请弹窗 -->
    <el-dialog v-model="inviteDialogVisible" title="添加成员" width="420px">
      <el-form :model="inviteForm" label-width="80px">
        <el-form-item label="用户 ID">
          <el-input v-model="inviteForm.subjectId" placeholder="输入用户 ID（userId）" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="inviteForm.role" style="width: 100%">
            <el-option label="ADMIN" value="ADMIN" />
            <el-option label="MEMBER" value="MEMBER" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="inviteDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="inviteLoading" @click="handleInvite">
          确认添加
        </el-button>
      </template>
    </el-dialog>

    <!-- 临时密码弹窗 -->
    <el-dialog v-model="tempPasswordVisible" title="密码重置成功" width="420px">
      <p>临时密码已生成，请复制并告知用户：</p>
      <el-input :model-value="tempPassword" readonly>
        <template #append>
          <el-button @click="copyTempPassword">复制</el-button>
        </template>
      </el-input>
      <p class="hint">用户首次登录后需修改密码。</p>
      <template #footer>
        <el-button type="primary" @click="tempPasswordVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-members {
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
.hint {
  margin-top: 12px;
  color: #909399;
  font-size: 13px;
}
</style>
