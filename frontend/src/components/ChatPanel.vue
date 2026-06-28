<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useKbStore } from '@/stores/kbStore'
import { useChatStore } from '@/stores/chatStore'
import DOMPurify from 'dompurify'
import SourceCard from './SourceCard.vue'
import type { Source } from '@/types/query'

const kbStore = useKbStore()
const chatStore = useChatStore()

const question = ref('')
const messageList = ref<HTMLElement | null>(null)

const messages = computed(() => {
  if (!kbStore.selectedKbId) return []
  return chatStore.getHistory(kbStore.selectedKbId)
})

const canSend = computed(() => {
  return question.value.trim() && !chatStore.streaming && kbStore.selectedKbId
})

async function handleSend() {
  if (!canSend.value || !kbStore.selectedKbId) return
  const q = question.value.trim()
  question.value = ''
  await chatStore.sendQuestion(kbStore.selectedKbId, q)
}

function sanitizeContent(content: string): string {
  return DOMPurify.sanitize(content)
}

// 自动滚动到底部
watch(
  () => [messages.value.length, chatStore.currentAnswer],
  () => {
    nextTick(() => {
      if (messageList.value) {
        messageList.value.scrollTop = messageList.value.scrollHeight
      }
    })
  }
)
</script>

<template>
  <div class="chat-panel">
    <div class="message-list" ref="messageList">
      <div v-for="(msg, idx) in messages" :key="idx" :class="['message', msg.role]">
        <div class="bubble" v-html="sanitizeContent(msg.content)" />
        <div v-if="msg.sources" class="sources">
          <SourceCard v-for="(s, i) in msg.sources" :key="i" :source="s" />
        </div>
      </div>

      <!-- 流式回答 -->
      <div v-if="chatStore.streaming && chatStore.currentAnswer" class="message assistant">
        <div class="bubble" v-html="sanitizeContent(chatStore.currentAnswer)" />
      </div>

      <!-- 来源卡片（流式中） -->
      <div v-if="chatStore.streaming && chatStore.pendingSources.length > 0" class="sources">
        <SourceCard v-for="(s, i) in chatStore.pendingSources" :key="i" :source="s" />
      </div>
    </div>

    <div class="input-area">
      <el-input
        v-model="question"
        placeholder="输入问题..."
        :disabled="chatStore.streaming"
        @keyup.enter="handleSend"
      />
      <el-button type="primary" :disabled="!canSend" :loading="chatStore.streaming" @click="handleSend">
        发送
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
.message {
  margin-bottom: 12px;
}
.message.user .bubble {
  background: #ecf5ff;
  margin-left: 20%;
}
.message.assistant .bubble {
  background: #f4f4f5;
}
.message.error .bubble {
  background: #fef0f0;
  color: #f56c6c;
}
.bubble {
  padding: 12px;
  border-radius: 8px;
  word-break: break-word;
}
.sources {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
.input-area {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #e4e7ed;
}
</style>
