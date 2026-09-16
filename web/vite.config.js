import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import autoprefixer from 'autoprefixer'
import { defineConfig } from 'vite'

import { miniappDocs } from './scripts/miniapp-docs.mjs'

// 构建产物直接进 server/static/site,由 FastAPI 托管(生产机无需 node)
export default defineConfig({
  // miniappDocs:仓库根的 docs/miniapp/*.md 构建时转成 /developers 的页面数据(virtual:miniapp-docs)
  plugins: [react(), miniappDocs(fileURLToPath(new URL('..', import.meta.url)))],
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
    // 端口:给了 PORT 就用它(预览工具在 5173 被别的程序占着时会分配一个),
    // 并且严格占用 —— 自动顺延到 5174 会撞上商家后台,预览也等错端口。
    // 没给 PORT 时照旧是 vite 默认的 5173
    port: process.env.PORT ? Number(process.env.PORT) : undefined,
    strictPort: Boolean(process.env.PORT),
    // 本地开发时把数据接口代理到后端
    proxy: {
      '/stats': 'http://127.0.0.1:8010',
      // 首页服务台读哪些频道开着(和 App 金刚区同一份后台配置)
      '/channels': 'http://127.0.0.1:8010',
      // /nodes/summary(透明中心的见证节点卡)和 /nodes 那一页本身
      '/nodes': 'http://127.0.0.1:8010',
      '/ledger': 'http://127.0.0.1:8010',
      // 三端规则的改动留痕(开源仓页):/rules/{customer|merchant|rider}/revisions
      '/rules': 'http://127.0.0.1:8010',
      '/screen/stats': 'http://127.0.0.1:8010',
      '/screen/orders': 'http://127.0.0.1:8010',
      // 今日逐单(透明中心首屏)与它的 CSV:/transparency/today、/transparency/today.csv
      '/transparency/today': 'http://127.0.0.1:8010',
      '/transparency/audit': 'http://127.0.0.1:8010',
      '/transparency/funds': 'http://127.0.0.1:8010',
      '/transparency/compensation': 'http://127.0.0.1:8010',
      '/transparency/fairness': 'http://127.0.0.1:8010',
      '/transparency/reports': 'http://127.0.0.1:8010',
      '/transparency/changelog': 'http://127.0.0.1:8010',
      '/transparency/uptime': 'http://127.0.0.1:8010',
      '/transparency/dispatch': 'http://127.0.0.1:8010',
      '/transparency/governance': 'http://127.0.0.1:8010',
      '/transparency/liability': 'http://127.0.0.1:8010',
      // 小程序:公开目录、详情(/mini-apps/catalog、/mini-apps/<appid>)、透明中心那一栏、托管的图标截图
      '/mini-apps': 'http://127.0.0.1:8010',
      '/transparency/miniapps': 'http://127.0.0.1:8010',
      '/img': 'http://127.0.0.1:8010',
    },
  },
})
