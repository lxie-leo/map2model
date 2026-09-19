<script setup lang="ts">
// 框选组件(自己不渲染 DOM):进入框选模式后,在地图上按住左键拖出矩形,
// 把 bbox 抛给父组件。
// 做法:GeoJSON source + 虚线描边 + 半透明填充。
// 地图的拖动/旋转只在框选模式里锁住,画完或右键取消后马上还回去。

import { onBeforeUnmount, watch } from 'vue'
import type { GeoJSONSource, Map as MlMap } from 'maplibre-gl'
import type { BBox } from '@/api/types'

const props = defineProps<{
  map: MlMap | null
  active: boolean
  /** 地图上要显示的框(自己刚画的,或点任务列表回显的);null = 清掉 */
  bbox: BBox | null
}>()
const emit = defineEmits<{ change: [bbox: BBox | null]; exit: [] }>()

const SOURCE = 'select-rect'
const FILL = 'select-rect-fill'
const LINE = 'select-rect-line'

let start: { lng: number; lat: number } | null = null
let drawing = false

// 进模式前的地图状态,退出时照原样还回去
let panWasEnabled = true
let rotateWasEnabled = true
let oldCursor = ''

function onMouseDown(e: { lngLat: { lng: number; lat: number }; originalEvent: MouseEvent }) {
  // 只有框选模式里的左键才开始画
  if (!props.active || e.originalEvent.button !== 0) return
  drawing = true
  start = { lng: e.lngLat.lng, lat: e.lngLat.lat }
  updateBox(e.lngLat.lng, e.lngLat.lat)
}

// 松手和移动都挂在 window 上听:地图只把自家容器里的鼠标事件转出来,
// 要是只听地图的,拖到容器外面才松手就永远收不到"松开",
// 框会一直跟着鼠标跑
function windowPointToLngLat(clientX: number, clientY: number) {
  const map = props.map!
  const rect = map.getCanvas().getBoundingClientRect()
  return { rect, ll: map.unproject([clientX - rect.left, clientY - rect.top]) }
}

function onWindowMouseMove(e: MouseEvent) {
  if (!drawing || !start || !props.map) return
  const { ll } = windowPointToLngLat(e.clientX, e.clientY)
  updateBox(ll.lng, ll.lat)
}

function onWindowMouseUp(e: MouseEvent) {
  if (!drawing || !start || !props.map) return
  drawing = false
  const { rect, ll } = windowPointToLngLat(e.clientX, e.clientY)
  // 框没画成(地图外松手/拖得太小):把地图恢复成"当前该显示的框"。
  // 不能一把 clearBox 清光——那会把任务回显的框也顺手抹掉,而父组件
  // 状态里它还选着,再点同一张卡片会被当成"取消",框就永远回不来
  const discard = () => {
    showBox(props.bbox)
    emit('change', null)
  }
  // 在地图外面松的手,这个框就算了,别硬画一个跨半个地球的巨框
  if (
    e.clientX < rect.left || e.clientX > rect.right ||
    e.clientY < rect.top || e.clientY > rect.bottom
  ) {
    discard()
    return
  }
  const b = toBBox(start.lng, start.lat, ll.lng, ll.lat)
  // 拖出足够大的框才生效(防误点);太小的框别留在地图上误导人
  if (Math.abs(b[2] - b[0]) <= 1e-5 || Math.abs(b[3] - b[1]) <= 1e-5) {
    discard()
    return
  }
  emit('change', b)
}

// 右键在框选模式里 = 解除框选:退出模式,自己画的框作废。
// 任务回显的框不属于"框选",照旧保留(交给父组件状态决定去留)。
// (模式里右键旋转已被锁住,不会和"右键转视角"打架;模式外右键不受影响)
function onContextMenu(e: { originalEvent: MouseEvent }) {
  if (!props.active) return
  e.originalEvent.preventDefault()
  drawing = false
  start = null
  showBox(props.bbox)
  emit('change', null)
  emit('exit')
}

function toBBox(w: number, s: number, e: number, n: number): BBox {
  return [Math.min(w, e), Math.min(s, n), Math.max(w, e), Math.max(s, n)]
}

function updateBox(lng: number, lat: number) {
  if (!start || !props.map) return
  const b = toBBox(start.lng, start.lat, lng, lat)
  // getSource 返回基类,setData 是 GeoJSON source 才有的,收窄一下类型
  const src = props.map.getSource(SOURCE) as GeoJSONSource | undefined
  src?.setData({
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [[
      [b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]],
    ]] },
  })
}

function clearBox() {
  if (!mapAlive(props.map)) return
  const src = props.map.getSource(SOURCE) as GeoJSONSource | undefined
  src?.setData({ type: 'FeatureCollection', features: [] })
}

// 外部给的框(刚画完回显 / 点任务回显 / 清掉)直接照画
function showBox(b: BBox | null) {
  if (!mapAlive(props.map)) return
  const src = props.map.getSource(SOURCE) as GeoJSONSource | undefined
  if (!src) {
    // 图层还没建好:挂到 load 和 idle 两个事件上补画。
    // 只挂 load 不够——它可能在挂监听之前就发完了,那便永远等不到
    props.map.once('load', () => showBox(props.bbox))
    props.map.once('idle', () => showBox(props.bbox))
    return
  }
  if (!b) {
    src.setData({ type: 'FeatureCollection', features: [] })
    return
  }
  src.setData({
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [[
      [b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]],
    ]] },
  })
}

watch(() => props.bbox, showBox, { immediate: true })

