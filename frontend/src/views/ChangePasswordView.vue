<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/authStore'

const router = useRouter()
const authStore = useAuthStore()
const form = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })
const submitting = ref(false)

async function handleSubmit() {
  if (!form.value.oldPassword || !form.value.newPassword) {
    ElMessage.warning('请填写旧密码和新密码')
    return
  }
  if (form.value.newPassword !== form.value.confirmPassword) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  if (form.value.newPassword.length < 8) {
    ElMessage.warning('新密码至少 8 位')
    return
  }

  submitting.value = true
  try {
    await http.post('/api/v1/auth/change-password', {
      oldPassword: form.value.oldPassword,
      newPassword: form.value.newPassword
    })
    ElMessage.success('密码修改成功，请重新登录')
    authStore.logout()
  } catch {
    // http.ts 拦截器已处理错误提示
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="change-password-page">
    <el-card class="change-password-card">
      <template #header>
        <span>修改密码</span>
      </template>
      <el-form @submit.prevent="handleSubmit">
        <el-form-item label="旧密码">
          <el-input v-model="form.oldPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="form.newPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="form.confirmPassword" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">
            确认修改
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.change-password-page {
  display: flex;
  justify-content: center;
  padding-top: 80px;
}
.change-password-card {
  width: 400px;
}
</style>
