<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowLeftBold, ArrowRightBold } from '@element-plus/icons-vue'
import { useKbStore } from '@/stores/kbStore'
import KbSidebar from '@/components/KbSidebar.vue'
import DocumentPanel from '@/components/DocumentPanel.vue'
import ChatPanel from '@/components/ChatPanel.vue'

const kbStore = useKbStore()
const selectedKb = computed(() => kbStore.kbs.find((kb) => kb.id === kbStore.selectedKbId))
/** "技术文档"面板默认折叠，把屏幕空间留给问答；用户可随时展开查看/管理文档。 */
const documentPanelExpanded = ref(false)

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
        <div class="workspace-panels" :class="{ 'documents-collapsed': !documentPanelExpanded }">
          <div class="document-panel-slot">
            <button
              class="document-toggle-btn"
              type="button"
              :aria-label="documentPanelExpanded ? '收起技术文档' : '展开技术文档'"
              @click="documentPanelExpanded = !documentPanelExpanded"
            >
              <el-icon><component :is="documentPanelExpanded ? ArrowLeftBold : ArrowRightBold" /></el-icon>
              <span class="document-toggle-label">技术文档</span>
            </button>
            <DocumentPanel v-if="documentPanelExpanded" :kb-id="kbStore.selectedKbId" />
          </div>
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
/* flex:1 + min-height:0 让面板刚好占满标题下方的剩余空间，
   而不是像之前用 min-height 那样随内容无限撑高、把整页顶出去滚动——
   各面板自身的 overflow:auto 区域（文档表格/问答记录）才是真正应该滚动的地方。
   技术文档面板默认折叠，只留一条竖向的展开按钮，把空间让给问答；
   展开后恢复两栏布局，与折叠前一致。 */
.workspace-panels { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(400px, 1fr) minmax(400px, 1.1fr); gap: 16px; }
.workspace-panels.documents-collapsed { grid-template-columns: auto 1fr; }
.workspace-panels > .chat-panel { min-width: 0; min-height: 0; border: 1px solid var(--brand-border); border-radius: 10px; padding: 16px; background: var(--brand-surface); }
.document-panel-slot {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  border: 1px solid var(--brand-border);
  border-radius: 10px;
  padding: 16px;
  background: var(--brand-surface);
}
.documents-collapsed .document-panel-slot { padding: 8px; }
.document-panel-slot :deep(> *:not(.document-toggle-btn)) { flex: 1; min-height: 0; }
.document-toggle-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px;
  border: none;
  background: none;
  color: var(--el-text-color-secondary);
  cursor: pointer;
}
.documents-collapsed .document-toggle-btn {
  flex-direction: column;
  writing-mode: vertical-rl;
  height: 100%;
  justify-content: center;
}
.document-toggle-btn:hover { color: var(--el-color-primary); }
.document-toggle-label { font-size: 13px; }
@media (max-width: 980px) { .workspace-panels, .workspace-panels.documents-collapsed { grid-template-columns: 1fr; } }
.empty-tip {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
}
</style>
