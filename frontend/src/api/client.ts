// 后端 REST API 的轻量封装(直接用 fetch,不引 axios)。
// 开发环境由 vite 把 /api 转发到 8000 端口,生产环境前后端在同一个域名下,不用配基础地址。

import type { BBox, Capabilities, ExportJob, PlaceResult, Task, TaskOptions } from './types'

const BASE = '/api/v1'

/** 后端报错的标准形状(detail 为字符串或 FastAPI 校验错误数组) */
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const body = await res.json()
      // 后端两种报错形状:FastAPI 校验错误在 detail 里,
      // 我们自己的错误在 error.message 里,都认一下
      detail = body.detail ?? body.error?.message ?? body
    } catch {
      // 非 JSON 错误体,保留 statusText
    }
    throw new ApiError(res.status, detail)
  }
  // 204 或空响应
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  health: () => request<{ status: string; version: string; time: string }>('/system/health'),

  capabilities: () => request<Capabilities>('/system/capabilities'),

  // ---- 地点搜索 ----

  geocode: (q: string) => request<PlaceResult[]>(`/geocode?q=${encodeURIComponent(q)}`),

  // ---- 任务 ----

  listTasks: (limit = 100) => request<Task[]>(`/tasks?limit=${limit}`),

  getTask: (id: string) => request<Task>(`/tasks/${id}`),

  createTask: (bbox: BBox, options: TaskOptions) =>
    request<Task>('/tasks', {
      method: 'POST',
      body: JSON.stringify({ bbox, options }),
    }),

  cancelTask: (id: string) => request<Task>(`/tasks/${id}/cancel`, { method: 'POST' }),

  deleteTask: (id: string) => request<{ deleted: string }>(`/tasks/${id}`, { method: 'DELETE' }),

  // ---- 导出 ----

  listExports: (taskId: string) => request<ExportJob[]>(`/tasks/${taskId}/exports`),

  createExport: (taskId: string, format: string, layers?: string[]) =>
    request<ExportJob>(`/tasks/${taskId}/exports`, {
      method: 'POST',
      // layers 不传 = 导全部图层(图层面板全开时)
      body: JSON.stringify({ format, layers }),
    }),
}

// ---- 各类文件地址(给 <a href> / three.js 加载器直接用) ----

export const urls = {
  /** WebSocket 实时事件流 */
  ws: () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${location.host}${BASE}/ws`
  },
  /** SSE 备用事件流(WS 连不上时用);query 参数由调用方自己拼,免得重复 */
  sse: (taskId: string) => `${BASE}/tasks/${taskId}/events`,
  /** 任务产物文件:hub.glb / preview.geojson / meta.json */
  taskFile: (taskId: string, filename: string) => `${BASE}/tasks/${taskId}/files/${filename}`,
  /** 2D 预览 GeoJSON */
  preview: (taskId: string) => `${BASE}/tasks/${taskId}/preview/geojson`,
  /** 导出结果下载 */
  exportDownload: (exportId: string) => `${BASE}/exports/${exportId}/download`,
}

/** 把后端 422 校验错误转成人话,列表页/表单直接展示 */
export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === 'string') return err.detail
    if (Array.isArray(err.detail)) {
      return err.detail
        .map((e: { msg?: string; loc?: unknown[] }) => `${(e.loc ?? []).join('.')}: ${e.msg ?? ''}`)
        .join('; ')
    }
    return JSON.stringify(err.detail)
  }
  return err instanceof Error ? err.message : String(err)
}
