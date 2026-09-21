<script setup lang="ts">
// 任务列表(住在主页侧栏里):进来拉一次数据,后续进度靠 WS/SSE 实时刷(store 已接管)。

import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, formatApiError } from '@/api/client'
import { useTasksStore } from '@/stores/tasks'
import TaskCard from './TaskCard.vue'

const props = defineProps<{ selectedId?: string | null }>()
const emit = defineEmits<{ goCreate: []; select: [id: string, bbox: [number, number, number, number]] }>()

const { t } = useI18n()
const store = useTasksStore()
const actionError = ref<string | null>(null)

onMounted(() => {
  if (!store.loaded || store.activeIds.size > 0) store.refresh()
})

async function cancel(id: string) {
  // 不等服务器回复,先把本地状态改成"已取消";取消的推送马上也会从 WS 过来。
  // 万一服务器没收下(比如点的那一瞬间任务恰好跑完了),把真实状态拉回来,
  // 不然卡片会一直挂在"已取消"上
  const task = store.tasks.find((x) => x.id === id)
  if (task) task.status = 'CANCELLED'
  try {
    await api.cancelTask(id)
  } catch (e) {
    actionError.value = t('taskList.cancelFailed', { msg: formatApiError(e) })
    void store.refreshOne(id)
  }
}

async function remove(id: string) {
  if (!confirm(t('taskList.deleteConfirm'))) return
  try {
    await store.remove(id)
  } catch (e) {
    actionError.value = t('taskList.deleteFailed', { msg: formatApiError(e) })
  }
}
</script>

<template>
  <div class="task-list">
    <div class="toolbar">
      <span class="total">{{ $t('taskList.total', { n: store.tasks.length }) }}</span>
      <button class="btn" :disabled="store.loading" @click="store.refresh()">
        {{ store.loading ? $t('taskList.refreshing') : $t('taskList.refresh') }}
      </button>
    </div>

    <p v-if="store.loaded && store.tasks.length === 0" class="empty">
      {{ $t('taskList.emptyPrefix') }}<a href="#" @click.prevent="emit('goCreate')">{{ $t('taskList.goCreate') }}</a>
    </p>

    <p v-if="actionError" class="error">{{ actionError }}</p>

    <div class="cards">
      <TaskCard
        v-for="t in store.tasks"
        :key="t.id"
        :task="t"
        :selected="t.id === props.selectedId"
        @select="emit('select', t.id, t.bbox)"
        @cancel="cancel"
        @remove="remove"
      />
    </div>
  </div>
</template>

<style scoped>
/* 上面是框选面板,这里用一条分隔线 + 小标题开头 */
.task-list {
  border-top: 1px solid var(--line);
  padding-top: 10px;
  margin-top: 10px;
}

.toolbar {
  margin-bottom: 8px;
}

.total {
  color: var(--muted);
  font-size: 13px;
}

.error {
  color: #c0392b;
  margin: 8px 0;
}
</style>
