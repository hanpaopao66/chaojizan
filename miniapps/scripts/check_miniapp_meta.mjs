// 官方小程序的标准化静态检查(GAME-STANDARD §6/§9)。
//
//   node scripts/check_miniapp_meta.mjs             # 全部
//   node scripts/check_miniapp_meta.mjs cards tower # 只查指定应用
//
// 查的是「结构 / 元数据 / 无外部素材 / 无内联脚本 / 包体 / 危险调试钩子」这些**静态就能判定**的规矩。
// 需要无头浏览器的项目(渲染、fps、console error)在 scripts/qa_miniapps.mjs 里,不进 CI。
// 退出码非 0 表示有 error;warning 只提示不挡。
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const CATEGORIES = new Set(['tools', 'productivity', 'life', 'learning', 'casual', 'puzzle'])
const ORIENTATIONS = new Set(['portrait', 'landscape', 'any'])
const KINDS = new Set(['app', 'game'])
//: 生产包里不该出现的调试钩子/开发便利名(加进 GAME-STANDARD 后这里同步)
const DEBUG_HOOKS = ['__tactical', 'placeAtSite', 'dev.frames', '__sandbox', '__cards', '__tower']
//: 编译/构建产物允许的扩展名:只有 html/js/css/json,任何图片/字体/音频都算外部素材
const CODE_EXT = new Set(['.html', '.js', '.mjs', '.css', '.json', '.ts', '.md'])

const args = process.argv.slice(2)
const ALL_APPS = readdirSync(root, { withFileTypes: true })
  .filter((d) => d.isDirectory() && existsSync(join(root, d.name, 'listing.json')))
  .map((d) => d.name)
  .sort()
const apps = args.length ? args : ALL_APPS
const unknown = apps.filter((a) => !ALL_APPS.includes(a))
if (unknown.length) {
  console.error(`✗ 不认识的应用:${unknown.join('、')}(可选:${ALL_APPS.join('、')})`)
  process.exit(2)
}

const errors = []
const warnings = []
const err = (app, msg) => errors.push(`[${app}] ${msg}`)
const warn = (app, msg) => warnings.push(`[${app}] ${msg}`)
const read = (p) => readFileSync(p, 'utf8')

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === 'dist') continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}

