<script setup lang="ts">
import { useAuthStore } from '@/stores/authStore'

const authStore = useAuthStore()

const isAdmin = authStore.role === 'OWNER' || authStore.role === 'ADMIN'
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
  padding: 12px 20px;
  background: #409eff;
  color: white;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 24px;
}
.logo {
  font-size: 18px;
  font-weight: bold;
}
.nav-links {
  display: flex;
  gap: 16px;
}
.nav-link {
  color: rgba(255, 255, 255, 0.85);
  text-decoration: none;
  font-size: 14px;
}
.nav-link:hover,
.nav-link.router-link-active {
  color: white;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
}
.user-info .el-button {
  color: white;
}
</style>
