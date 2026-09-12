import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 小程序开发者后台(DEV-PROMPTS-39 #330)。构建产物进 server/static/dev,由 FastAPI 挂在 /dev/,
// 接口在 /dev/v1/ —— 同源,不用配 CORS。页面路由不会以 v1 开头(见 main.py 的 developer_console)。
const api = process.env.SUPERZ_API || 'http://127.0.0.1:8010'

export default defineConfig({
  plugins: [react()],
  base: '/dev/',
  build: {
    outDir: '../server/static/dev',
    emptyOutDir: true,
    target: ['es2019', 'safari12'],
  },
  server: {
    // 5173 官网、5174 商家后台、5175 平台后台,这里占 5176
    port: 5176,
    strictPort: true,
    // changeOrigin:让后端看到的 Host 是它自己 —— 模拟器的托管地址由后端按 Host 拼出来,
    // 不改的话托管页会和这个后台同源,iframe 的 allow-same-origin 就能读到开发者的登录 token
    proxy: Object.fromEntries(['^/dev/v1/', '^/auth/', '^/upload', '^/files/', '^/img/', '^/rules/', '^/mini-apps/']
      .map((k) => [k, { target: api, changeOrigin: true }])),
  },
})
