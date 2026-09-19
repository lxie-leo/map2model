<script setup lang="ts">
// 导出记录:当前任务的历次导出 + 进度 + 下载/重试。
// 进度由 WS 事件实时推(exports store),进入页面时拉一次全量。

import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { urls } from '@/api/client'
import { useExportsStore } from '@/stores/exports'
import { ensureSubscribed } from '@/composables/useTaskEvents'

const props = defineProps<{ taskId: string }>()

const store = useExportsStore()
const retrying = ref<string | null>(null)
const error = ref<string | null>(null)

onMounted(() => {
  void store.load(props.taskId).catch(() => {})
  // 若当前是 SSE 模式,新导出也要能收到事件(WS 模式无影响)
  ensureSubscribed()
})

async function retry(format: string) {
  if (retrying.value) return // 手快连点会开出两个一样的导出
  retrying.value = format
  error.value = null
  try {
    const job = await api.createExport(props.taskId, format)
    store.add(job)
    ensureSubscribed()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    retrying.value = null
  }
}

const STATUS_LABEL: Record<string, string> = {
  QUEUED: '排队中',
  RUNNING: '导出中',
  COMPLETED: '完成',
  FAILED: '失败',
  CANCELLED: '取消',
}

/** 简短时间(月-日 时:分):下载列表里一屏好多条,全写年份太占地方 */
function fmtTime(iso: string): string {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
</script>

<template>
  <div class="export-jobs">
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="!store.byTask[taskId]?.length" class="empty">
      还没有导出记录,点右上"导出"按钮选格式
    </p>

    <div v-for="job in store.byTask[taskId]" :key="job.id" class="job" :data-status="job.status">
      <div class="row">
        <strong>{{ job.format }}</strong>
        <span class="status">{{ STATUS_LABEL[job.status] ?? job.status }}</span>
        <span v-if="job.status === 'RUNNING'">{{ Math.round(job.progress * 100) }}%</span>
        <span class="spacer"></span>
        <span class="time" :title="new Date(job.created_at).toLocaleString('zh-CN', { hour12: false })">
          {{ fmtTime(job.created_at) }}
        </span>
        <a
          v-if="job.status === 'COMPLETED'"
          class="btn"
          :href="urls.exportDownload(job.id)"
          :download="job.filename ?? ''"
        >
          下载
        </a>
        <button
          v-if="job.status === 'FAILED'"
          class="btn"
          :disabled="retrying !== null"
          @click="retry(job.format)"
        >
          {{ retrying === job.format ? '重试中…' : '重试' }}
        </button>
      </div>
      <div v-if="job.status === 'RUNNING' || job.status === 'QUEUED'" class="progress">
        <div class="bar" :style="{ width: job.progress * 100 + '%' }"></div>
      </div>
      <p v-if="job.error" class="error">{{ job.error }}</p>
      <p v-if="job.filename" class="filename">{{ job.filename }}</p>
    </div>
  </div>
</template>
