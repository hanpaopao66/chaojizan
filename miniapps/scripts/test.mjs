// 跑官方小程序的纯函数单测:esbuild 把 test/*.test.ts 打成 .mjs,再交给 node --test。
// (CI 的 Node 是 20,没有原生 TS;不引测试框架,少一个依赖)
import { spawnSync } from 'node:child_process'
import { mkdirSync, readdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildSync } from 'esbuild'

const root = fileURLToPath(new URL('..', import.meta.url))
const out = join(root, 'node_modules/.cache/sz-tests')
rmSync(out, { recursive: true, force: true })
mkdirSync(out, { recursive: true })
const files = []
// shared 是小游戏共用的存档和随机数
for (const app of ['shared', 'notepad', '2048', 'snake', 'blocks', 'minesweeper', 'gomoku', 'critters']) {
  const dir = join(root, app, 'test')
  for (const f of readdirSync(dir).filter((x) => x.endsWith('.test.ts'))) {
    const target = join(out, `${app}-${f.replace(/\.ts$/, '.mjs')}`)
    buildSync({ entryPoints: [join(dir, f)], bundle: true, format: 'esm', platform: 'node',
      outfile: target, logLevel: 'warning', external: ['node:*'] })
    files.push(target)
  }
}
const r = spawnSync(process.execPath, ['--test', ...files], { stdio: 'inherit' })
process.exit(r.status ?? 1)
