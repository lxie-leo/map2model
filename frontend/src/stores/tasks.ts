// 任务列表仓库:列表数据 + 实时进度更新(由 useTaskEvents 喂事件进来)。

import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { Task, TaskEvent } from '@/api/types'
import { useExportsStore } from './exports'

export const useTasksStore = defineStore('tasks', {
  state: () => ({
    tasks: [] as Task[],
    loaded: false,
    loading: false,
  }),

  getters: {
    /** 活跃任务 = 还在排队或跑着的;网断重连后要给它们补开 SSE 接着收进度 */
    activeIds(state): Set<string> {
      return new Set(
        state.tasks.filter((t) => t.status === 'QUEUED' || t.status === 'RUNNING').map((t) => t.id),
      )
    },
    byId(state): (id: string) => Task | undefined {
      return (id) => state.tasks.find((t) => t.id === id)
    },
  },

  actions: {
    async refresh() {
      this.loading = true
      try {
        this.tasks = await api.listTasks()
        this.loaded = true
      } finally {
        this.loading = false
      }
    },

    /** 单个任务就地刷新(进入查看页时用,不重拉整个列表) */
    async refreshOne(id: string) {
      const t = await api.getTask(id)
      const idx = this.tasks.findIndex((x) => x.id === id)
      if (idx >= 0) this.tasks[idx] = t
      else this.tasks.unshift(t)
      return t
    },

    /** 把还在排队/跑着的任务都刷新一遍(断线重连后补状态用) */
    async refreshActive() {
      await Promise.allSettled([...this.activeIds].map((id) => this.refreshOne(id)))
    },

    upsertLocal(task: Task) {
      const idx = this.tasks.findIndex((x) => x.id === task.id)
      if (idx >= 0) this.tasks[idx] = task
      else this.tasks.unshift(task)
    },

    /** 应用一条实时任务事件(WS 或 SSE 来的都走这里) */
    applyEvent(ev: TaskEvent) {
      const idx = this.tasks.findIndex((x) => x.id === ev.task_id)
      const t = this.tasks[idx]
      if (!t) return // 不在列表里的事件直接忽略,需要时走 refreshOne
      if (ev.stage && ev.stage !== t.stage) t.stage = ev.stage
      if (typeof ev.progress === 'number') t.progress = ev.progress
      switch (ev.type) {
        case 'task_done':
          t.status = 'COMPLETED'
          t.progress = 100
          break
        case 'task_error':
          t.status = 'FAILED'
          t.error = ev.message ?? '任务失败'
          break
        case 'task_cancelled':
          t.status = 'CANCELLED'
          break
        case 'task_warning':
          if (ev.message && !t.warnings.includes(ev.message)) t.warnings.push(ev.message)
          break
        case 'task_queued':
          t.status = 'QUEUED'
          break
        case 'task_progress':
          if (t.status === 'QUEUED') t.status = 'RUNNING'
          break
      }
    },

    async remove(id: string) {
      await api.deleteTask(id)
      this.tasks = this.tasks.filter((t) => t.id !== id)
      // 这个任务的导出记录也别留在仓库里:任务删了之后事件流断了,
      // 残留的"进行中"导出会永远显示成没跑完
      const exportsStore = useExportsStore()
      delete exportsStore.byTask[id]
    },
  },
})
