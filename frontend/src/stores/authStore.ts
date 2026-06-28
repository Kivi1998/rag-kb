import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { authApi } from '@/api/authApi'
import { memberApi } from '@/api/memberApi'
import type { LoginResponse } from '@/types/auth'
import type { MemberRole } from '@/types/member'

export const useAuthStore = defineStore('auth', () => {
  // State
  const token = ref<string | null>(sessionStorage.getItem('token'))
  const username = ref<string | null>(sessionStorage.getItem('username'))
  const orgId = ref<string | null>(sessionStorage.getItem('orgId'))
  const role = ref<MemberRole | null>(sessionStorage.getItem('role') as MemberRole | null)
  // 防止 fetchRole 失败后每次导航反复请求
  const roleFetched = ref(sessionStorage.getItem('role') !== null)

  // Getters
  const isAuthenticated = computed(() => !!token.value)

  // Actions
  async function login(email: string, password: string): Promise<'ok' | 'must_change_password' | 'fail'> {
    try {
      const res: LoginResponse = await authApi.login(email, password)

      // orgId=null 时提示错误，不存储 token
      if (!res.orgId) {
        ElMessage.error('账号未分配组织，请联系管理员')
        return 'fail'
      }

      // 存储到 state
      token.value = res.token
      username.value = email
      orgId.value = res.orgId

      // 持久化到 sessionStorage
      sessionStorage.setItem('token', res.token)
      sessionStorage.setItem('username', email)
      sessionStorage.setItem('orgId', res.orgId)

      // 获取当前用户角色
      await fetchRole()

      // 检测 mustChangePassword
      if (res.mustChangePassword) {
        return 'must_change_password'
      }

      return 'ok'
    } catch {
      return 'fail'
    }
  }

  async function fetchRole() {
    try {
      const me = await memberApi.me()
      role.value = me.role
      sessionStorage.setItem('role', me.role)
    } catch {
      // 获取失败时 role 保持 null（可能是新用户尚无 member 记录）
      role.value = null
      sessionStorage.removeItem('role')
    } finally {
      roleFetched.value = true
    }
  }

  function logout() {
    token.value = null
    username.value = null
    orgId.value = null
    role.value = null
    roleFetched.value = false
    sessionStorage.removeItem('token')
    sessionStorage.removeItem('username')
    sessionStorage.removeItem('orgId')
    sessionStorage.removeItem('role')
    router.push('/login')
  }

  return { token, username, orgId, role, roleFetched, isAuthenticated, login, fetchRole, logout }
})
