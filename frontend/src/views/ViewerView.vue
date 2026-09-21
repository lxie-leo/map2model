<script setup lang="ts">
// 查看页:任务头部(状态/进度) + 三个标签(3D / 2D / 导出)。
// 任务运行中会自动等它完成;完成后 3D 面板自动加载 hub.glb。

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, formatApiError } from '@/api/client'
import { useTasksStore } from '@/stores/tasks'
import { ensureSubscribed } from '@/composables/useTaskEvents'
import { defaultVisibility, LAYERS, type LayerKey } from '@/three/layers'
import { tEnum, i18n } from '@/locales'
import ViewerTabs from '@/components/viewer/ViewerTabs.vue'
import SceneCanvas from '@/components/viewer/SceneCanvas.vue'
import LayerPanel from '@/components/viewer/LayerPanel.vue'
import Map2DPanel from '@/components/viewer/Map2DPanel.vue'
import ExportJobList from '@/components/viewer/ExportJobList.vue'
import ExportDialog from '@/components/viewer/ExportDialog.vue'

const props = defineProps<{ id: string }>()

const tasks = useTasksStore()
const tab = ref<'model3d' | 'map2d' | 'exports'>('model3d')
const visibility = ref<Record<LayerKey, boolean>>(defaultVisibility())
const viewMode = ref<'perspective' | 'top'>('perspective')
const showExportDialog = ref(false)
const error = ref<string | null>(null)
/** 模型版本号:任务每次进入"完成"都 +1,触发 3D 面板重新加载 */
const modelVersion = ref(0)

const task = computed(() => tasks.byId(props.id))

onMounted(async () => {
  await load()
})

// 浏览器后退/前进时,同一个页面组件会被复用,不会重新挂载,
// 得自己盯着地址栏里的任务号,变了就重新拉这个任务的详情
watch(
  () => props.id,
  () => load(),
)

async function load() {
  error.value = null
  try {
    await tasks.refreshOne(props.id)
    ensureSubscribed()
  } catch (e) {
    error.value = formatApiError(e)
  }
}

// 任务从运行中翻到"完成"时,刷新模型和导出记录
watch(
  () => task.value?.status,
  (now, before) => {
    if (now === 'COMPLETED' && before && before !== 'COMPLETED') {
      modelVersion.value++
    }
  },
)

const running = computed(
  () => task.value?.status === 'QUEUED' || task.value?.status === 'RUNNING',
)

/** 导出跟着图层走:只把当前开着的图层给导出接口。
 *  全开时不传(后端走"整包"快路径,GLB 直接复制文件都不用重新打包) */
const exportLayers = computed(() => {
  const on = LAYERS.filter((l) => visibility.value[l.key]).map((l) => l.key)
  return on.length === LAYERS.length ? undefined : on
})

/** "正在下载"的顶部提示:导出提交成功后弹出来,几秒后自己消失 */
const notice = ref<string | null>(null)
let noticeTimer: ReturnType<typeof setTimeout> | null = null

function showDownloadNotice() {
  notice.value = i18n.global.t('export_.downloadNotice')
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => (notice.value = null), 4000)
}

function goDownloads() {
  tab.value = 'exports'
  notice.value = null
}

onBeforeUnmount(() => {
  if (noticeTimer) clearTimeout(noticeTimer)
})
</script>

<template>
  <div class="viewer-view">
    <p v-if="error" class="error center-hint">{{ error }} <router-link to="/">{{ $t('viewer.back') }}</router-link></p>

    <template v-else-if="task">
      <div class="viewer-body" :data-tab="tab">
        <div v-show="tab === 'model3d'" class="pane pane-3d">
          <!-- 任务没跑完就去拉模型文件必然 404,等完成了再挂 3D 画布 -->
          <template v-if="task.status === 'COMPLETED'">
            <SceneCanvas
              :task-id="id"
              :visibility="visibility"
              :view-mode="viewMode"
              :key="`${id}-${modelVersion}`"
            />
            <!-- 图层/视角浮在场景右下角 -->
            <LayerPanel v-model:visibility="visibility" v-model:view-mode="viewMode" />
          </template>
          <p v-else class="hint">{{ $t('viewer.wait3d') }}</p>
        </div>
        <div v-show="tab === 'map2d'" class="pane">
          <Map2DPanel v-if="task.status === 'COMPLETED'" :key="id" :task-id="id" :bbox="task.bbox" />
          <p v-else class="hint">{{ $t('viewer.wait2d') }}</p>
        </div>
        <div v-show="tab === 'exports'" class="pane pane-exports">
          <ExportJobList :key="id" :task-id="id" />
        </div>

        <!-- 没有顶栏:任务信息浮在左上,标签和导出按钮浮在右上 -->
        <div class="hud hud-info">
          <router-link to="/" class="back">{{ $t('viewer.back') }}</router-link>
          <span class="id">{{ $t('task.idLabel', { id: task.id.slice(0, 10) }) }}</span>
          <span class="area">{{ task.area_km2.toFixed(3) }} km²</span>
          <div v-if="running" class="progress">
            <div class="bar" :style="{ width: task.progress + '%' }"></div>
            <span class="pct">
              {{ Math.round(task.progress) }}% ·
              {{ task.stage ? tEnum(`task.stage.${task.stage}`) : $t('task.status.QUEUED') }}
            </span>
          </div>
          <span v-else-if="task.error" class="error" :title="task.error">{{ task.error }}</span>
        </div>

        <div class="hud hud-actions">
          <ViewerTabs v-model:tab="tab" />
          <button class="btn primary" :disabled="running" @click="showExportDialog = true">
            {{ $t('export_.exportButton') }}
          </button>
        </div>

        <!-- 导出提交成功后顶部的短暂提示,带直达下载页的入口 -->
        <div v-if="notice" class="hud export-notice">
          ⬇ {{ notice }}
          <a @click="goDownloads">{{ $t('export_.goDownloads') }}</a>
        </div>

        <p v-for="w in task.warnings" :key="w" class="hud hud-warning">⚠ {{ w }}</p>
      </div>
    </template>

    <p v-else class="hint center-hint">{{ $t('viewer.loading') }}</p>

    <ExportDialog
      v-if="showExportDialog"
      :task-id="id"
      :layers="exportLayers"
      @done="showDownloadNotice"
      @close="showExportDialog = false"
    />
  </div>
</template>
