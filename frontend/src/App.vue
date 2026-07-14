<script setup lang="ts">
import { RouterView } from 'vue-router'
import AppHeader from './components/AppHeader.vue'
</script>

<template>
  <el-container>
    <el-header>
      <AppHeader />
    </el-header>
    <el-main>
      <RouterView />
    </el-main>
  </el-container>
</template>

<style scoped>
.el-header {
  padding: 0;
  height: auto;
}
.el-main {
  padding: 20px;
  background: var(--brand-bg);
  min-height: calc(100vh - 57px);
}
</style>
