// 和后端 app/schemas.py 一一对应的数据结构。
// 改动这里的字段时记得同步后端,否则页面会拿到 undefined。

/** 边界框:(西经, 南纬, 东经, 北纬) */
export type BBox = [number, number, number, number]

/** 地点搜索的一条结果;面状地点有范围,点状地点只有中心 */
export interface PlaceResult {
  name: string
  display_name: string
  bbox: BBox | null
  center: [number, number]
}

/** 任务的几种状态:排队 → 运行 → 完成/失败/取消 */
export type TaskStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

/** 任务处理的五个阶段,和后端的步骤一一对应 */
export type TaskStage =
  | 'FETCH_OVERPASS'
  | 'FETCH_TERRAIN'
  | 'PARSE_VECTOR'
  | 'BUILD_MESH'
  | 'WRITE_HUB'

/** 任务创建时的选项:六个图层开关 + 数据源/纠偏两个下拉 */
export interface TaskOptions {
  buildings: boolean
  roads: boolean
  railways: boolean
  water: boolean
  green: boolean
  terrain: boolean
  /** 建筑数据来源:auto = 中国区域自动合并 Overture(那里 OSM 建筑缺得多) */
  source: 'osm' | 'overture' | 'auto'
  /** GCJ-02 坐标纠偏(校正 Overture 中国建筑坐标的整体偏移):auto = 中国区域自动开 */
  rectify_gcj: 'auto' | 'on' | 'off'
}

export interface Task {
  id: string
  status: TaskStatus
  stage: TaskStage | null
  /** 0 ~ 100 的百分比 */
  progress: number
  bbox: BBox
  area_km2: number
  options: TaskOptions
  warnings: string[]
  error: string | null
  stats: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

/** WebSocket 推过来的任务事件(type 是广播出去的名字,如 task_progress / task_done) */
export interface TaskEvent {
  type: string
  id?: number
  task_id: string
  ts?: string
  event?: string
  stage?: TaskStage | null
  progress?: number | null
  message?: string | null
}

/** WebSocket 推送的导出事件 */
export interface ExportEvent {
  type: 'export_progress' | 'export_done' | 'export_error'
  task_id: string
  export_id: string
  format: string
  progress?: number | null
  message?: string | null
}

export interface ExportJob {
  id: string
  task_id: string
  format: string
  status: TaskStatus
  /** 0 ~ 1 的小数 */
  progress: number
  filename: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export interface Capabilities {
  version: string
  blender_path: string | null
  formats: Record<string, boolean>
  groups: Record<string, string[]>
}
