// 跑官方小程序的纯函数单测:esbuild 把 test/*.test.ts 打成 .mjs,再交给 node --test。
// (CI 的 Node 是 20,没有原生 TS;不引测试框架,少一个依赖)
//
//   node scripts/test.mjs            # 全部(CI / make analyze 跑的就是这一条)
//   node scripts/test.mjs cards      # 只跑一个:并行开发时几个小程序一起做,
//                                    # 全量会把别人还没写完的用例一起带上
//
// 输出目录带进程号:两个人同时跑不会互相删掉对方正在跑的用例。
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildSync } from 'esbuild'

const root = fileURLToPath(new URL('..', import.meta.url))
const apps = ['shared', 'notepad', '2048', 'snake', 'blocks', 'minesweeper', 'gomoku', 'critters',
  'sandbox', 'cards', 'tactical']
const only = process.argv.slice(2)
const unknown = only.filter((a) => !apps.includes(a))
if (unknown.length) {
  console.error(`✗ 不认识的小程序:${unknown.join('、')}(可选:${apps.join('、')})`)
  process.exit(2)
}
const picked = only.length ? only : apps
const out = join(root, `node_modules/.cache/sz-tests-${process.pid}`)
mkdirSync(out, { recursive: true })
const files = []
let missing = false
for (const app of picked) {
  const dir = join(root, app, 'test')
  if (!existsSync(dir)) {
    // 有 src/ 却没 test/ 是漏测,红;整个目录还没有是「这个小程序还没做」,跳过。
    // 后者只会在并行开发的半成品树里出现,提交前 build_miniapp.sh 会把该应用单测跑一遍。
    if (existsSync(join(root, app, 'src'))) {
      console.error(`✗ ${app} 有 src/ 却没有 test/ —— 纯函数单测不能少`)
      missing = true
    }
    continue
  }
  for (const f of readdirSync(dir).filter((x) => x.endsWith('.test.ts'))) {
    const target = join(out, `${app}-${f.replace(/\.ts$/, '.mjs')}`)
    buildSync({ entryPoints: [join(dir, f)], bundle: true, format: 'esm', platform: 'node',
      outfile: target, logLevel: 'warning', external: ['node:*'] })
    files.push(target)
  }
}
if (missing) process.exit(1)
if (!files.length) {
  console.error('✗ 一个用例都没找到')
  process.exit(1)
}
const r = spawnSync(process.execPath, ['--test', ...files], { stdio: 'inherit' })
// 跑完把自己这次的临时目录删掉,别让 node_modules/.cache 里积一堆 sz-tests-<pid>
rmSync(out, { recursive: true, force: true })
process.exit(r.status ?? 1)
