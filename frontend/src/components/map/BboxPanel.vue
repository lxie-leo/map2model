<script setup lang="ts">
// 框选信息面板:显示 bbox 数值和面积,超限给红字;图层开关和按钮。
// 按钮分三步走:没框时是"框选",框选模式下等待拖框,框好了变成
// "生成 2D / 3D 模型" + "重新框选"。

import { computed, ref } from 'vue'
import area from '@turf/area'
import type { BBox, TaskOptions } from '@/api/types'

const props = defineProps<{
  bbox: BBox | null
  /** 正在框选(等用户在地图上拖矩形) */
  drawing?: boolean
  /** 提交请求进行中,由父组件控制按钮禁用 */
  disabled?: boolean
}>()
const emit = defineEmits<{
  create: [bbox: BBox, options: TaskOptions]
  startDraw: []
}>()

/** 和后端 max_bbox_area_km2 保持一致 */
const MAX_AREA_KM2 = 25

// 图层开关(地形勾掉就按平地生成)
const options = ref<TaskOptions>({
  buildings: true,
  roads: true,
  railways: true,
  water: true,
  green: true,
  terrain: true,
})

const OPTION_LABELS: Record<keyof TaskOptions, string> = {
  buildings: '建筑',
  roads: '道路',
  railways: '铁路',
  water: '水体',
  green: '绿地',
  terrain: '地形起伏',
}

const areaKm2 = computed(() => {
  if (!props.bbox) return 0
  const [w, s, e, n] = props.bbox
  // turf 按米制算球面多边形面积,除以 1e6 得 km²
  return area({ type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] }) / 1e6
})

const tooLarge = computed(() => areaKm2.value > MAX_AREA_KM2)
const canSubmit = computed(
  () => props.bbox !== null && !tooLarge.value && props.disabled !== true,
)
</script>

<template>
  <div class="bbox-panel">
    <p v-if="drawing" class="hint">在地图上按住左键拖出矩形(右键取消)</p>
    <p v-else-if="!bbox" class="hint">点下方「框选」按钮,再到地图上拖出矩形</p>
    <template v-else>
      <table class="bbox-table">
        <tbody>
          <tr>
            <td>西经 W</td><td>{{ bbox[0].toFixed(5) }}</td>
            <td>东经 E</td><td>{{ bbox[2].toFixed(5) }}</td>
          </tr>
          <tr>
            <td>南纬 S</td><td>{{ bbox[1].toFixed(5) }}</td>
            <td>北纬 N</td><td>{{ bbox[3].toFixed(5) }}</td>
          </tr>
        </tbody>
      </table>
      <p class="area" :class="{ danger: tooLarge }">
        面积 {{ areaKm2.toFixed(3) }} km²
        <span v-if="tooLarge"> — 超过上限 {{ MAX_AREA_KM2 }} km²,请缩小范围</span>
      </p>
    </template>

    <div class="options">
      <label v-for="(label, key) in OPTION_LABELS" :key="key">
        <input type="checkbox" v-model="options[key]" />
        {{ label }}
      </label>
    </div>

    <!-- 没框:引导先点"框选";框选中:等拖框;框好了:生成 + 可重选 -->
    <button v-if="drawing" class="primary" disabled>框选中…(在地图上拖动)</button>
    <button v-else-if="!bbox" class="primary" @click="emit('startDraw')">框选</button>
    <template v-else>
      <button
        class="primary"
        :disabled="!canSubmit"
        @click="bbox && emit('create', bbox, options)"
      >
        生成 2D / 3D 模型
      </button>
      <button class="redraw" :disabled="disabled" @click="emit('startDraw')">重新框选</button>
    </template>
  </div>
</template>
