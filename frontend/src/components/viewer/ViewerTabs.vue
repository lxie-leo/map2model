<script setup lang="ts">
// 查看页顶部的三个标签:3D 模型 / 2D 制图 / 导出。

const tab = defineModel<'model3d' | 'map2d' | 'exports'>('tab', { required: true })

const TABS = [
  { key: 'model3d', label: '3D 模型' },
  { key: 'map2d', label: '2D 制图' },
  { key: 'exports', label: '下载' },
] as const
</script>

<template>
  <div class="viewer-tabs">
    <button
      v-for="t in TABS"
      :key="t.key"
      :class="{ active: tab === t.key }"
      @click="tab = t.key"
    >
      {{ t.label }}
    </button>
  </div>
</template>
