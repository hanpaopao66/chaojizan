// 构建 SDK:dist/sz-webapp.js(IIFE,挂 window.SuperZ.WebApp)、dist/sz-webapp.mjs、dist/index.d.ts,
// 再发布到 server/static/sdk/<版本>/(不可变)和 sdk/2/(最新 2.x)。打印 gzip 大小与 SRI。
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'
import * as esbuild from 'esbuild'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
const dist = join(root, 'dist')
mkdirSync(dist, { recursive: true })

const common = { entryPoints: [join(root, 'src/index.ts')], bundle: true, target: 'es2019',
  legalComments: 'inline', charset: 'utf8', logLevel: 'warning' }
await esbuild.build({ ...common, format: 'iife', minify: true, outfile: join(dist, 'sz-webapp.js') })
await esbuild.build({ ...common, format: 'esm', outfile: join(dist, 'sz-webapp.mjs') })
execFileSync(join(root, 'node_modules/.bin/tsc'), ['-p', root], { stdio: 'inherit' })

const js = readFileSync(join(dist, 'sz-webapp.js'))
const gz = gzipSync(js, { level: 9 }).length
const sri = 'sha384-' + createHash('sha384').update(js).digest('base64')
if (gz > 12 * 1024) {
  console.error(`sz-webapp.js gzip 后 ${gz} 字节,超过 12 KB 预算`)
  process.exit(1)
}

const server = join(root, '../../server/static/sdk')
// 2.x.y/ 下的文件**发布后不可变**:已经提交进仓库的版本,内容变了就拒绝覆盖 —— 改了代码要升版本号
const rel = `server/static/sdk/${pkg.version}/sz-webapp.js`
try {
  const committed = execFileSync('git', ['show', `HEAD:${rel}`], { cwd: root, stdio: ['ignore', 'pipe', 'ignore'] })
  if (!committed.equals(js) && !process.argv.includes('--force')) {
    console.error(`${rel} 已经发布过且内容不同。改了 SDK 请先升 package.json 的版本号`)
    process.exit(1)
  }
} catch (_) { /* 还没提交过这个版本 */ }
for (const dir of [pkg.version, pkg.version.split('.')[0]]) {
  mkdirSync(join(server, dir), { recursive: true })
  for (const f of ['sz-webapp.js', 'sz-webapp.mjs', 'index.d.ts']) {
    copyFileSync(join(dist, f), join(server, dir, f))
  }
}
// 老版本的条目留着:/_sdk/2.0.0/ 永远在线,钉了老版本 + SRI 的页面还要从这里查 integrity
const versionsFile = join(server, 'versions.json')
const known = existsSync(versionsFile) ? JSON.parse(readFileSync(versionsFile, 'utf8')) : {}
delete known.latest
writeFileSync(versionsFile, JSON.stringify({
  latest: pkg.version, ...known, [pkg.version]: { 'sz-webapp.js': { bytes: js.length, gzip: gz, integrity: sri } },
}, null, 2) + '\n')
console.log(`sz-webapp.js ${js.length} 字节,gzip ${gz} 字节;integrity ${sri}`)
