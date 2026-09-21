<script setup lang="ts">
// 3D 画布:用 three.js 加载任务的 hub.glb 来渲染;图层显隐和视角听外面面板的。

import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { SceneManager } from '@/three/SceneManager'
import { urls } from '@/api/client'
import type { LayerKey } from '@/three/layers'

const props = defineProps<{
  taskId: string
  visibility: Record<LayerKey, boolean>
  /** 外部切换视角时变化 */
  viewMode: 'perspective' | 'top'
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
let mgr: SceneManager | null = null

onMounted(async () => {
  if (!canvas.value) return
  mgr = new SceneManager(canvas.value)
  await load()
})

async function load() {
  loading.value = true
  error.value = null
  try {
    await mgr?.loadModel(urls.taskFile(props.taskId, 'hub.glb'))
    if (!mgr) return
    // 加载完成后应用当前显隐设置
    for (const [key, vis] of Object.entries(props.visibility)) {
      mgr.setLayerVisible(key as LayerKey, vis)
    }
    mgr.setView(props.viewMode)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

// 任务切换时重新加载
watch(() => props.taskId, () => void load())

// 图层开关 → 节点显隐
watch(
  () => props.visibility,
  (vis) => {
    for (const [key, on] of Object.entries(vis)) mgr?.setLayerVisible(key as LayerKey, on)
  },
  { deep: true },
)

// 视角切换
watch(
  () => props.viewMode,
  (mode) => mgr?.setView(mode),
)

onBeforeUnmount(() => {
  mgr?.dispose()
  mgr = null
})
</script>

<template>
  <div class="scene-canvas">
    <canvas ref="canvas"></canvas>
    <div v-if="loading" class="overlay">{{ $t('scene.loading') }}</div>
    <div v-else-if="error" class="overlay error">
      {{ $t('scene.failedPrefix') }}{{ error }}
      <button class="btn" @click="load">{{ $t('scene.retry') }}</button>
    </div>
  </div>
</template>
