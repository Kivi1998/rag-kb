import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

// Mock components
vi.mock('@/views/LoginView.vue', () => ({ default: { template: '<div>Login</div>' } }))
vi.mock('@/views/KbWorkspaceView.vue', () => ({ default: { template: '<div>Workspace</div>' } }))

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/login',
        name: 'login',
        component: () => import('@/views/LoginView.vue')
      },
      {
        path: '/',
        redirect: '/kb'
      },
      {
        path: '/kb',
        name: 'kb',
        component: () => import('@/views/KbWorkspaceView.vue'),
        meta: { requiresAuth: true }
      }
    ]
  })
}

describe('router', () => {
  let router: ReturnType<typeof createTestRouter>

  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    router = createTestRouter()
    
    // Add beforeEach guard
    router.beforeEach((to) => {
      const authStore = useAuthStore()
      if (to.meta.requiresAuth && !authStore.token) {
        return { name: 'login' }
      }
      if (to.name === 'login' && authStore.token) {
        return { name: 'kb' }
      }
    })
  })

  it('未登录访问 /kb 跳转 /login', async () => {
    await router.push('/kb')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('已登录访问 / 重定向 /kb', async () => {
    const authStore = useAuthStore()
    authStore.token = 'test-token'
    
    await router.push('/')
    expect(router.currentRoute.value.path).toBe('/kb')
  })

  it('已登录访问 /login 跳转 /kb', async () => {
    const authStore = useAuthStore()
    authStore.token = 'test-token'
    
    await router.push('/login')
    expect(router.currentRoute.value.path).toBe('/kb')
  })
})
