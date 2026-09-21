import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 开发时把 /api 和 /api/v1/ws 代理到本地后端(8000 端口)
export default defineConfig({
  plugins: [vue()],
  // vue-i18n 的两个编译开关:不用 legacy API、不开开发工具,
  // 声明掉能消掉打包时的一串 feature-flag 警告
  define: {
    __VUE_I18N_LEGACY_API__: false,
    __INTLIFY_PROD_DEVTOOLS__: false,
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // WebSocket 的键要放在普通 /api 前面,vite 按最长匹配处理
      '^/api/v1/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // three 和 maplibre 都是大件,各放一个文件,改业务代码时浏览器不用重新下载它们
    rollupOptions: {
      output: {
        manualChunks: {
          three: ['three'],
          maplibre: ['maplibre-gl'],
        },
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.spec.ts'],
  },
})
