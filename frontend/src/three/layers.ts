// 图层定义:名字和颜色与后端 LAYER_ORDER / PALETTE_3D 严格一致。
// GLB 里的节点名就是这些 key,靠它做图层显隐。

export interface LayerDef {
  /** GLB 节点名(大写) */
  key: string
  /** 界面上显示的中文名 */
  label: string
  /** 与后端 PALETTE_3D 同色 */
  color: string
}

export const LAYERS: LayerDef[] = [
  { key: 'TERRAIN', label: '地形', color: '#c8c3ba' },
  { key: 'GREEN', label: '绿地', color: '#b7d6a8' },
  { key: 'WATER', label: '水体', color: '#a8cfe8' },
  { key: 'BUILDING', label: '建筑', color: '#ded7cb' },
  { key: 'ROAD', label: '道路', color: '#a8a8a8' },
  { key: 'RAILWAY', label: '铁路', color: '#6b6f73' },
]

export type LayerKey = (typeof LAYERS)[number]['key']

/** 全部图层默认可见 */
export function defaultVisibility(): Record<LayerKey, boolean> {
  return Object.fromEntries(LAYERS.map((l) => [l.key, true])) as Record<LayerKey, boolean>
}
