<script setup lang="ts">
// 查看页顶部的三个标签:3D 模型 / 2D 制图 / 下载。

const tab = defineModel<'model3d' | 'map2d' | 'exports'>('tab', { required: true })

const TABS = ['model3d', 'map2d', 'exports'] as const
</script>

<template>
  <div class="viewer-tabs">
    <button
      v-for="t in TABS"
      :key="t"
      :class="{ active: tab === t }"
      @click="tab = t"
    >
      {{ $t(`tab.${t}`) }}
    </button>
  </div>
</template>
