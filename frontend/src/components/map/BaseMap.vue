<script setup lang="ts">
// MapLibre 地图封装:一个 div + 一个 maplibre.Map,挂载后向外发 ready 事件。
// basemap=false 时给一张空白底(2D 预览用),否则铺在线瓦片(osm 街道/Esri 卫星,
// 由 basemapId 决定),右上角一个小钮在两种底图间切换。
// 视角操作换键:MapLibre 默认右键拖=旋转/俯仰,但右键在框选里有别的
// 用途(取消框选),这里把旋转挪到中键——关掉自带的,自己监听中键拖动。

import { onMounted, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { Map, type StyleSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useSettingsStore, basemapById, type BasemapId } from '@/stores/settings'

const props = withDefaults(
  defineProps<{
    /** 要不要铺在线瓦片底图 */
    basemap?: boolean
    /** 底图样式:osm 街道 / satellite 卫星(运行时切换,瓦片原地换) */
    basemapId?: BasemapId
    center?: [number, number]
    zoom?: number
  }>(),
  {
    basemap: true,
    basemapId: 'osm',
    center: () => [121.4917, 31.2363] as [number, number], // 默认上海人民广场附近,和测试样例同区
    zoom: 14,
  },
)

const emit = defineEmits<{ ready: [map: Map] }>()

// 切换钮直接读写设置仓:改 basemap 后 HomeView 传进来的 prop 会跟着变,
// 上面的 watch 负责真的换瓦片
const settings = useSettingsStore()

/** 点一下切到另一种底图;钮上显示的是"切过去之后"的名字 */
function toggleBasemap() {
  settings.setBasemap(settings.basemap === 'osm' ? 'satellite' : 'osm')
}

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
  const def = basemapById(props.basemapId)
  return {
    version: 8,
    sources: {
      basemap: {
        type: 'raster',
        tiles: def.tiles,
        tileSize: 256,
        attribution: def.attribution,
      },
    },
    layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }],
  }
}

// 运行时换底图:layer 按名字引用 source,得连着 layer 一起拆了重铺。
// 重铺前记下底图上面第一层的 id,插回原位置——晚于本组件挂的图层
// (框选矩形、2D 预览)都压在底图上头,不能被新底图盖住。
function applyBasemap(id: BasemapId, attempt = 0) {
  const m = map.value
  if (!m || !props.basemap) return
  const def = basemapById(id)
  try {
    const layers = m.getStyle().layers
    const idx = layers.findIndex((l) => l.id === 'basemap')
    const beforeId = idx >= 0 ? layers[idx + 1]?.id : layers[0]?.id
    if (m.getLayer('basemap')) m.removeLayer('basemap')
    if (m.getSource('basemap')) m.removeSource('basemap')
    m.addSource('basemap', {
      type: 'raster',
      tiles: def.tiles,
      tileSize: 256,
      attribution: def.attribution,
    })
    m.addLayer({ id: 'basemap', type: 'raster', source: 'basemap' }, beforeId)
  } catch {
    // 样式还没就绪时会抛错。别拿 isStyleLoaded 当门槛(它要等瓦片到齐,
    // 可能一直 false),稍等片刻重试就行
    if (attempt < 20) setTimeout(() => applyBasemap(id, attempt + 1), 200)
  }
}

watch(
  () => props.basemapId,
  (id) => applyBasemap(id),
)

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
  <!-- 只在有底图的实例上显示(2D 预览那张是空白底,用不着切) -->
  <button
    v-if="basemap"
    type="button"
    class="bm-toggle"
    @click="toggleBasemap"
  >{{ settings.basemap === 'osm' ? $t('map.satellite') : $t('map.street') }}</button>
</template>

<style scoped>
.base-map {
  position: absolute;
  inset: 0;
}

/* 底图切换小钮:搜索框/信息胶囊同款玻璃底,字号收一档 */
.bm-toggle {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 10;
  padding: 3px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(6px);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
  font-size: 12px;
  color: var(--ink);
  cursor: pointer;
}

.bm-toggle:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* 窄窗口档(和 main.css 的结构档同一个断点):右上角会冒出"面板"
   浮钮(侧栏收起时),往下挪一行给它让位 */
@media (max-width: 899px) {
  .bm-toggle {
    top: 48px;
  }
}
</style>
