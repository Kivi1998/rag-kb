<script setup lang="ts">
import { onMounted } from 'vue'
import { useKbStore } from '@/stores/kbStore'
import KbSidebar from '@/components/KbSidebar.vue'
import DocumentTable from '@/components/DocumentTable.vue'
import ChatPanel from '@/components/ChatPanel.vue'

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
      <el-tabs v-if="kbStore.selectedKbId">
        <el-tab-pane label="文档管理">
          <DocumentTable />
        </el-tab-pane>
        <el-tab-pane label="问答">
          <ChatPanel />
        </el-tab-pane>
      </el-tabs>
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
