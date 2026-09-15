// 官方小程序共用一份构建配置:vite build --mode <名字>(notepad / 2048 / snake / blocks / minesweeper / gomoku / critters)
// 产物在 <app>/dist/pkg,再由 scripts/build_miniapp.sh 打成可复现的 zip。
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'

const here = fileURLToPath(new URL('.', import.meta.url))

/** 小程序 → 开发服务器端口 */
const APPS: Record<string, number> = {
  notepad: 5190, '2048': 5191, snake: 5192, blocks: 5193, minesweeper: 5194, gomoku: 5195, critters: 5196,
}

export default defineConfig(({ mode }) => {
  // 命令行的 --mode 2048 会被解析成数字,先转字符串再比;不认识的名字按老规矩当 notepad
  const app = Object.prototype.hasOwnProperty.call(APPS, String(mode)) ? String(mode) : 'notepad'
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
      port: APPS[app],
      // SDK 源码在 packages/miniapp-sdk、小游戏共用的代码在 miniapps/shared,开发服务器要能读到仓库根
      fs: { allow: [resolve(here, '..')] },
    },
  }
})
