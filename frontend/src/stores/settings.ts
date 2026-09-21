// 全局设置:底图瓦片地址(想换底图改这里) + 界面语言 + 后端能导出哪些格式的记录。

import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { Capabilities } from '@/api/types'
import { i18n, applyLocaleSideEffects, type AppLocale } from '@/locales'

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    /** OSM 德国镜像底图(免费无 key);想换源改这里即可。
     *  之前用 CARTO,它收紧了免费政策,不带 key 的请求会收到印着
     *  "API KEY REQUIRED" 的占位瓦片,后来干脆连不上了 */
    basemapTiles: [
      'https://a.tile.openstreetmap.de/{z}/{x}/{y}.png',
      'https://b.tile.openstreetmap.de/{z}/{x}/{y}.png',
      'https://c.tile.openstreetmap.de/{z}/{x}/{y}.png',
    ],
    basemapAttribution: '© OpenStreetMap contributors',

    /** 后端能力(哪些格式可导出),进首页时加载一次 */
    capabilities: null as Capabilities | null,

    /** 主页侧栏是否展开:窄窗口(≤900px)下侧栏是浮层,可收起给地图腾地方。
     *  只存内存:去查看页再回来状态不丢,刷新回默认展开 */
    sideOpen: true,

    /** 界面语言:初始值在 locales/index.ts 里探测(上次选择 > 浏览器语言) */
    locale: i18n.global.locale.value as AppLocale,
  }),

  actions: {
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
