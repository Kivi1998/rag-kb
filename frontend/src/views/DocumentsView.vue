<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { useKbStore } from '@/stores/kbStore'
import KbSidebar from '@/components/KbSidebar.vue'
import DocumentPanel from '@/components/DocumentPanel.vue'

const route = useRoute()
const router = useRouter()
const kbStore = useKbStore()

const kbId = computed(() => route.params.kbId as string)
const kb = computed(() => kbStore.kbs.find((item) => item.id === kbId.value))

/** 首次挂载时确保知识库列表已加载，再同步一次 kbStore 的当前知识库。 */
onMounted(async () => {
  if (kbStore.kbs.length === 0) await kbStore.loadKbs()
  if (kb.value) kbStore.selectedKbId = kb.value.id
})

/** 路由参数变化（如从这个页面直接切到另一个知识库的文档页，组件实例被复用、不会
 * 重新走 onMounted）时，同步 kbStore 的当前知识库，保持左侧列表高亮、以及
 * "返回问答"回去时还是这个知识库。不设 immediate，避免和上面 onMounted 的首次
 * 同步重复执行一次。 */
watch(
  () => route.params.kbId,
  () => {
    if (kb.value) kbStore.selectedKbId = kb.value.id
  }
)

function backToWorkspace() {
  router.push({ name: 'kb' })
}
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <KbSidebar />
    </aside>
    <main class="main-content">
      <div class="page-title">
        <button class="back-link" type="button" @click="backToWorkspace">
          <el-icon><ArrowLeft /></el-icon>
          返回问答
        </button>
        <h1 v-if="kb">{{ kb.name }}</h1>
      </div>
      <DocumentPanel v-if="kb" :kb-id="kb.id" />
      <div v-else class="empty-tip">
        <el-empty description="该知识库不存在或已删除">
          <el-button type="primary" @click="backToWorkspace">返回问答</el-button>
        </el-empty>
      </div>
    </main>
  </div>
</template>

<style scoped>
.workspace { display: flex; height: calc(100vh - 120px); }
.sidebar { width: 220px; border-right: 1px solid var(--brand-border); padding: 12px; }
.main-content { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 12px; overflow: hidden; }
.page-title { flex: 0 0 auto; display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
.page-title h1 { margin: 0; font-size: 22px; }
.back-link {
  display: flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: none;
  color: var(--el-color-primary);
  font-size: 13px;
  cursor: pointer;
  padding: 0;
}
.back-link:hover { text-decoration: underline; }
.main-content > .document-panel { flex: 1; min-height: 0; border: 1px solid var(--brand-border); border-radius: 10px; padding: 16px; background: var(--brand-surface); }
.empty-tip { flex: 1; display: flex; justify-content: center; align-items: center; }
</style>
