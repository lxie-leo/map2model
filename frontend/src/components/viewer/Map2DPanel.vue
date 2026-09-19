<script setup lang="ts">
// 2D 制图面板:MapLibre 空白底 + preview.geojson 矢量渲染。
// 配色和后端 draw2d.PALETTE 一致:白路灰边、米色建筑、蓝水、绿草、深灰铁路。

import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { Map as MlMap, ExpressionSpecification } from 'maplibre-gl'
import BaseMap from '@/components/map/BaseMap.vue'
import { urls } from '@/api/client'
import type { BBox } from '@/api/types'

const props = defineProps<{
  taskId: string
  bbox: BBox
}>()

const map = ref<MlMap | null>(null)
const error = ref<string | null>(null)
const rootEl = ref<HTMLElement | null>(null)
let fitted = false // 只在画布真正有尺寸后对一次视野
let ro: ResizeObserver | null = null
let unmounted = false // 预览文件还没下完就切走页时,拦住回调别再碰已销毁的地图

// 后端 PALETTE 的前端镜像(改后端记得同步这里)
const COLOR = {
  paper: '#f2efe9',
  green: '#b7d6a8',
  water: '#a8cfe8',
  building: '#ddd5c9',
  buildingEdge: '#8f887e',
  roadCasing: '#b9b4ad',
  roadFill: '#ffffff',
  railway: '#4a4a4a',
}

async function onReady(m: MlMap) {
  map.value = m
  try {
    const res = await fetch(urls.preview(props.taskId))
    if (unmounted) return // 等文件的时候页面已经切走了
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const geojson = await res.json()

    // ready 现在来得早(地图实例刚建好就发),铺图层前先确认样式加载完。
    // load 可能已经发过,再挂个 idle 兜底,谁先到谁放行
    if (!m.isStyleLoaded()) await new Promise<void>((r) => {
      m.once('load', r)
      m.once('idle', r)
    })

    m.addSource('preview', { type: 'geojson', data: geojson })

    // 面层:草和水直接铺;建筑铺色 + 描边
    m.addLayer({
      id: 'green', type: 'fill', source: 'preview',
      filter: ['==', ['get', 'layer'], 'green'],
      paint: { 'fill-color': COLOR.green, 'fill-outline-color': '#9cc48c' },
    })
    m.addLayer({
      id: 'water-poly', type: 'fill', source: 'preview',
      filter: ['==', ['get', 'layer'], 'water'],
      paint: { 'fill-color': COLOR.water, 'fill-outline-color': '#8ab8da' },
    })
    m.addLayer({
      id: 'building', type: 'fill', source: 'preview',
      filter: ['==', ['get', 'layer'], 'building'],
      paint: { 'fill-color': COLOR.building, 'fill-outline-color': COLOR.buildingEdge },
    })

    // 线层:先垫"外壳"(路的灰边 + 河岸),再压白色路面;白路不垫灰边,在浅色底图上看不见
    // 线宽随缩放放大:width 是米,给个像素换算系数。
    // 注意:带 zoom 的表达式只准放在最外层 interpolate 的输入位上,路壳
    // "比路面粗 2px"不能用 ['+', lineWidth, 2] 套在外面(校验会拒),
    // 只能在两个缩放档位里各自把 2 加进去
    const w: ExpressionSpecification = ['coalesce', ['get', 'width'], 3]
    const lineWidth: ExpressionSpecification = ['interpolate', ['linear'], ['zoom'],
      12, ['*', w, 0.7],
      15, ['*', w, 2.2],
    ]
    const casingWidth: ExpressionSpecification = ['interpolate', ['linear'], ['zoom'],
      12, ['+', ['*', w, 0.7], 2],
      15, ['+', ['*', w, 2.2], 2],
    ]
    m.addLayer({
      id: 'water-line', type: 'line', source: 'preview',
      filter: ['all', ['==', ['get', 'layer'], 'water'], ['==', ['geometry-type'], 'LineString']],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': COLOR.water, 'line-width': lineWidth },
    })
    m.addLayer({
      id: 'railway', type: 'line', source: 'preview',
      filter: ['==', ['get', 'layer'], 'railway'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': COLOR.railway, 'line-width': lineWidth },
    })
    m.addLayer({
      id: 'road-casing', type: 'line', source: 'preview',
      filter: ['==', ['get', 'layer'], 'road'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': COLOR.roadCasing, 'line-width': casingWidth },
    })
    m.addLayer({
      id: 'road-fill', type: 'line', source: 'preview',
      filter: ['==', ['get', 'layer'], 'road'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': COLOR.roadFill, 'line-width': lineWidth },
    })

    // 视野对准任务区域(面板藏在别的标签后面时画布是 0 尺寸,对位会被放弃,
    // 等真正显示出来的那一刻再对,见下面的 ResizeObserver)
    fitIfVisible()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

function fitIfVisible() {
  const m = map.value
  if (fitted || !m || !rootEl.value) return
  // 藏着(display:none)的时候宽高是 0,这时候对位 maplibre 会直接放弃
  if (rootEl.value.clientWidth < 2 || rootEl.value.clientHeight < 2) return
  m.resize() // 先让地图把画布尺寸摆正,再对位
  m.fitBounds(props.bbox as [number, number, number, number], { padding: 24, duration: 0 })
  fitted = true
}

onMounted(() => {
  // 盯着面板尺寸:从"藏着的 0 尺寸"翻到"显示出来"的那一刻补对视野
  ro = new ResizeObserver(() => fitIfVisible())
  if (rootEl.value) ro.observe(rootEl.value)
})

onBeforeUnmount(() => {
  unmounted = true
  ro?.disconnect()
  ro = null
  map.value = null
})
</script>

<template>
  <div ref="rootEl" class="map2d-panel">
    <BaseMap :basemap="false" @ready="onReady" />
    <div v-if="error" class="overlay error">2D 预览加载失败:{{ error }}</div>
  </div>
</template>

<style scoped>
/* 空白地图是透明的,容器给纸底色透出来就是"图纸"效果 */
.map2d-panel {
  position: relative;
  background: v-bind('COLOR.paper');
  height: 100%;
}
</style>
