<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { CircleClose, Promotion } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/authStore'
import { openStream, queryStreamUrl } from '@/api/queryApi'
import type { Citation } from '@/types/citation'
import type { Message, QueryEvent } from '@/types/query'

const props = defineProps<{ kbId: string }>()
const authStore = useAuthStore()
const question = ref('')
const messages = ref<Message[]>([])
const sending = ref(false)
const streamAbort = ref<AbortController | null>(null)
const transcript = ref<HTMLElement | null>(null)

const canSend = computed(() => !!props.kbId && !!question.value.trim() && !sending.value)

function headers() {
  const result: Record<string, string> = {}
  if (authStore.token) result.Authorization = `Bearer ${authStore.token}`
  if (authStore.orgId) result['X-Org-Id'] = authStore.orgId
  return result
}

function createAssistantMessage(): Message {
  return { id: crypto.randomUUID(), role: 'assistant', content: '', citations: [], createdAt: new Date().toISOString() }
}

async function ask() {
  const text = question.value.trim()
  if (!text || sending.value) return
  const userMessage: Message = { id: crypto.randomUUID(), role: 'user', content: text, createdAt: new Date().toISOString() }
  const assistantMessage = createAssistantMessage()
  messages.value.push(userMessage, assistantMessage)
  question.value = ''
  sending.value = true
  const controller = new AbortController()
  streamAbort.value = controller
  try {
    for await (const event of openStream({
      url: queryStreamUrl('', props.kbId),
      body: { question: text }, headers: headers(), signal: controller.signal
    })) {
      applyEvent(assistantMessage, event)
      await scrollToBottom()
      if (event.eventType === 'done' || event.eventType === 'error' || event.eventType === 'refusal') break
    }
  } catch (error) {
    if ((error as Error).name !== 'AbortError') {
      assistantMessage.role = 'error'
      assistantMessage.content = '连接问答服务失败，请稍后重试。'
    } else if (!assistantMessage.content) {
      assistantMessage.role = 'error'
      assistantMessage.content = '已取消本次问答。'
    }
  } finally {
    sending.value = false
    streamAbort.value = null
    await scrollToBottom()
  }
}

function applyEvent(message: Message, event: QueryEvent) {
  switch (event.eventType) {
    case 'chunk': message.content += event.data.content; break
    case 'source': message.citations = [...(message.citations || []), event.data.citation]; break
    case 'refusal':
      message.role = 'refusal'
      message.content = event.data.message
      break
    case 'error':
      message.role = 'error'
      message.content = event.data.message
      break
    case 'done': break
  }
}

function cancel() {
  streamAbort.value?.abort()
}

async function scrollToBottom() {
  await nextTick()
  if (transcript.value) transcript.value.scrollTop = transcript.value.scrollHeight
}

function citationLocation(citation: Citation) {
  const parts = [citation.headingPath.join(' / ')]
  if (citation.pageNo !== null) parts.push(`第 ${citation.pageNo} 页`)
  if (citation.lineStart !== null) parts.push(`第 ${citation.lineStart}${citation.lineEnd === null ? '' : `-${citation.lineEnd}`} 行`)
  return parts.filter(Boolean).join(' · ')
}

watch(() => props.kbId, () => { messages.value = []; question.value = ''; cancel() })
</script>

<template>
  <section class="chat-panel" data-testid="chat-panel">
    <header class="panel-header">
      <div><h2>技术文档问答</h2><p>回答仅基于已完成索引的当前知识库文档。</p></div>
      <el-button v-if="sending" type="danger" plain :icon="CircleClose" @click="cancel">取消生成</el-button>
    </header>
    <div ref="transcript" class="transcript" aria-live="polite">
      <el-empty v-if="messages.length === 0" description="输入类名、错误码、配置项或技术问题开始检索" />
      <article v-for="message in messages" :key="message.id" class="message" :class="`message-${message.role}`">
        <span class="message-label">{{ message.role === 'user' ? '你' : message.role === 'refusal' ? '检索结果' : '知识库助手' }}</span>
        <p class="message-content">{{ message.content || (sending ? '正在生成…' : '') }}</p>
        <div v-if="message.citations?.length" class="citations">
          <p class="citation-title">参考来源</p>
          <article v-for="(citation, index) in message.citations" :key="`${citation.documentId}-${index}`" class="citation-card">
            <strong>[{{ index + 1 }}] {{ citation.documentName || '文档不可访问' }}</strong>
            <span v-if="citationLocation(citation)" class="citation-location">{{ citationLocation(citation) }}</span>
            <p>{{ citation.snippet }}</p>
            <small v-if="citation.score !== null">相关度 {{ citation.score.toFixed(3) }}</small>
          </article>
        </div>
      </article>
    </div>
    <form class="composer" @submit.prevent="ask">
      <el-input v-model="question" type="textarea" :rows="3" maxlength="2000" show-word-limit :disabled="sending" placeholder="例如：SearchService 启动失败如何排查？" @keydown.ctrl.enter.prevent="ask" />
      <el-button type="primary" native-type="submit" :icon="Promotion" :loading="sending" :disabled="!canSend">发送</el-button>
    </form>
  </section>
</template>

<style scoped>
.chat-panel { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 14px; }
.panel-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.panel-header h2 { margin: 0; font-size: 18px; }
.panel-header p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.transcript { min-height: 280px; flex: 1; overflow: auto; border: 1px solid var(--brand-border); border-radius: 8px; padding: 14px; background: var(--brand-surface-soft); }
.message { max-width: 92%; margin: 0 0 14px; border-radius: 8px; padding: 10px 12px; background: var(--brand-surface); border: 1px solid var(--brand-border-soft); }
.message-user { margin-left: auto; background: var(--el-color-primary-light-9); }
.message-refusal { border-color: var(--el-color-warning-light-5); background: var(--el-color-warning-light-9); }
.message-error { border-color: var(--el-color-danger-light-5); background: var(--el-color-danger-light-9); }
.message-label { color: var(--el-text-color-secondary); font-size: 12px; }
.message-content { margin: 5px 0 0; white-space: pre-wrap; line-height: 1.6; }
.citations { margin-top: 10px; border-top: 1px dashed var(--el-border-color); padding-top: 8px; }
.citation-title { margin: 0 0 7px; color: var(--el-text-color-secondary); font-size: 12px; }
.citation-card { margin: 6px 0; padding: 8px; border-radius: 5px; background: var(--brand-surface-soft); border: 1px solid var(--brand-border-soft); font-size: 13px; }
.citation-card strong, .citation-card span, .citation-card small { display: block; }
.citation-card p { margin: 5px 0; white-space: pre-wrap; }
.citation-location, .citation-card small { color: var(--el-text-color-secondary); }
.composer { display: flex; align-items: flex-end; gap: 10px; }
.composer .el-textarea { flex: 1; }
@media (max-width: 760px) { .composer { flex-direction: column; align-items: stretch; } .message { max-width: 100%; } }
</style>
