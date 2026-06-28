import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/authStore'
import router from '@/router'

const http = axios.create({
  baseURL: '',
  timeout: 15000
})

// 请求拦截器：注入 Authorization + X-Org-Id
http.interceptors.request.use((config) => {
  const authStore = useAuthStore()
  if (authStore.token) {
    config.headers.Authorization = `Bearer ${authStore.token}`
  }
  if (authStore.orgId) {
    config.headers['X-Org-Id'] = authStore.orgId
  }
  return config
})

// 响应拦截器：解包 ApiResponse envelope
http.interceptors.response.use(
  (response) => {
    const { code, message, data } = response.data

    // HTTP 2xx + code=0：返回业务数据
    if (code === 0) {
      return data
    }

    // HTTP 2xx + code=202：PENDING_CLEANUP，透传给调用方
    if (code === 202) {
      return { code: 202, message }
    }

    // HTTP 2xx + code≠0 且 code≠202：业务错误
    ElMessage.error(message || '请求失败')
    return Promise.reject(new Error(message || '请求失败'))
  },
  (error) => {
    // HTTP 401：清除认证，跳转登录
    if (error.response?.status === 401) {
      const authStore = useAuthStore()
      authStore.logout()
      router.push('/login')
      ElMessage.error('认证已过期，请重新登录')
      return Promise.reject(error)
    }

    // HTTP 4xx/5xx：提示错误
    const msg = error.response?.data?.message || error.message || '网络错误'
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

export default http
