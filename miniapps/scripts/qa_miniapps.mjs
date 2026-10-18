// 官方小游戏的无头浏览器验收(GAME-STANDARD §7/§9)。
//
//   node scripts/qa_miniapps.mjs                 # 所有已构建的应用
//   node scripts/qa_miniapps.mjs cards tower     # 只查指定应用(没构建就直接失败)
//
// 每个应用:起一个本地静态服务器 → headless Chrome 打开 `?sz_mock=1` →
//   首屏截图 / 点开始 / 操作截图 / 暗色+减少动态截图 / 桌面视口截图 / 刷新续档截图
//   → 断言:console error 0、pageerror 0、外部请求 0、内联脚本 0、无横向溢出、
//          aria-live ≥ 1(精品游戏)、~60fps、标题与正文非空。
// 产物:/tmp/qa-miniapps/<app>/*.png + report.json。依赖 `web/node_modules` 里的 puppeteer-core
// 和本机 Chrome;发布前手动跑,不进 CI(CI 没有 Chrome)。
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const repo = fileURLToPath(new URL('../..', import.meta.url))
const OUT = '/tmp/qa-miniapps'
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
/** 精品游戏:必须有 aria-live、开始按钮要能点到 */
const FLAGSHIP = new Set(['sandbox', 'cards', 'tactical', 'tower'])
/** 点开始按钮的候选文案(不同游戏叫法不同,按顺序找第一个可见的) */
const START_TEXTS = ['开始游戏', '开始对局', '开始行动', '开始新世界', '开始挑战', '开始',
  '新游戏', '新建笔记', '继续游戏', '继续对局', '继续', '闯关']

const args = process.argv.slice(2)
const require = createRequire(join(repo, 'web', 'package.json'))
let puppeteer
try {
  puppeteer = require('puppeteer-core')
} catch (e) {
  console.error('✗ 找不到 puppeteer-core(装在 web/node_modules 下)')
  process.exit(2)
}
if (!existsSync(CHROME)) {
  console.error(`✗ 找不到 Chrome:${CHROME}`)
  process.exit(2)
}

const allApps = readdirSync(join(root)).filter((a) => existsSync(join(root, a, 'listing.json')))
const apps = args.length ? args : allApps
const unknown = apps.filter((a) => !allApps.includes(a))
if (unknown.length) {
  console.error(`✗ 不认识的应用:${unknown.join('、')}`)
  process.exit(2)
}
const explicit = args.length > 0
const missing = apps.filter((a) => !existsSync(join(root, a, 'dist/pkg')))
if (missing.length) {
  if (explicit) {
    console.error(`✗ 这些应用还没有构建产物,先跑 bash scripts/build_miniapp.sh <app>:${missing.join('、')}`)
    process.exit(2)
  }
  console.log(`(跳过未构建的应用:${missing.join('、')})`)
}
const runnable = apps.filter((a) => existsSync(join(root, a, 'dist/pkg')))

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function serve(app, port) {
  const cwd = join(root, app, 'dist/pkg')
  const p = spawn('python3', ['-m', 'http.server', String(port)], { cwd, stdio: 'ignore' })
  return p
}

