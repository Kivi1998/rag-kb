import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

// Mock components
vi.mock('@/views/LoginView.vue', () => ({ default: { template: '<div>Login</div>' } }))
vi.mock('@/views/KbWorkspaceView.vue', () => ({ default: { template: '<div>Workspace</div>' } }))
vi.mock('@/views/AdminMembersView.vue', () => ({ default: { template: '<div>Members</div>' } }))
vi.mock('@/views/AdminTeamsView.vue', () => ({ default: { template: '<div>Teams</div>' } }))
vi.mock('@/views/ChangePasswordView.vue', () => ({ default: { template: '<div>ChangePassword</div>' } }))

// Mock memberApi
vi.mock('@/api/memberApi', () => ({
  memberApi: { me: vi.fn() }
}))

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
      },
      {
        path: '/change-password',
        name: 'change-password',
        component: () => import('@/views/ChangePasswordView.vue'),
        meta: { requiresAuth: true }
      },
      {
        path: '/admin',
        redirect: '/admin/members',
        meta: { requiresAuth: true, requiresAdmin: true }
      },
      {
        path: '/admin/members',
        name: 'admin-members',
        component: () => import('@/views/AdminMembersView.vue'),
        meta: { requiresAuth: true, requiresAdmin: true }
      },
      {
        path: '/admin/teams',
        name: 'admin-teams',
        component: () => import('@/views/AdminTeamsView.vue'),
        meta: { requiresAuth: true, requiresAdmin: true }
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

    // Add beforeEach guard (matching the real router logic)
    router.beforeEach((to) => {
      const authStore = useAuthStore()
      if (to.meta.requiresAuth && !authStore.token) {
        return { name: 'login' }
      }
      if (to.name === 'login' && authStore.token) {
        return { name: 'kb' }
      }
      if (to.meta.requiresAdmin) {
        if (authStore.role === 'MEMBER' || authStore.role === null) {
          return { name: 'kb' }
        }
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

  it('OWNER 访问 /admin/members 放行', async () => {
    const authStore = useAuthStore()
    authStore.token = 'test-token'
    authStore.role = 'OWNER'

    await router.push('/admin/members')
    expect(router.currentRoute.value.name).toBe('admin-members')
  })

  it('ADMIN 访问 /admin/teams 放行', async () => {
    const authStore = useAuthStore()
    authStore.token = 'test-token'
    authStore.role = 'ADMIN'

    await router.push('/admin/teams')
    expect(router.currentRoute.value.name).toBe('admin-teams')
  })

  it('MEMBER 访问 /admin/members 重定向 /kb', async () => {
    const authStore = useAuthStore()
    authStore.token = 'test-token'
    authStore.role = 'MEMBER'

    await router.push('/admin/members')
    expect(router.currentRoute.value.path).toBe('/kb')
  })

  it('role=null 访问 /admin/teams 重定向 /kb', async () => {
    const authStore = useAuthStore()
    authStore.token = 'test-token'
    authStore.role = null

    await router.push('/admin/teams')
    expect(router.currentRoute.value.path).toBe('/kb')
  })

  it('未登录访问 /admin/members 重定向 /login', async () => {
    await router.push('/admin/members')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('/admin 重定向到 /admin/members', async () => {
    const authStore = useAuthStore()
    authStore.token = 'test-token'
    authStore.role = 'OWNER'

    await router.push('/admin')
    expect(router.currentRoute.value.path).toBe('/admin/members')
  })
})
