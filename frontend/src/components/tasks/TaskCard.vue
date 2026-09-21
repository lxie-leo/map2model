<script setup lang="ts">
// 单张任务卡片:状态徽章 + 进度条 + 概要信息 + 操作按钮。

import type { Task } from '@/api/types'
import { tEnum } from '@/locales'
import { fmtDateTime } from '@/utils/datetime'

defineProps<{ task: Task; selected?: boolean }>()
const emit = defineEmits<{
  cancel: [id: string]
  remove: [id: string]
  select: []
}>()
</script>

<template>
  <!-- 点卡片本体 = 选中,地图上回显框选范围;点按钮别触发选中 -->
  <div
    class="task-card"
    :class="{ selected }"
    :data-status="task.status"
    :title="$t('task.cardTitle')"
    @click="emit('select')"
  >
    <div class="row1">
      <span class="badge" :class="task.status.toLowerCase()">{{ tEnum(`task.status.${task.status}`) }}</span>
      <span class="id" :title="task.id">{{ task.id.slice(0, 10) }}</span>
      <span class="time">{{ fmtDateTime(task.created_at) }}</span>
    </div>

    <div class="row2">
      <span class="area">{{ task.area_km2.toFixed(3) }} km²</span>
    </div>

    <div v-if="task.status === 'RUNNING' || task.status === 'QUEUED'" class="progress">
      <div class="bar" :style="{ width: task.progress + '%' }"></div>
      <!-- 阶段文字挪进进度条里,不再和面积挤一行(详情页就是这个排法) -->
      <span class="pct">
        {{ task.status === 'QUEUED'
          ? $t('task.status.QUEUED')
          : task.stage
            ? `${Math.round(task.progress)}% · ${tEnum(`task.stage.${task.stage}`)}`
            : `${Math.round(task.progress)}%`
        }}
      </span>
    </div>

    <p v-if="task.error" class="error">{{ task.error }}</p>
    <p v-for="w in task.warnings.slice(0, 2)" :key="w" class="warning">⚠ {{ w }}</p>

    <div class="actions" @click.stop>
      <router-link :to="`/viewer/${task.id}`" class="btn">{{ $t('task.view') }}</router-link>
      <button
        v-if="task.status === 'QUEUED' || task.status === 'RUNNING'"
        class="btn"
        @click="emit('cancel', task.id)"
      >
        {{ $t('task.cancel') }}
      </button>
      <button class="btn danger" @click="emit('remove', task.id)">{{ $t('task.remove') }}</button>
    </div>
  </div>
</template>
