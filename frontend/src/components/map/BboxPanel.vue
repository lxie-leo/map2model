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

// 开关的显示顺序(文案走 option.* 的 key,和 TaskOptions 字段名一致)
const OPTION_KEYS: (keyof TaskOptions)[] = [
  'buildings', 'roads', 'railways', 'water', 'green', 'terrain',
]

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
    <p v-if="drawing" class="hint">{{ $t('bbox.drawingHint') }}</p>
    <p v-else-if="!bbox" class="hint">{{ $t('bbox.emptyHint') }}</p>
    <template v-else>
      <table class="bbox-table">
        <tbody>
          <tr>
            <td>{{ $t('bbox.west') }}</td><td>{{ bbox[0].toFixed(5) }}</td>
            <td>{{ $t('bbox.east') }}</td><td>{{ bbox[2].toFixed(5) }}</td>
          </tr>
          <tr>
            <td>{{ $t('bbox.south') }}</td><td>{{ bbox[1].toFixed(5) }}</td>
            <td>{{ $t('bbox.north') }}</td><td>{{ bbox[3].toFixed(5) }}</td>
          </tr>
        </tbody>
      </table>
      <p class="area" :class="{ danger: tooLarge }">
        {{ $t('bbox.area', { area: areaKm2.toFixed(3) }) }}
        <span v-if="tooLarge">{{ $t('bbox.tooLarge', { max: MAX_AREA_KM2 }) }}</span>
      </p>
    </template>

    <div class="options">
      <label v-for="key in OPTION_KEYS" :key="key">
        <input type="checkbox" v-model="options[key]" />
        {{ $t(`option.${key}`) }}
      </label>
    </div>

    <!-- 没框:引导先点"框选";框选中:等拖框;框好了:生成 + 可重选 -->
    <button v-if="drawing" class="primary" disabled>{{ $t('bbox.drawingButton') }}</button>
    <button v-else-if="!bbox" class="primary" @click="emit('startDraw')">{{ $t('bbox.draw') }}</button>
    <template v-else>
      <button
        class="primary"
        :disabled="!canSubmit"
        @click="bbox && emit('create', bbox, options)"
      >
        {{ $t('bbox.create') }}
      </button>
      <button class="redraw" :disabled="disabled" @click="emit('startDraw')">{{ $t('bbox.redraw') }}</button>
    </template>
  </div>
</template>
