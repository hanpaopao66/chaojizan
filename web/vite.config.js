import react from '@vitejs/plugin-react'
import autoprefixer from 'autoprefixer'
import { defineConfig } from 'vite'

// 构建产物直接进 server/static/site,由 FastAPI 托管(生产机无需 node)
export default defineConfig({
  plugins: [react()],
  base: '/site/',
  css: {
    postcss: { plugins: [autoprefixer()] },
  },
  build: {
    outDir: '../server/static/site',
    emptyOutDir: true,
    // 手机浏览器兼容:微信内置(X5/XWeb)、iOS Safari 12+、国产安卓壳浏览器
    target: ['es2019', 'safari12'],
  },
  server: {
    // 本地开发时把数据接口代理到后端
    proxy: {
      '/stats': 'http://127.0.0.1:8010',
      '/nodes/summary': 'http://127.0.0.1:8010',
      '/ledger': 'http://127.0.0.1:8010',
      '/screen/stats': 'http://127.0.0.1:8010',
      '/screen/orders': 'http://127.0.0.1:8010',
      '/transparency/audit': 'http://127.0.0.1:8010',
      '/transparency/funds': 'http://127.0.0.1:8010',
      '/transparency/compensation': 'http://127.0.0.1:8010',
      '/transparency/fairness': 'http://127.0.0.1:8010',
      '/transparency/reports': 'http://127.0.0.1:8010',
      '/transparency/changelog': 'http://127.0.0.1:8010',
      '/transparency/uptime': 'http://127.0.0.1:8010',
      '/transparency/governance': 'http://127.0.0.1:8010',
    },
  },
})