for (const app of apps) {
  const dir = join(root, app)
  const report = (msg) => err(app, msg)

  // ---- 1. 结构 ----
  for (const f of ['index.html', 'listing.json', 'public/superz.json']) {
    if (!existsSync(join(dir, f))) report(`缺文件 ${f}`)
  }
  // 老应用(标准之前做的)先提示、新游戏必须补:发布前按 GAME-STANDARD 自查
  if (!existsSync(join(dir, 'ASSETS.md'))) warn(app, '缺 ASSETS.md(素材来源与原创性说明;新游戏必须有)')
  if (!existsSync(join(dir, 'src'))) report('缺 src/ 目录(纯逻辑与界面要分开)')
  if (!existsSync(join(dir, 'test'))) report('缺 test/ 目录(纯函数单测不能少)')
  if (!existsSync(dir)) continue

  // ---- 2. listing.json ----
  let listing = {}
  try {
    listing = JSON.parse(read(join(dir, 'listing.json')))
  } catch (e) {
    report(`listing.json 不是合法 JSON:${e.message}`)
  }
  const req = ['name', 'icon', 'kind', 'category', 'version', 'changelog', 'tagline',
    'description', 'privacy_policy', 'data_declaration']
  for (const k of req) {
    if (!(k in listing)) report(`listing.json 缺字段 ${k}`)
  }
  if (listing.kind && !KINDS.has(listing.kind)) report(`listing.kind=${listing.kind} 只能是 app/game`)
  if (listing.category && !CATEGORIES.has(listing.category)) {
    report(`listing.category=${listing.category} 不在 ${[...CATEGORIES].join('/')} 里`)
  }
  if (listing.version && !/^\d+\.\d+\.\d+$/.test(String(listing.version))) {
    report(`listing.version=${listing.version} 要写成 x.y.z`)
  }
  if (listing.description && String(listing.description).length < 60) {
    warn('description 偏短(玩家看不到这个游戏是什么)')
  }
  if (listing.changelog && String(listing.changelog).length < 10) report('changelog 太短,更新了什么要写清楚')
  if (listing.privacy_policy && !String(listing.privacy_policy).includes('云存储')) {
    report('privacy_policy 没写云存储(用了 SaveSlot 就必须如实写)')
  }
  const decl = listing.data_declaration
  if (!Array.isArray(decl) || decl.length === 0) {
    report('data_declaration 必须是非空数组(收集什么、干什么用)')
  } else {
    for (const d of decl) {
      if (!d || typeof d !== 'object' || !d.field || !d.purpose) report('data_declaration 每项要有 field 和 purpose')
    }
  }
  if (listing.kind === 'game') {
    for (const phrase of ['没有广告', '没有内购', '没有排行榜']) {
      if (!String(listing.description || '').includes(phrase)) {
        report(`listing.description 要写明「${phrase}」(游戏的诚实边界)`)
      }
    }
  }
  if (!String(listing.name || '').trim()) report('listing.name 不能为空')

  // ---- 3. superz.json ----
  let manifest = {}
  try {
    manifest = JSON.parse(read(join(dir, 'public/superz.json')))
  } catch (e) {
    report(`public/superz.json 不是合法 JSON:${e.message}`)
  }
  if (manifest.sdk !== '2') report(`superz.json.sdk 必须是 "2",现在是 ${JSON.stringify(manifest.sdk)}`)
  if (manifest.kind !== listing.kind) report(`superz.json.kind=${manifest.kind} 与 listing.kind=${listing.kind} 不一致`)
  if (!ORIENTATIONS.has(String(manifest.orientation || 'portrait'))) {
    report(`superz.json.orientation=${manifest.orientation} 只能是 portrait / landscape / any`)
  }
  if (!/^#[0-9A-Fa-f]{6}$/.test(String(manifest.background_color || ''))) {
    report('superz.json.background_color 要写成 #RRGGBB')
  }
  if (typeof manifest.spa_fallback !== 'boolean') report('superz.json.spa_fallback 要是 true/false')

  // ---- 4. 文件扫描:外部素材 / 外部请求 / 内联脚本 / 调试钩子 ----
  const files = walk(dir)
  // 有 CC0 等公开授权素材的老应用(萌兽三路)在 ASSETS.md 里逐包写明了出处与许可证,
  // 属于已归档例外;新游戏按 GAME-STANDARD 必须全部程序化生成。
  const assetsDoc = existsSync(join(dir, 'ASSETS.md')) ? read(join(dir, 'ASSETS.md')) : ''
  const licensedAssets = /CC0|Creative Commons Zero|许可证/.test(assetsDoc)
  const binaryFiles = files.filter((f) => !CODE_EXT.has(extname(f).toLowerCase()))
  if (binaryFiles.length) {
    if (licensedAssets) warn(app, `有 ${binaryFiles.length} 个公开授权素材文件(ASSETS.md 已写明出处,属老应用例外)`)
    else report(`有 ${binaryFiles.length} 个外部素材文件(美术/音频/字体必须程序化生成),例如 ${relative(root, binaryFiles[0])}`)
  }
  const srcText = files
    .filter((f) => ['.ts', '.js', '.css', '.html'].includes(extname(f).toLowerCase()))
    .map((f) => ({ f, text: read(f) }))
  for (const { f, text } of srcText) {
    const rel = relative(root, f)
    if (/XMLHttpRequest|new\s+WebSocket|navigator\.sendBeacon/.test(text)) {
      report(`${rel} 有网络请求 —— 单机游戏不联网`)
    }
    for (const m of text.matchAll(/.{0,60}fetch\s*\(.{0,80}/g)) {
      if (/https?:/.test(m[0])) report(`${rel} 有外网 fetch —— 单机游戏不联网`)
      else warn(app, `${rel} 有 fetch(读取包内本地文件;新游戏应避免)`)
    }
    if (/(src|href)\s*=\s*["'](https?:)?\/\//i.test(text)) report(`${rel} 引用了外部地址(CSP 会拦、也不是单机)`)
    if (/\bconsole\.log\s*\(/.test(text)) warn(`${rel} 有 console.log(从游戏里出去)`)
  }
  if (existsSync(join(dir, 'index.html'))) {
    const html = read(join(dir, 'index.html'))
    if (/<script\b(?![^>]*\bsrc=)[^>]*>/i.test(html)) report('index.html 有内联 <script>(CSP script-src 是 self)')
    if (!/charset=["']?utf-8/i.test(html)) warn('index.html 缺 charset')
    if (!/name=["']viewport["']/i.test(html)) warn('index.html 缺 viewport')
    if (!/<title>[^<]+<\/title>/i.test(html)) warn('index.html 缺 <title>')
  }

  // ---- 5. 单测数量 ----
  const testDir = join(dir, 'test')
  if (existsSync(testDir)) {
    let n = 0
    for (const f of walk(testDir)) {
      if (!f.endsWith('.test.ts')) continue
      n += (read(f).match(/\btest\s*\(/g) || []).length
    }
    const floor = listing.kind === 'game' ? 10 : 5
    if (n < floor) report(`纯函数单测只有 ${n} 条(标准:${listing.kind === 'game' ? '游戏 ≥10、精品 ≥20' : '≥5'})`)
  }

  // ---- 6. 源码体积 ----
  for (const f of files) {
    if (extname(f) !== '.ts') continue
    const lines = read(f).split('\n').length
    if (lines > 800) warn(app, `${relative(root, f)} 有 ${lines} 行(标准:单文件 ≤ ~700 行)`)
  }

  // ---- 7. 构建产物(可选):包内容 / 包体 / 调试钩子 ----
  const pkgDir = join(dir, 'dist/pkg')
  if (existsSync(pkgDir)) {
    let total = 0
    const bad = []
    for (const f of walk(pkgDir)) {
      total += statSync(f).size
      const ext = extname(f).toLowerCase()
      if (!['.html', '.js', '.css', '.json'].includes(ext)) bad.push(relative(pkgDir, f))
    }
    if (bad.length) {
      if (licensedAssets) warn(app, `构建产物里有 ${bad.length} 个公开授权素材(ASSETS.md 已写明出处,属老应用例外)`)
      else report(`构建产物里有非代码文件(外部素材):${bad.slice(0, 6).join('、')}${bad.length > 6 ? '…' : ''}`)
    }
    if (total > 5 * 1024 * 1024) report(`构建产物 ${Math.round(total / 1024)} KB 超过 5 MB(小游戏上限 30MB,但我们要求更严)`)
    else if (total > 400 * 1024) warn(app, `构建产物 ${Math.round(total / 1024)} KB 超过 400 KB 预算`)
    for (const f of walk(pkgDir)) {
      const text = read(f)
      for (const hook of DEBUG_HOOKS) {
        if (text.includes(hook)) report(`生产构建里出现调试钩子「${hook}」(${relative(pkgDir, f)})`)
      }
    }
  }

  if (!errors.some((e) => e.startsWith(`[${app}]`))) {
    console.log(`✓ ${app}`)
  }
}

if (warnings.length) {
  console.log(`\n${warnings.length} 条提示:`)
  for (const w of warnings) console.log('  · ' + w)
}
if (errors.length) {
  console.error(`\n✗ ${errors.length} 条不通过:`)
  for (const e of errors) console.error('  · ' + e)
  process.exit(1)
}
console.log(`\n全部通过(${apps.length} 个应用,${warnings.length} 条提示)`)
