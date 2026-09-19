// 任务仓库的状态机测试:各种实时事件进来后,本地任务状态要正确翻转。

import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTasksStore } from './tasks'
import type { Task } from '@/api/types'

/** 造一个初始任务 */
function mkTask(status: Task['status'] = 'RUNNING'): Task {
  return {
    id: 't1',
    status,
    stage: 'FETCH_OVERPASS',
    progress: 5,
    bbox: [121.49, 31.234, 121.497, 31.2385],
    area_km2: 0.26,
    options: {
      buildings: true, roads: true, railways: true,
      water: true, green: true, terrain: true,
    },
    warnings: [],
    error: null,
    stats: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

describe('tasks store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('进度事件更新阶段和百分比,排队中自动转运行中', () => {
    const s = useTasksStore()
    s.upsertLocal(mkTask('QUEUED'))
    s.applyEvent({ type: 'task_progress', task_id: 't1', stage: 'BUILD_MESH', progress: 70 })
    const t = s.byId('t1')!
    expect(t.status).toBe('RUNNING')
    expect(t.stage).toBe('BUILD_MESH')
    expect(t.progress).toBe(70)
  })

  it('完成事件置 100%', () => {
    const s = useTasksStore()
    s.upsertLocal(mkTask())
    s.applyEvent({ type: 'task_done', task_id: 't1', progress: 100 })
    const t = s.byId('t1')!
    expect(t.status).toBe('COMPLETED')
    expect(t.progress).toBe(100)
  })

  it('失败事件带上错误信息', () => {
    const s = useTasksStore()
    s.upsertLocal(mkTask())
    s.applyEvent({ type: 'task_error', task_id: 't1', message: 'boom' })
    const t = s.byId('t1')!
    expect(t.status).toBe('FAILED')
    expect(t.error).toBe('boom')
  })

  it('警告事件去重追加', () => {
    const s = useTasksStore()
    s.upsertLocal(mkTask())
    s.applyEvent({ type: 'task_warning', task_id: 't1', message: '地形服务不可用' })
    s.applyEvent({ type: 'task_warning', task_id: 't1', message: '地形服务不可用' })
    expect(s.byId('t1')!.warnings).toEqual(['地形服务不可用'])
  })

  it('不在列表里的事件被安全忽略', () => {
    const s = useTasksStore()
    expect(() =>
      s.applyEvent({ type: 'task_done', task_id: '不存在', progress: 100 }),
    ).not.toThrow()
  })
})
