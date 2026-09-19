import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'

// 两个页面:主页(地图工作台,含任务列表)和任务详情(2D/3D 查看)。
// 老的独立任务列表页并进了主页侧栏,旧链接重定向回主页。
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/tasks', redirect: '/' },
    {
      path: '/viewer/:id',
      name: 'viewer',
      component: () => import('@/views/ViewerView.vue'),
      props: true,
    },
  ],
})
