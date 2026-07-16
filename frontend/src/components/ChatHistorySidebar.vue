<script setup lang="ts">
import { ref } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/authStore'
import { deleteSession, listSessions } from '@/api/queryApi'
import SidebarToggleIcon from '@/components/icons/SidebarToggleIcon.vue'
import type { ChatSessionSummary } from '@/types/query'

const props = defineProps<{ kbId: string; activeSessionId: string | null }>()
const emit = defineEmits<{
  select: [sessionId: string]
  create: []
  deleted: [sessionId: string]
}>()

const authStore = useAuthStore()
const expanded = ref(false)
const loading = ref(false)
const sessions = ref<ChatSessionSummary[]>([])

function headers() {
  const result: Record<string, string> = {}
  if (authStore.token) result.Authorization = `Bearer ${authStore.token}`
  if (authStore.orgId) result['X-Org-Id'] = authStore.orgId
  return result
}

async function refresh() {
  if (!props.kbId) return
  loading.value = true
  try {
    sessions.value = await listSessions('', props.kbId, headers())
  } catch (error) {
    console.error('加载历史会话列表失败', error)
  } finally {
    loading.value = false
  }
}

async function toggle() {
  expanded.value = !expanded.value
  if (expanded.value) await refresh()
}

function select(sessionId: string) {
  emit('select', sessionId)
}

function create() {
  emit('create')
  void refresh()
}

async function remove(item: ChatSessionSummary, event: Event) {
  event.stopPropagation()
  try {
    await ElMessageBox.confirm(`确定删除对话「${item.title || '新对话'}」？`, '确认删除', { type: 'warning' })
  } catch {
    return // 用户取消
  }
  try {
    await deleteSession('', props.kbId, item.sessionId, headers())
    sessions.value = sessions.value.filter((session) => session.sessionId !== item.sessionId)
    emit('deleted', item.sessionId)
  } catch (error) {
    console.error('删除会话失败', error)
    ElMessage.error('删除会话失败，请稍后重试')
  }
}

defineExpose({ refresh })
</script>

<template>
  <div class="history-sidebar" :class="{ expanded }" data-testid="chat-history-sidebar">
    <button
      class="toggle-btn"
      type="button"
      :aria-label="expanded ? '收起历史对话' : '展开历史对话'"
      @click="toggle"
    >
      <el-icon><SidebarToggleIcon /></el-icon>
    </button>
    <div v-if="expanded" class="panel">
      <div class="panel-header">
        <span>历史对话</span>
        <el-button size="small" :icon="Plus" @click="create">新建对话</el-button>
      </div>
      <el-empty v-if="!loading && sessions.length === 0" description="暂无历史对话" :image-size="60" />
      <ul class="session-list">
        <li
          v-for="item in sessions"
          :key="item.sessionId"
          class="session-item"
          :class="{ active: item.sessionId === activeSessionId }"
          @click="select(item.sessionId)"
        >
          <span class="session-title">{{ item.title || '新对话' }}</span>
          <el-icon class="delete-icon" @click="(event: Event) => remove(item, event)"><Delete /></el-icon>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.history-sidebar { display: flex; flex-shrink: 0; }
.toggle-btn {
  width: 22px;
  border: none;
  border-right: 1px solid var(--brand-border);
  background: var(--brand-surface-soft);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
}
.toggle-btn:hover { color: var(--el-color-primary); }
.panel {
  width: 220px;
  border-right: 1px solid var(--brand-border);
  padding: 10px;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}
.panel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; font-size: 13px; font-weight: 600; }
.session-list { list-style: none; margin: 0; padding: 0; }
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 8px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.session-item:hover { background: var(--brand-surface-soft); }
.session-item.active { background: var(--el-color-primary-light-9); }
.session-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.delete-icon { display: none; color: var(--el-text-color-secondary); }
.session-item:hover .delete-icon { display: inline-flex; }
.delete-icon:hover { color: var(--el-color-danger); }
</style>
