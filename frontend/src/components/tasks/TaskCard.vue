<script setup lang="ts">
// 单张任务卡片:状态徽章 + 进度条 + 概要信息 + 操作按钮。

import type { Task } from '@/api/types'

defineProps<{ task: Task; selected?: boolean }>()
const emit = defineEmits<{
  cancel: [id: string]
  remove: [id: string]
  select: []
}>()

const STAGE_LABELS: Record<string, string> = {
  FETCH_OVERPASS: '拉取 OSM 数据',
  FETCH_TERRAIN: '拉取地形高程',
  PARSE_VECTOR: '解析矢量要素',
  BUILD_MESH: '构建三维网格',
  WRITE_HUB: '写出模型文件',
}

const STATUS_LABELS: Record<string, string> = {
  QUEUED: '排队中',
  RUNNING: '运行中',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <!-- 点卡片本体 = 选中,地图上回显框选范围;点按钮别触发选中 -->
  <div
    class="task-card"
    :class="{ selected }"
    :data-status="task.status"
    title="点击在地图上显示框选范围"
    @click="emit('select')"
  >
    <div class="row1">
      <span class="badge" :class="task.status.toLowerCase()">{{ STATUS_LABELS[task.status] }}</span>
      <span class="id" :title="task.id">{{ task.id.slice(0, 10) }}</span>
      <span class="time">{{ fmtTime(task.created_at) }}</span>
    </div>

    <div class="row2">
      <span class="area">{{ task.area_km2.toFixed(3) }} km²</span>
    </div>

    <div v-if="task.status === 'RUNNING' || task.status === 'QUEUED'" class="progress">
      <div class="bar" :style="{ width: task.progress + '%' }"></div>
      <!-- 阶段文字挪进进度条里,不再和面积挤一行(详情页就是这个排法) -->
      <span class="pct">
        {{ task.status === 'QUEUED'
          ? '排队中'
          : task.stage
            ? `${Math.round(task.progress)}% · ${STAGE_LABELS[task.stage] ?? task.stage}`
            : `${Math.round(task.progress)}%`
        }}
      </span>
    </div>

    <p v-if="task.error" class="error">{{ task.error }}</p>
    <p v-for="w in task.warnings.slice(0, 2)" :key="w" class="warning">⚠ {{ w }}</p>

    <div class="actions" @click.stop>
      <router-link :to="`/viewer/${task.id}`" class="btn">查看</router-link>
      <button
        v-if="task.status === 'QUEUED' || task.status === 'RUNNING'"
        class="btn"
        @click="emit('cancel', task.id)"
      >
        取消
      </button>
      <button class="btn danger" @click="emit('remove', task.id)">删除</button>
    </div>
  </div>
</template>
