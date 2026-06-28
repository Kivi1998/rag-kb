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
    }
  ]
})

router.beforeEach((to) => {
  const authStore = useAuthStore()
  
  if (to.meta.requiresAuth && !authStore.token) {
    return { name: 'login' }
  }
  
  if (to.name === 'login' && authStore.token) {
    return { name: 'kb' }
  }
})

export default router
