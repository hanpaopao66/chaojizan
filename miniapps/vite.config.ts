// 两个官方小程序共用一份构建配置:vite build --mode notepad / --mode 2048
// 产物在 <app>/dist/pkg,再由 scripts/build_miniapp.sh 打成可复现的 zip。
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'

const here = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig(({ mode }) => {
  // 命令行的 --mode 2048 会被解析成数字,先转字符串再比
  const app = String(mode) === '2048' ? '2048' : 'notepad'
  return {
    root: resolve(here, app),
    // 托管地址是 /v/<版本号>/…,资源一律用相对路径
    base: './',
    publicDir: 'public',
    build: {
      outDir: 'dist/pkg',
      emptyOutDir: true,
      target: 'es2018',
      cssTarget: 'chrome61',
      assetsInlineLimit: 0,
      // CSP 是 script-src 'self':不要任何内联脚本
      modulePreload: { polyfill: false },
      sourcemap: false,
    },
    server: {
      port: app === '2048' ? 5191 : 5190,
      // SDK 源码在 packages/miniapp-sdk,开发服务器要能读到仓库根
      fs: { allow: [resolve(here, '..')] },
    },
  }
})
