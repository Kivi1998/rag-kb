<script setup lang="ts">
/** 圆角矩形 + 竖线分割出左侧一小块——常见的"切换边栏"图标（如 Claude 官方 UI）。
 * 展开/收起共用同一个图标，不像箭头图标那样需要换方向。 */
</script>

<template>
  <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <path d="M9 3v18" />
  </svg>
</template>
