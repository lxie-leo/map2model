<script setup lang="ts">
// 主页(地图工作台):左边全屏地图,右边侧栏一竖到底——
// 上面是框选面板,下面紧跟任务列表。生成后不跳走:按钮变回"框选",
// 新任务卡片出现在列表里实时跑进度,想看 3D 再点"查看"。

import { computed, ref, shallowRef } from 'vue'
import type { Map as MlMap } from 'maplibre-gl'
import BaseMap from '@/components/map/BaseMap.vue'
import SelectRect from '@/components/map/SelectRect.vue'
import MapSearch from '@/components/map/MapSearch.vue'
import BboxPanel from '@/components/map/BboxPanel.vue'
import TaskList from '@/components/tasks/TaskList.vue'
import { api, formatApiError } from '@/api/client'
import type { BBox, PlaceResult, TaskOptions } from '@/api/types'
import { useTasksStore } from '@/stores/tasks'
import { useSettingsStore } from '@/stores/settings'
import { ensureSubscribed, liveStatus } from '@/composables/useTaskEvents'

const tasks = useTasksStore()
const settings = useSettingsStore()

const map = shallowRef<MlMap | null>(null)
const bbox = ref<BBox | null>(null)
// 点任务列表某张卡片时,地图上回显那个任务的框选范围
const highlight = ref<BBox | null>(null)
const selectedTaskId = ref<string | null>(null)
// 框选模式:点了"框选"到画完/取消之间,地图锁住不让拖
const drawing = ref(false)
const creating = ref(false)
const error = ref<string | null>(null)

// 地图上实际画的框:自己刚框的优先,其次才是任务回显
const displayBox = computed(() => bbox.value ?? highlight.value)

const STATUS_TEXT = {
  ws: '实时通道已连接',
  sse: '实时通道:备用模式',
  offline: '正在连接实时通道…',
} as const

function onReady(m: MlMap) {
  map.value = m
}

function startDraw() {
  bbox.value = null // 重选就把旧框抹掉
  highlight.value = null
  selectedTaskId.value = null
  error.value = null
  drawing.value = true
}

// 画完(或没画成)都会回到普通状态,地图恢复拖动
function onRectChange(b: BBox | null) {
  bbox.value = b
  if (b) {
    // 有了自己的新框,任务回显让位
    highlight.value = null
    selectedTaskId.value = null
  }
  drawing.value = false
}

function onRectExit() {
  drawing.value = false
}

// 任务列表里"去框一块"的引导:直接进入框选模式
function goCreate() {
  startDraw()
}

// 地点搜索选中一条:视角飞到那个地方。有范围的框进去,只有中心的飞到点上
function flyToPlace(p: PlaceResult) {
  if (p.bbox) {
    const b = p.bbox
    map.value?.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 60, duration: 800 })
  } else {
    map.value?.jumpTo({ center: p.center, zoom: 15 })
  }
}

// 点任务卡片:在地图上回显它的框选范围,视角飞过去;再点一次同一张就取消回显
function selectTask(id: string, b: BBox) {
  // 还挂在框选模式的话一并退出:不然地图锁着十字光标,回显框一碰左键就被新框顶掉
  drawing.value = false
  if (selectedTaskId.value === id) {
    highlight.value = null
    selectedTaskId.value = null
  } else {
    highlight.value = b
    selectedTaskId.value = id
    bbox.value = null
    // 视角飞过去,让框完整落在视野中间(四周留一圈余量)
    map.value?.fitBounds(
      [[b[0], b[1]], [b[2], b[3]]],
      { padding: 60, duration: 600 },
    )
  }
}

async function create(b: BBox, options: TaskOptions) {
  creating.value = true
  error.value = null
  try {
    const task = await api.createTask(b, options)
    tasks.upsertLocal(task)
    ensureSubscribed() // SSE 模式下要给新任务补开事件流
    // 成功就留在本页:清掉框,按钮回到"框选",进度看下方列表
    bbox.value = null
  } catch (e) {
    error.value = formatApiError(e)
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <!-- 窄窗口下侧栏是浮层,side-closed 表示收起(宽屏下这个 class 没有任何效果) -->
  <div class="home-view" :class="{ 'side-closed': !settings.sideOpen }">
    <div class="map-wrap">
      <BaseMap @ready="onReady" />
      <MapSearch @pick="flyToPlace" />
      <SelectRect
        :map="map"
        :active="drawing"
        :bbox="displayBox"
        @change="onRectChange"
        @exit="onRectExit"
      />
      <!-- 侧栏收起后才出现的"面板"按钮,点开侧栏 -->
      <button
        v-if="!settings.sideOpen"
        type="button"
        class="hud side-fab"
        title="展开侧栏"
        @click="settings.sideOpen = true"
      >☰ 面板</button>
    </div>
    <aside class="side">
      <div class="side-brand">
        <span>map2model</span>
        <!-- 语言切换:两个小钮,点哪个界面就整体换哪种话 -->
        <span class="lang-switch" :title="$t('app.lang')">
          <button
            type="button"
            :class="{ on: settings.locale === 'zh-CN' }"
            @click="settings.setLocale('zh-CN')"
          >中</button><button
            type="button"
            :class="{ on: settings.locale === 'en' }"
            @click="settings.setLocale('en')"
          >EN</button>
        </span>
        <button
          type="button"
          class="side-x"
          title="收起侧栏"
          @click="settings.sideOpen = false"
        >»</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <BboxPanel
        :bbox="bbox"
        :drawing="drawing"
        :disabled="creating"
        @create="create"
        @start-draw="startDraw"
      />
      <!-- 框选面板钉在上面不动,任务列表在自己的滚动区里滚 -->
      <div class="task-scroll">
        <TaskList :selected-id="selectedTaskId" @select="selectTask" @go-create="goCreate" />
      </div>
      <div class="backend-tip">
        <span class="dot" :class="liveStatus"></span>
        {{ STATUS_TEXT[liveStatus] }}
      </div>
    </aside>
  </div>
</template>