async function waitServer(port) {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/`, { signal: AbortSignal.timeout(500) })
      if (r.ok) return
    } catch { /* 还没起来 */ }
    await sleep(100)
  }
  throw new Error(`本地服务器 ${port} 没起来`)
}

async function metrics(page) {
  return page.evaluate(() => {
    const doc = document.documentElement
    const buttons = [...document.querySelectorAll('button')]
    return {
      title: document.title,
      bodyText: (document.body.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 200),
      inner: [innerWidth, innerHeight],
      scroll: [doc.scrollWidth, doc.scrollHeight],
      overflowX: doc.scrollWidth > innerWidth + 1,
      inlineScripts: document.querySelectorAll('script:not([src])').length,
      buttons: buttons.length,
      namelessButtons: buttons.filter((b) => !(b.textContent || '').trim() && !b.getAttribute('aria-label')).length,
      live: document.querySelectorAll('[aria-live]').length,
    }
  })
}

async function fps(page) {
  return page.evaluate(() => new Promise((resolve) => {
    let n = 0
    const t0 = performance.now()
    const tick = () => {
      n++
      const dt = performance.now() - t0
      if (dt >= 1500) resolve(Math.round(n / (dt / 1000)))
      else requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }))
}

async function clickStart(page) {
  for (const text of START_TEXTS) {
    const ok = await page.evaluate((t) => {
      const b = [...document.querySelectorAll('button')].find((x) =>
        (x.textContent || '').replace(/\s+/g, '').includes(t) && !x.disabled && x.getClientRects().length > 0)
      if (!b) return false
      b.click()
      return true
    }, text)
    if (ok) return text
  }
  return null
}

function orientationOf(app) {
  try {
    const m = JSON.parse(readFileSync(join(root, app, 'public/superz.json'), 'utf8'))
    return m.orientation === 'landscape' ? 'landscape' : 'portrait'
  } catch {
    return 'portrait'
  }
}

mkdirSync(OUT, { recursive: true })
const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--autoplay-policy=no-user-gesture-required'],
})

const results = []
for (let i = 0; i < runnable.length; i++) {
  const app = runnable[i]
  const port = 5601 + i
  const outDir = join(OUT, app)
  mkdirSync(outDir, { recursive: true })
  const server = serve(app, port)
  const errors = []
  const pageErrors = []
  const external = []
  const failed = []
  try {
    await waitServer(port)
    const page = await browser.newPage()
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)) })
    page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 200)))
    page.on('requestfailed', (r) => failed.push(`${r.url().slice(0, 120)} ${r.failure()?.errorText || ''}`))
    page.on('request', (r) => {
      const u = r.url()
      if (!u.startsWith(`http://127.0.0.1:${port}`) && !u.startsWith('data:') && !u.startsWith('blob:')) {
        external.push(u.slice(0, 160))
      }
    })
    const orientation = orientationOf(app)
    const size = orientation === 'landscape' ? { width: 844, height: 390 } : { width: 390, height: 844 }
    await page.setViewport({ ...size, isMobile: true, hasTouch: true })
    await page.goto(`http://127.0.0.1:${port}/?sz_mock=1`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(1500)
    await page.screenshot({ path: join(outDir, '1-home.png') })
    const home = await metrics(page)
    const startClicked = await clickStart(page)
    await sleep(2500)
    await page.screenshot({ path: join(outDir, '2-started.png') })
    // 基础输入:方向键 + 点击屏幕中央(不假设具体玩法)
    for (const k of ['ArrowRight', 'ArrowDown']) await page.keyboard.press(k)
    await page.mouse.click(size.width / 2, size.height / 2)
    await sleep(1200)
    await page.screenshot({ path: join(outDir, '3-action.png') })
    const action = await metrics(page)
    const frames = await fps(page)
    // 暗色 + 减少动态
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' },
      { name: 'prefers-reduced-motion', value: 'reduce' }])
    await sleep(700)
    await page.screenshot({ path: join(outDir, '4-dark-reduced.png') })
    // 桌面视口
    await page.setViewport({ width: 1280, height: 800 })
    await sleep(700)
    await page.screenshot({ path: join(outDir, '5-desktop.png') })
    const desktop = await metrics(page)
    // 刷新续档:不能崩、要有内容
    await page.reload({ waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(1500)
    await page.screenshot({ path: join(outDir, '6-reload.png') })
    const reload = await metrics(page)

    const issues = []
    if (errors.length) issues.push(`console error ${errors.length} 条`)
    if (pageErrors.length) issues.push(`pageerror ${pageErrors.length} 条`)
    if (external.length) issues.push(`外部请求 ${external.length} 条`)
    if (home.inlineScripts) issues.push(`内联脚本 ${home.inlineScripts} 个`)
    if (!home.title.trim()) issues.push('页面没有标题')
    if (home.bodyText.length < 10) issues.push('页面几乎是空的')
    if (home.overflowX) issues.push('首屏横向溢出')
    if (FLAGSHIP.has(app) && home.live < 1) issues.push('缺 aria-live 播报')
    if (FLAGSHIP.has(app) && !startClicked) issues.push('找不到可点的开始按钮')
    if (frames < 45) issues.push(`帧率偏低 ${frames}fps`)
    if (reload.bodyText.length < 10) issues.push('刷新后页面为空')
    const result = {
      app, ok: issues.length === 0, issues,
      startClicked, fps: frames, orientation,
      consoleErrors: errors, pageErrors, externalRequests: [...new Set(external)], failedRequests: failed,
      home, action, desktop, reload,
      screenshots: outDir,
    }
    results.push(result)
    writeFileSync(join(outDir, 'report.json'), JSON.stringify(result, null, 2))
    if (result.ok) console.log(`✓ ${app}  ${frames}fps  开始=${startClicked || '—'}  截图=${outDir}`)
    else console.log(`✗ ${app}  ${issues.join(';')}  截图=${outDir}`)
    await page.close()
  } catch (e) {
    results.push({ app, ok: false, issues: [`QA 脚本异常:${e.message}`] })
    console.log(`✗ ${app}  QA 脚本异常:${e.message}`)
  } finally {
    server.kill()
  }
}

await browser.close()
const failedApps = results.filter((r) => !r.ok)
writeFileSync(join(OUT, 'summary.json'), JSON.stringify(results, null, 2))
console.log(`\n${results.length - failedApps.length}/${results.length} 个应用通过;明细 ${OUT}/summary.json`)
if (failedApps.length) process.exit(1)
