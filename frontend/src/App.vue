<script setup lang="ts">
// 根组件:不带顶部导航栏,页面自己铺满整屏(地图工具的形态);
// 页面一挂载就先连上后台的推送通道。

import { onMounted } from 'vue'
import { startLiveEvents } from '@/composables/useTaskEvents'
import { useSettingsStore } from '@/stores/settings'

onMounted(() => {
  startLiveEvents()
  // 先问一遍后端哪些格式能导出,点导出时不用现等;失败也不影响页面
  void useSettingsStore().loadCapabilities().catch(() => {})
})
</script>

<template>
  <main class="app-main">
    <!-- 主页用 KeepAlive 保活:进任务详情再返回时地图实例不销毁,
         瓦片不重载、视角原样;详情页不缓存(每次进不同任务都要重新拉数据) -->
    <router-view v-slot="{ Component }">
      <KeepAlive include="HomeView">
        <component :is="Component" />
      </KeepAlive>
    </router-view>
  </main>
</template>
