<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/authStore'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.role === 'OWNER' || authStore.role === 'ADMIN')
</script>

<template>
  <div class="app-header">
    <div class="header-left">
      <span class="logo">rag-kb</span>
      <nav v-if="authStore.isAuthenticated" class="nav-links">
        <router-link to="/kb" class="nav-link">知识库</router-link>
        <router-link v-if="isAdmin" to="/admin" class="nav-link">管理</router-link>
      </nav>
    </div>
    <div class="user-info" v-if="authStore.isAuthenticated">
      <span>{{ authStore.username }}</span>
      <el-button text @click="authStore.logout()">退出</el-button>
    </div>
  </div>
</template>

<style scoped>
.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px;
  background: var(--brand-surface);
  color: var(--brand-ink);
  border-bottom: 1px solid var(--brand-border);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 28px;
}
.logo {
  font-family: var(--brand-font-serif);
  font-size: 19px;
  font-weight: 600;
  color: var(--brand-ink);
}
.nav-links {
  display: flex;
  gap: 20px;
}
.nav-link {
  color: var(--brand-ink-soft);
  text-decoration: none;
  font-size: 14px;
  padding-bottom: 4px;
  border-bottom: 2px solid transparent;
}
.nav-link:hover {
  color: var(--brand-ink);
}
.nav-link.router-link-active {
  color: var(--brand-accent);
  border-bottom-color: var(--brand-accent);
}
.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--brand-ink-soft);
  font-size: 14px;
}
.user-info .el-button {
  color: var(--brand-ink-soft);
}
.user-info .el-button:hover {
  color: var(--brand-accent);
}
</style>