function enterMode(map: MlMap) {
  // 进模式=要画新框,先抹掉上一轮的旧框
  clearBox()
  // 把视角转回正北平视:框选存的是北向对齐的矩形,地图转着角度时
  // 屏幕上拖的方向和东西南北对不上,拖出的斜框转回北向范围会变形
  // 撑大,很难正好框住想要的地。转正后拖的方向就是东西南北。
  if (map.getBearing() !== 0 || map.getPitch() !== 0) {
    map.easeTo({ bearing: 0, pitch: 0, duration: 400 })
  }
  // 记下进模式前的状态,锁住拖动和右键旋转,鼠标变十字
  panWasEnabled = map.dragPan.isEnabled()
  rotateWasEnabled = map.dragRotate.isEnabled()
  map.dragPan.disable()
  map.dragRotate.disable()
  oldCursor = map.getCanvas().style.cursor
  map.getCanvas().style.cursor = 'crosshair'
  map.on('contextmenu', onContextMenu)
}

function leaveMode(map: MlMap) {
  // 只收尾不动框:正常画完时框要留着显示,清框是右键取消/进新模式时的事
  drawing = false
  start = null
  map.off('contextmenu', onContextMenu)
  if (panWasEnabled) map.dragPan.enable()
  if (rotateWasEnabled) map.dragRotate.enable()
  map.getCanvas().style.cursor = oldCursor
}

// 建图层:能加就加,加了验货。绝不拿 isStyleLoaded() 当门槛——
// 那个函数要等底图所有瓦片到齐才算数,网络一抖就永远 false,
// 图层被它拦住永远建不上(表现:能飞过去但框死活不出)。
// addSource 真正的门槛只是样式元数据就绪,地图构造完就满足了
function ensureLayers(map: MlMap): boolean {
  if (!map.getSource(SOURCE)) {
    try {
      map.addSource(SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    } catch {
      return false // 元数据还没就绪,下轮再试
    }
  }
  // 先填充分淡罩,再描虚线边,压在底图之上、其他图层之下无所谓(主页没有别的)
  if (!map.getLayer(FILL)) {
    try {
      map.addLayer({ id: FILL, type: 'fill', source: SOURCE, paint: { 'fill-color': '#2563eb', 'fill-opacity': 0.08 } })
    } catch { /* 同上 */ }
  }
  if (!map.getLayer(LINE)) {
    try {
      map.addLayer({
        id: LINE,
        type: 'line',
        source: SOURCE,
        paint: { 'line-color': '#2563eb', 'line-width': 2, 'line-dasharray': [2, 1.5] },
      })
    } catch { /* 同上 */ }
  }
  return !!map.getSource(SOURCE) && !!map.getLayer(FILL) && !!map.getLayer(LINE)
}

// 图层建立兜底:正常第一次尝试就成;万一地图元数据还没就绪,
// 靠 load/idle 事件加短轮询谁先到谁再试,建好收摊(15 秒后放弃,防泄漏)
function armLayers(m: MlMap) {
  let tries = 0
  const attempt = (): boolean => {
    if (!mapAlive(m)) return true // 地图都没了,不用再试
    if (!ensureLayers(m)) return false
    if (props.bbox) showBox(props.bbox) // 建好之前如果就该显示框,补上
    return true
  }
  if (attempt()) return
  m.once('load', attempt)
  m.once('idle', attempt)
  const timer = setInterval(() => {
    if (attempt() || ++tries > 125) clearInterval(timer)
  }, 120)
}

// 地图被 remove() 之后内部的 style 就空了,再问图层/源都会炸。
// 卸载时 BaseMap 和本组件谁先拆不一定,动手前都得先看地图还活着没
function mapAlive(map: MlMap | null): map is MlMap {
  return !!map && (map as unknown as { style?: unknown }).style != null
}

function teardown(map: MlMap) {
  window.removeEventListener('mousemove', onWindowMouseMove)
  window.removeEventListener('mouseup', onWindowMouseUp)
  if (!mapAlive(map)) return
  leaveMode(map)
  map.off('mousedown', onMouseDown)
  for (const id of [LINE, FILL]) if (map.getLayer(id)) map.removeLayer(id)
  if (map.getSource(SOURCE)) map.removeSource(SOURCE)
}

watch(
  () => props.map,
  (map, old) => {
    if (old) teardown(old)
    if (!map) return
    // 存个非空的局部量,闭包里 TS 才认它不会变回 null
    const m = map
    // 鼠标监听、锁地图这些都只认地图实例,不等样式,先挂上
    m.on('mousedown', onMouseDown)
    window.addEventListener('mousemove', onWindowMouseMove)
    window.addEventListener('mouseup', onWindowMouseUp)
    if (props.active) enterMode(m)
    armLayers(m)
  },
  { immediate: true },
)

// 框选模式开关:进了锁地图,出了还回去
watch(
  () => props.active,
  (active) => {
    const map = props.map
    if (!mapAlive(map)) return
    if (active) enterMode(map)
    else leaveMode(map)
  },
)

onBeforeUnmount(() => {
  // 只清理,不再往外发事件:整个页面都在拆了,这时还去改父组件的状态,
  // 会让 Vue 在卸载中途又排一轮更新,时序上容易出乱子
  if (props.map) teardown(props.map)
})
</script>

<!-- 这个组件不画任何 DOM(框是地图图层、监听在 window 上)。
     留一个空模板纯粹是为了让 Vue 闭嘴:没有模板块它会一直报
     "missing template or render function" 的警告 -->
<template>
  <!-- 什么都不渲染 -->
</template>
