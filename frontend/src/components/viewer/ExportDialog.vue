<script setup lang="ts">
// 导出对话框:按 3D / 2D / GIS 分组列出全部格式,后端不支持的一律禁用置灰。

import { computed, onMounted, ref } from 'vue'
import { api, formatApiError } from '@/api/client'
import { useSettingsStore } from '@/stores/settings'
import { useExportsStore } from '@/stores/exports'
import { ensureSubscribed } from '@/composables/useTaskEvents'

const props = defineProps<{ taskId: string; layers?: string[] }>()
const emit = defineEmits<{ close: []; done: [] }>()

const settings = useSettingsStore()
const exportsStore = useExportsStore()
const submitting = ref<string | null>(null)
const error = ref<string | null>(null)

/** 每种格式的一句话说明,给不熟悉格式的用户看 */
const FORMAT_LABELS: Record<string, string> = {
  glb: 'glTF 二进制 · 通用 3D,推荐',
  obj: 'Wavefront OBJ · 建模软件通用',
  stl: 'STL · 3D 打印',
  fbx: 'FBX · 需要 Blender 转换',
  dae: 'Collada DAE · 需要 Blender 转换',
  usdz: 'USDZ · Apple AR 快速预览',
  dxf: 'AutoCAD DXF · CAD 图层',
  svg: 'SVG · 矢量地图,可无限放大',
  pdf: 'PDF · 打印版矢量地图',
  png: 'PNG · 位图快照',
  geojson: 'GeoJSON · 最通用的矢量交换',
  gpkg: 'GeoPackage · 单文件数据库,QGIS 直开',
  shp: 'Shapefile · 传统 GIS,打包 zip',
  kml: 'KML · Google Earth',
  kmz: 'KMZ · KML 压缩包',
  cityjson: 'CityJSON · 城市 3D 标准',
  '3dtiles': '3D Tiles · Cesium 流式加载',
}

const groups = computed(() => {
  const caps = settings.capabilities
  if (!caps) return []
  return Object.entries(caps.groups).map(([group, formats]) => ({
    group,
    formats: formats.map((f) => ({
      key: f,
      label: FORMAT_LABELS[f] ?? f,
      enabled: caps.formats[f] ?? false,
    })),
  }))
})

onMounted(() => {
  void settings.loadCapabilities().catch((e) => (error.value = formatApiError(e)))
})

async function run(format: string) {
  submitting.value = format
  error.value = null
  try {
    const job = await api.createExport(props.taskId, format, props.layers)
    exportsStore.add(job)
    ensureSubscribed() // SSE 模式下给这个任务补开事件流收导出进度
    emit('done') // 先告诉父页面弹"正在下载"的提示,再收起对话框
    emit('close')
  } catch (e) {
    error.value = formatApiError(e)
  } finally {
    submitting.value = null
  }
}
</script>

<template>
  <div class="dialog-mask" @click.self="emit('close')">
    <div class="dialog">
      <header>
        <h2>导出模型</h2>
        <button class="btn" @click="emit('close')">✕</button>
      </header>

      <p v-if="error" class="error">{{ error }}</p>

      <section v-for="g in groups" :key="g.group">
        <h3>{{ g.group }}</h3>
        <div class="fmt-grid">
          <button
            v-for="f in g.formats"
            :key="f.key"
            class="fmt"
            :disabled="!f.enabled || submitting !== null"
            :title="f.enabled ? '' : '后端未安装对应组件或未检测到 Blender'"
            @click="run(f.key)"
          >
            <strong>{{ f.key }}</strong>
            <small>{{ f.label }}</small>
            <span v-if="submitting === f.key" class="busy">提交中…</span>
          </button>
        </div>
      </section>

      <footer>
        <span class="tip">
          只导出图层面板里勾选的图层;导出在后台进行,可在"下载"页看进度和拿文件
        </span>
      </footer>
    </div>
  </div>
</template>
