<script setup lang="ts">
// 图层面板:六个图层的显隐开关 + 视角单选,配色和 3D 场景一致。
// 浮在场景右下角(半透明底),不单独占一栏。

import { LAYERS, type LayerKey } from '@/three/layers'

const visibility = defineModel<Record<LayerKey, boolean>>('visibility', { required: true })
const viewMode = defineModel<'perspective' | 'top'>('viewMode', { required: true })
</script>

<template>
  <div class="layer-panel">
    <h3>图层</h3>
    <div class="layers">
      <label v-for="l in LAYERS" :key="l.key" class="layer-row">
        <input type="checkbox" v-model="visibility[l.key]" />
        <span class="chip" :style="{ background: l.color }"></span>
        {{ l.label }}
      </label>
    </div>

    <h3>视角</h3>
    <div class="layers">
      <label class="layer-row">
        <input type="radio" name="view-mode" value="perspective" v-model="viewMode" />
        透视
      </label>
      <label class="layer-row">
        <input type="radio" name="view-mode" value="top" v-model="viewMode" />
        俯视
      </label>
    </div>
  </div>
</template>
