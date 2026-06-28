import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
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

router.beforeEach((to) => {
  const authStore = useAuthStore()

  // 未登录 → /login
  if (to.meta.requiresAuth && !authStore.token) {
    return { name: 'login' }
  }

  // 已登录访问登录页 → /kb
  if (to.name === 'login' && authStore.token) {
    return { name: 'kb' }
  }

  // /admin/* 需要 OWNER 或 ADMIN 角色
  if (to.meta.requiresAdmin) {
    if (authStore.role === 'MEMBER' || authStore.role === null) {
      return { name: 'kb' }
    }
  }
})

export default router
