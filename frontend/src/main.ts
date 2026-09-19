import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './styles/main.css'

// 应用入口:把 Vue 应用挂到页面上,路由和 Pinia 也在这里装好
const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
