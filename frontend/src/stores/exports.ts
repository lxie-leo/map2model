// 导出任务仓库:按任务分组保存导出记录,实时更新进度。

import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { ExportEvent, ExportJob } from '@/api/types'
import { i18n } from '@/locales'

export const useExportsStore = defineStore('exports', {
  state: () => ({
    /** taskId -> 导出记录列表(最新在前,和后端返回的顺序一致) */
    byTask: {} as Record<string, ExportJob[]>,
    /** 正在补拉列表的任务,防抖用 */
    resyncing: {} as Record<string, boolean>,
  }),

  getters: {
    /** 有导出还在排队/跑着的任务号:SSE 模式下要给这些任务开着事件流收导出进度 */
    pendingTaskIds(state): Set<string> {
      const ids = new Set<string>()
      for (const [taskId, jobs] of Object.entries(state.byTask)) {
        if (jobs.some((j) => j.status === 'QUEUED' || j.status === 'RUNNING')) ids.add(taskId)
      }
      return ids
    },
  },

  actions: {
    async load(taskId: string) {
      const jobs = await api.listExports(taskId)
      this.byTask[taskId] = jobs // 后端就是最新在前,别再颠倒
    },

    add(job: ExportJob) {
      const list = this.byTask[job.task_id] ?? []
      this.byTask[job.task_id] = [job, ...list]
    },

    /** 列表和事件对不上账时重拉一遍(同一任务同时只拉一次) */
    async resync(taskId: string) {
      if (this.resyncing[taskId]) return
      this.resyncing[taskId] = true
      try {
        await this.load(taskId)
      } finally {
        this.resyncing[taskId] = false
      }
    },

    /** 应用一条实时导出事件 */
    applyEvent(ev: ExportEvent) {
      const list = this.byTask[ev.task_id]
      if (!list) {
        // 事件比"发起导出"的接口响应还快(小文件秒完成):列表里还没有这条,
        // 补拉一次,别让进度永远停在"排队中"
        this.resync(ev.task_id)
        return
      }
      const job = list.find((j) => j.id === ev.export_id)
      if (!job) {
        this.resync(ev.task_id)
        return
      }
      if (typeof ev.progress === 'number') job.progress = ev.progress
      if (ev.message) job.error = ev.type === 'export_error' ? ev.message : job.error
      if (ev.type === 'export_done') {
        job.status = 'COMPLETED'
        job.progress = 1
        job.filename = ev.message ?? job.filename
      } else if (ev.type === 'export_error') {
        job.status = 'FAILED'
        job.error = ev.message ?? i18n.global.t('export_.fallbackError')
      } else if (job.status === 'QUEUED') {
        job.status = 'RUNNING'
      }
    },
  },
})
