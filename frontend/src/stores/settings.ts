// 全局设置:底图切换(街道/卫星)+ 界面语言 + 后端能导出哪些格式的记录。

import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { Capabilities } from '@/api/types'
import { i18n, applyLocaleSideEffects, type AppLocale } from '@/locales'

export type BasemapId = 'osm' | 'satellite'

/** 底图候选:换源/加源改这里。
 *  osm 用德国镜像(免费无 key)——之前用 CARTO,它收紧了免费政策,
 *  不带 key 的请求会收到印着 "API KEY REQUIRED" 的占位瓦片,后来干脆连不上了 */
const BASEMAPS: { id: BasemapId; labelKey: string; tiles: string[]; attribution: string }[] = [
  {
    id: 'osm',
    labelKey: 'map.street',
    tiles: [
      'https://a.tile.openstreetmap.de/{z}/{x}/{y}.png',
      'https://b.tile.openstreetmap.de/{z}/{x}/{y}.png',
      'https://c.tile.openstreetmap.de/{z}/{x}/{y}.png',
    ],
    attribution: '© OpenStreetMap contributors',
  },
  {
    id: 'satellite',
    labelKey: 'map.satellite',
    // Esri 世界影像:注意模板里 y 在 x 前面
    tiles: [
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    ],
    attribution: 'Esri, Maxar, Earthstar Geographics',
  },
]

/** 按 id 取底图配置(BaseMap 铺图/换瓦片用);不认识的 id 兜底回街道图 */
export function basemapById(id: BasemapId) {
  return BASEMAPS.find((b) => b.id === id) ?? BASEMAPS[0]
}

/** 上次选过的底图(localStorage)> 默认街道图 */
function resolveInitialBasemap(): BasemapId {
  try {
    const saved = localStorage.getItem('m2m.basemap')
    if (saved === 'osm' || saved === 'satellite') return saved
  } catch {
    // node 环境没有 localStorage
  }
  return 'osm'
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    /** 当前底图:osm 街道 / satellite 卫星(地图上的换图由 BaseMap 盯 prop 完成) */
    basemap: resolveInitialBasemap(),

    /** 后端能力(哪些格式可导出),进首页时加载一次 */
    capabilities: null as Capabilities | null,

    /** 主页侧栏是否展开:窄窗口(≤900px)下侧栏是浮层,可收起给地图腾地方。
     *  只存内存:去查看页再回来状态不丢,刷新回默认展开 */
    sideOpen: true,

    /** 界面语言:初始值在 locales/index.ts 里探测(上次选择 > 浏览器语言) */
    locale: i18n.global.locale.value as AppLocale,
  }),

  actions: {
    /** 切底图:实例、本地记录两处一起动 */
    setBasemap(id: BasemapId) {
      this.basemap = id
      try {
        localStorage.setItem('m2m.basemap', id)
      } catch {
        // node 环境没有 localStorage
      }
    },

    /** 切语言:实例、本地记录、DOM 三处一起动 */
    setLocale(loc: AppLocale) {
      this.locale = loc
      i18n.global.locale.value = loc
      try {
        localStorage.setItem('m2m.locale', loc)
      } catch {
        // node 环境没有 localStorage
      }
      applyLocaleSideEffects()
    },

    async loadCapabilities() {
      if (this.capabilities) return this.capabilities
      this.capabilities = await api.capabilities()
      return this.capabilities
    },
  },
})
