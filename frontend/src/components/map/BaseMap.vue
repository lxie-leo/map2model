<script setup lang="ts">
// MapLibre 地图封装:一个 div + 一个 maplibre.Map,挂载后向外发 ready 事件。
// basemap=false 时给一张空白底(2D 预览用),否则铺 CARTO 浅色瓦片。
// 视角操作换键:MapLibre 默认右键拖=旋转/俯仰,但右键在框选里有别的
// 用途(取消框选),这里把旋转挪到中键——关掉自带的,自己监听中键拖动。

import { onMounted, onBeforeUnmount, ref, shallowRef } from 'vue'
import { Map, type StyleSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useSettingsStore } from '@/stores/settings'

const props = withDefaults(
  defineProps<{
    /** 要不要铺在线瓦片底图 */
    basemap?: boolean
    center?: [number, number]
    zoom?: number
  }>(),
  {
    basemap: true,
    center: () => [121.4917, 31.2363] as [number, number], // 默认上海人民广场附近,和测试样例同区
    zoom: 14,
  },
)

const emit = defineEmits<{ ready: [map: Map] }>()

const container = ref<HTMLDivElement | null>(null)
const map = shallowRef<Map | null>(null)

// 中键拖转视角的起点状态(拖动中才非空)
let midDrag: { x: number; y: number; bearing: number; pitch: number } | null = null

function onMidDown(e: MouseEvent) {
  if (e.button !== 1) return
  const m = map.value
  if (!m) return
  // 地图被锁住(比如正在框选)时视角也不许动
  if (!m.dragPan.isEnabled()) return
  e.preventDefault() // 不让浏览器按中键出"自动滚动"的小圆点
  midDrag = { x: e.clientX, y: e.clientY, bearing: m.getBearing(), pitch: m.getPitch() }
  window.addEventListener('mousemove', onMidMove)
  window.addEventListener('mouseup', onMidUp)
}

function onMidMove(e: MouseEvent) {
  const m = map.value
  if (!midDrag || !m) return
  const dx = e.clientX - midDrag.x
  const dy = e.clientY - midDrag.y
  // 速率和方向对齐 MapLibre 自带的右键旋转(源码里 0.8°/px 转、0.5°/px 俯仰,
  // 向上拖 = 越俯视),手感就不会变
  const maxPitch = m.getMaxPitch()
  m.jumpTo({
    bearing: midDrag.bearing + dx * 0.8,
    pitch: Math.max(0, Math.min(maxPitch, midDrag.pitch - dy * 0.5)),
  })
}

function onMidUp() {
  midDrag = null
  window.removeEventListener('mousemove', onMidMove)
  window.removeEventListener('mouseup', onMidUp)
}

function buildStyle(): StyleSpecification {
  if (!props.basemap) {
    return { version: 8, sources: {}, layers: [] }
  }
  const settings = useSettingsStore()
  return {
    version: 8,
    sources: {
      basemap: {
        type: 'raster',
        tiles: settings.basemapTiles,
        tileSize: 256,
        attribution: settings.basemapAttribution,
      },
    },
    layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }],
  }
}

onMounted(() => {
  if (!container.value) return
  map.value = new Map({
    container: container.value,
    style: buildStyle(),
    center: props.center,
    zoom: props.zoom,
    attributionControl: { compact: true },
  })
  // 右键旋转交给中键方案,自带的关掉(Ctrl+左键旋转也一并关了)
  map.value.dragRotate.disable()
  map.value.getCanvas().addEventListener('mousedown', onMidDown)
  // 地图实例一建好就交出去:飞视角(fitBounds)这些操作不依赖底图加载完。
  // 之前等 load 事件才发 ready,底图瓦片一慢,刚进页面的几秒里点任务卡片
  // 就"不回显也不飞",看起来像功能失灵。要铺图层的消费方自己等 load。
  emit('ready', map.value)
})

onBeforeUnmount(() => {
  onMidUp() // 万一拖着拖着页面拆了,把 window 上的监听摘干净
  if (map.value) map.value.getCanvas().removeEventListener('mousedown', onMidDown)
  map.value?.remove()
  map.value = null
})

defineExpose({ map })
</script>

<template>
  <div ref="container" class="base-map"></div>
</template>

<style scoped>
.base-map {
  position: absolute;
  inset: 0;
}
</style>
