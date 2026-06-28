<script setup lang="ts">
import { useAuthStore } from '@/stores/authStore'

const authStore = useAuthStore()
</script>

<template>
  <div class="app-header">
    <div class="logo">rag-kb</div>
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
.logo {
  font-size: 18px;
  font-weight: bold;
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
