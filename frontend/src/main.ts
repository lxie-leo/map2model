import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { i18n, applyLocaleSideEffects } from './locales'
import './styles/main.css'

// 应用入口:把 Vue 应用挂到页面上,路由、Pinia 和 i18n 也在这里装好
const app = createApp(App)
app.use(createPinia())
app.use(i18n)
app.use(router)
app.mount('#app')
// index.html 里的静态 title/lang 只是首帧兜底,挂载完立刻按语言校正
applyLocaleSideEffects()
