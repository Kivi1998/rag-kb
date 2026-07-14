<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

const router = useRouter()
const authStore = useAuthStore()

const loading = ref(false)
const form = reactive({
  email: '',
  password: ''
})

async function handleLogin() {
  if (loading.value || !form.email || !form.password) return

  loading.value = true
  try {
    const result = await authStore.login(form.email, form.password)
    if (result === 'must_change_password') {
      router.push('/change-password')
    } else if (result === 'ok') {
      router.push('/kb')
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-container">
    <el-card class="login-card">
      <template #header>
        <h2>rag-kb</h2>
        <p class="subtitle">企业技术文档知识库</p>
      </template>
      <el-form @submit.prevent="handleLogin">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" type="email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="请输入密码" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="handleLogin" style="width: 100%">
            登录
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 80vh;
}
.login-card {
  width: 400px;
  border-radius: 12px;
}
.login-card :deep(h2) {
  margin: 0;
  font-size: 22px;
  color: var(--brand-ink);
}
.subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--brand-ink-soft);
}
</style>
