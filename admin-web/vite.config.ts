import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 构建产物进 server/static/admin,由 FastAPI 托管在 /admin-console
// (照 merchant-web 的先例,生产机无需 node)
//
// ⚠️ 路径**不能**叫 /admin —— 那是后端 API 的前缀(79 个接口都在下面),
// 静态站点抢了这个前缀,整个管理接口就全 404 了。
export default defineConfig({
  plugins: [react()],
  base: '/admin-console/',
  build: {
    outDir: '../server/static/admin',
    emptyOutDir: true,
    target: ['es2019', 'safari12'],
  },
  server: {
    // 5173 是官网、5174 是商家后台,这里占 5175。
    // strictPort:抢不到就报错而不是静默换号 —— 换了号会对着错的应用改半天
    port: 5175,
    strictPort: true,
    // ⚠️ `/admin` 必须写成正则 `^/admin/`,不能写成裸字符串。
    //
    // vite 的字符串键是**前缀匹配**,而这个站点自己挂在 `/admin-console/` ——
    // 它也以 `/admin` 开头,于是页面本身被转发给后端,拿回一个 404。
    // 踩过一次:build 通过、类型全绿、打开是「迷路了」。
    proxy: {
      '^/auth/': 'http://127.0.0.1:8010',
      '^/admin/': 'http://127.0.0.1:8010',
      '^/platform/': 'http://127.0.0.1:8010',
      '^/files/': 'http://127.0.0.1:8010',
      '^/uploads/': 'http://127.0.0.1:8010',
    },
  },
})
