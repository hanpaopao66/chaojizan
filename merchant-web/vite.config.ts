import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 构建产物直接进 server/static/merchant,由 FastAPI 托管在 /merchant
// (照 web/ 官网的先例,生产机无需 node)
export default defineConfig({
  plugins: [react()],
  base: '/merchant/',
  build: {
    outDir: '../server/static/merchant',
    emptyOutDir: true,
    target: ['es2019', 'safari12'],
  },
  server: {
    // 本地开发把接口代理到后端(含 WebSocket)
    proxy: {
      '/auth': 'http://127.0.0.1:8010',
      '/merchants': 'http://127.0.0.1:8010',
      '/stays': 'http://127.0.0.1:8010',
      '/vouchers': 'http://127.0.0.1:8010',
      '/invoices': 'http://127.0.0.1:8010',
      '/orders': 'http://127.0.0.1:8010',
      '/uploads': 'http://127.0.0.1:8010',
      '/platform': 'http://127.0.0.1:8010',
      '/tickets': 'http://127.0.0.1:8010',
      '/ws': { target: 'ws://127.0.0.1:8010', ws: true },
    },
  },
})
