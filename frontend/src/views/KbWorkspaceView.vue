<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useKbStore } from '@/stores/kbStore'
import KbSidebar from '@/components/KbSidebar.vue'
import DocumentPanel from '@/components/DocumentPanel.vue'
import ChatPanel from '@/components/ChatPanel.vue'

const kbStore = useKbStore()
const selectedKb = computed(() => kbStore.kbs.find((kb) => kb.id === kbStore.selectedKbId))

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
      <template v-if="kbStore.selectedKbId">
        <div class="workspace-title"><h1>{{ selectedKb?.name }}</h1><span>技术文档工作区</span></div>
        <div class="workspace-panels">
          <DocumentPanel :kb-id="kbStore.selectedKbId" />
          <ChatPanel :kb-id="kbStore.selectedKbId" />
        </div>
      </template>
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
.workspace-title { display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; }
.workspace-title h1 { margin: 0; font-size: 22px; }
.workspace-title span { color: var(--el-text-color-secondary); font-size: 13px; }
.workspace-panels { display: grid; grid-template-columns: minmax(400px, 1fr) minmax(400px, 1.1fr); gap: 16px; min-height: calc(100vh - 190px); }
.workspace-panels > * { min-width: 0; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; padding: 16px; background: white; }
@media (max-width: 980px) { .workspace-panels { grid-template-columns: 1fr; } }
.empty-tip {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
}
</style>
