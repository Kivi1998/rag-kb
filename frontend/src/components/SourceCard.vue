<script setup lang="ts">
import type { Source } from '@/types/query'

defineProps<{ source: Source }>()
</script>

<template>
  <el-card class="source-card" shadow="hover">
    <div class="source-header">
      <span class="doc-name">{{ source.documentName }}</span>
      <el-tag size="small">{{ source.score.toFixed(2) }}</el-tag>
    </div>
    <div class="source-content">{{ source.content.slice(0, 200) }}{{ source.content.length > 200 ? '...' : '' }}</div>
  </el-card>
</template>

<style scoped>
.source-card {
  width: 240px;
  font-size: 12px;
}
.source-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.doc-name {
  font-weight: bold;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-content {
  color: #606266;
  line-height: 1.4;
}
</style>
