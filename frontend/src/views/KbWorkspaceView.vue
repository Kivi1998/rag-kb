<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useKbStore } from '@/stores/kbStore'
import KbSidebar from '@/components/KbSidebar.vue'
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
        <ChatPanel :kb-id="kbStore.selectedKbId" />
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
  border-right: 1px solid var(--brand-border);
  padding: 12px;
}
.main-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
  overflow: hidden;
}
.workspace-title { flex: 0 0 auto; display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; }
.workspace-title h1 { margin: 0; font-size: 22px; }
.workspace-title span { color: var(--el-text-color-secondary); font-size: 13px; }
/* flex:1 + min-height:0 让问答区刚好占满标题下方的剩余空间，
   而不是像之前用 min-height 那样随内容无限撑高、把整页顶出去滚动——
   ChatPanel 自身的 overflow:auto 区域（问答记录）才是真正应该滚动的地方。 */
.main-content > .chat-panel { flex: 1; min-height: 0; border: 1px solid var(--brand-border); border-radius: 10px; padding: 16px; background: var(--brand-surface); }
.empty-tip {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
}
</style>
