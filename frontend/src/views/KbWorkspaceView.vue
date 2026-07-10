<script setup lang="ts">
import { onMounted } from 'vue'
import { useKbStore } from '@/stores/kbStore'
import KbSidebar from '@/components/KbSidebar.vue'

const kbStore = useKbStore()

onMounted(() => {
  kbStore.loadKbs()
})
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <KbSidebar />
    </aside>
    <main class="main-content">
      <el-result
        v-if="kbStore.selectedKbId"
        icon="info"
        title="RAG 核心正在重构"
        sub-title="旧文档摄取与问答链路已下线，新的自研技术文档检索能力完成后将在此接入。"
      />
      <div v-else class="empty-tip">
        <el-empty description="请先选择或创建知识库" />
      </div>
    </main>
  </div>
</template>

<style scoped>
.workspace {
  display: flex;
  height: calc(100vh - 120px);
}
.sidebar {
  width: 220px;
  border-right: 1px solid #e4e7ed;
  padding: 12px;
}
.main-content {
  flex: 1;
  padding: 12px;
  overflow: auto;
}
.empty-tip {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
}
</style>
