// 全局设置:底图瓦片地址(想换底图改这里) + 后端能导出哪些格式的记录。

import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { Capabilities } from '@/api/types'

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
  }),

  actions: {
    async loadCapabilities() {
      if (this.capabilities) return this.capabilities
      this.capabilities = await api.capabilities()
      return this.capabilities
    },
  },
})
