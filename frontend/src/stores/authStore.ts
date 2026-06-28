import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { authApi } from '@/api/authApi'
import type { LoginResponse } from '@/types/auth'

export const useAuthStore = defineStore('auth', () => {
  // State
  const token = ref<string | null>(sessionStorage.getItem('token'))
  const username = ref<string | null>(sessionStorage.getItem('username'))
  const orgId = ref<string | null>(sessionStorage.getItem('orgId'))

  // Getters
  const isAuthenticated = computed(() => !!token.value)

  // Actions
  async function login(email: string, password: string): Promise<boolean> {
    try {
      const res: LoginResponse = await authApi.login(email, password)

      // orgId=null 时提示错误，不存储 token
      if (!res.orgId) {
        ElMessage.error('账号未分配组织，请联系管理员')
        return false
      }

      // 存储到 state
      token.value = res.token
      username.value = email
      orgId.value = res.orgId

      // 持久化到 sessionStorage
      sessionStorage.setItem('token', res.token)
      sessionStorage.setItem('username', email)
      sessionStorage.setItem('orgId', res.orgId)

      return true
    } catch {
      return false
    }
  }

  function logout() {
    token.value = null
    username.value = null
    orgId.value = null
    sessionStorage.removeItem('token')
    sessionStorage.removeItem('username')
    sessionStorage.removeItem('orgId')
    router.push('/login')
  }

  return { token, username, orgId, isAuthenticated, login, logout }
})
