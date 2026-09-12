// 小程序的浏览器级检查(DEV-PROMPTS-39 #335 #338):真 Chrome(无头)跑三件事。
//
// 1. 存储型 XSS:开发者在名称、介绍、描述、隐私政策、数据声明、更新说明、给审核员的话里写了脚本和标签,
//    在官网详情页、目录、开发者后台、审核后台各渲染一遍 —— 没有脚本执行、没有标签被当成 HTML;
// 2. CSP:托管页里请求没声明的域名、加载外部脚本、内联脚本、eval、嵌 iframe,全部被浏览器拦下;
//    声明过的域名不拦;违规报告送到了 /mini-apps/csp-report(开发者后台的数据页计数变多);
// 3. 模拟器(#338):开发者后台的模拟器里,记事本用宿主画的主按钮新建一条 → 停笔自动保存 →
//    系统返回键回列表看得到 → 云存储里真有;2048 用方向键打一局,棋盘和分数在变。
//
// 数据由 server/tests/e2e_miniapp_security.py 备好(带 MINIAPP_BROWSER_FIXTURE=… 跑一遍),
// 服务是能直出 /dev/、/admin/ 和官网的那一个(本地开发库上的 API)。模拟器那一段要先打好官方小程序的包
// (bash scripts/build_miniapp.sh notepad、2048)。
//
//   FIXTURE=/tmp/fixture.json OUT=/tmp/shots node scripts/verify_miniapp_browser.mjs
import { mkdirSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'

// puppeteer-core 装在 web/ 下(官网的截图脚本也用它),从那里解析
const require = createRequire(new URL('../web/package.json', import.meta.url))
const puppeteer = require('puppeteer-core')

const fx = JSON.parse(readFileSync(process.env.FIXTURE, 'utf8'))
const API = fx.api.replace(/\/$/, '')
const OUT = process.env.OUT || ''
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
if (OUT) mkdirSync(OUT, { recursive: true })

const problems = []
const ok = (m) => console.log(`✓ ${m}`)
const bad = (m) => { problems.push(m); console.log(`✗ ${m}`) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const shot = async (page, name) => { if (OUT) await page.screenshot({ path: join(OUT, `${name}.png`) }) }

async function api(method, path, body) {
  const r = await fetch(API + path, {
    method, headers: { Authorization: `Bearer ${fx.dev_token}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) throw new Error(`${method} ${path} → ${r.status} ${await r.text()}`)
  return r.json()
}

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--window-size=1440,1000'], defaultViewport: { width: 1440, height: 1000 },
})

async function newPage(tokenKey, token) {
  const page = await browser.newPage()
  page.alerts = []
  page.on('dialog', async (d) => { page.alerts.push(d.message()); await d.dismiss() })
  // 两个后台都从 localStorage 读 token(键名见各自的 api.ts):在页面脚本跑之前放进去
  if (tokenKey) {
    await page.evaluateOnNewDocument((k, t) => {
      localStorage.setItem(k, t)
      localStorage.setItem(`${k}_at`, String(Date.now()))
    }, tokenKey, token)
  }
  return page
}

async function clickText(page, selector, text) {
  const hit = await page.evaluate((sel, t) => {
    // antd 会在两个汉字的按钮里插一个空格(「启 动」),比较前把空白去掉
    const txt = (e) => e.textContent.replace(/\s+/g, '')
    const el = [...document.querySelectorAll(sel)].find((e) => txt(e) === t)
      || [...document.querySelectorAll(sel)].find((e) => txt(e).includes(t))
    if (el) el.click()
    return !!el
  }, selector, text)
  if (!hit) throw new Error(`找不到「${text}」(${selector})`)
}

const waitText = (page, text, timeout = 15000) =>
  page.waitForFunction((t) => document.body && document.body.innerText.includes(t), { timeout }, text)

// ---------------------------------------------------------------- 1. 存储型 XSS

const XSS_NAME_HEAD = '<svg onload=f()>'
const XSS_TEXT_HEAD = '<script>window.__xss=1</script>'

function scan() {
  return {
    xss: window.__xss ?? null,
    svg: document.querySelectorAll('svg[onload]').length,
    img: document.querySelectorAll('img[src="x"]').length,
    b: document.querySelectorAll('b[onclick]').length,
    i: [...document.querySelectorAll('i')].filter((e) => e.textContent === '昵称').length,
    script: [...document.scripts].filter((s) => s.textContent.includes('__xss')).length,
    text: document.body.innerText,
  }
}

async function checkXss(page, label, mustShow) {
  const r = await page.evaluate(scan)
  const { text, ...counts } = r
  const injected = r.xss !== null || r.svg || r.img || r.b || r.i || r.script || page.alerts.length
  if (injected) bad(`${label}:开发者写的标签被当成了 HTML ${JSON.stringify({ ...counts, alerts: page.alerts })}`)
  else if (!mustShow.every((m) => text.includes(m))) bad(`${label}:页面上没看到原样的文字 ${JSON.stringify(mustShow)}`)
  else ok(`${label}:脚本没执行,标签原样显示成文字`)
}

{
  const page = await newPage()
  await page.goto(`${API}/m/${fx.xss_appid}`, { waitUntil: 'networkidle2' })
  await page.waitForSelector('.ma-name')
  await checkXss(page, '官网详情页 /m/<appid>', [XSS_NAME_HEAD, XSS_TEXT_HEAD])
  await shot(page, 'xss-site-detail')
  await page.goto(`${API}/miniapps?q=${encodeURIComponent(XSS_NAME_HEAD)}`, { waitUntil: 'networkidle2' })
  await page.waitForSelector('.ma-row')
  await checkXss(page, '官网目录 /miniapps', [XSS_NAME_HEAD])
  await page.close()
}
{
  const page = await newPage('superz_dev_token', fx.xss_dev_token)
  await page.goto(`${API}/dev/apps/${fx.xss_appid}`, { waitUntil: 'networkidle2' })
  await waitText(page, XSS_NAME_HEAD)
  await checkXss(page, '开发者后台 · 应用概览', [XSS_NAME_HEAD])
  // 展示信息页:描述、隐私政策在输入框里(值是文字,不是 HTML)
  await clickText(page, '.ant-tabs-tab-btn', '展示信息')
  await page.waitForFunction((t) => [...document.querySelectorAll('textarea')].some((x) => x.value.startsWith(t)),
    { timeout: 15000 }, XSS_TEXT_HEAD)
  await checkXss(page, '开发者后台 · 展示信息(描述、隐私政策)', [XSS_NAME_HEAD])
  await shot(page, 'xss-dev-listing')
  await page.close()
}
{
  const page = await newPage('superz_admin_token', fx.admin_token)
  await page.goto(`${API}/admin/mini-apps`, { waitUntil: 'networkidle2' })
  await waitText(page, XSS_NAME_HEAD)
  const opened = await page.evaluate((name) => {
    const row = [...document.querySelectorAll('tr')].find((tr) => tr.innerText.includes(name))
    const link = row && [...row.querySelectorAll('a')].find((a) => a.textContent.trim() === '审核')
    if (link) link.click()
    return !!link
  }, XSS_NAME_HEAD)
  if (!opened) bad('审核后台:待审队列里找不到那条版本')
  else {
    await page.waitForSelector('.ant-drawer-body')
    await waitText(page, XSS_TEXT_HEAD)
    await checkXss(page, '审核后台 · 审核抽屉(更新说明、给审核员的话、描述、隐私政策)', [XSS_NAME_HEAD, XSS_TEXT_HEAD])
    await shot(page, 'xss-admin-drawer')
  }
  await page.close()
}

// ---------------------------------------------------------------- 2. CSP

async function cspCount() {
  const s = await api('GET', `/dev/v1/apps/${fx.probe_appid}/stats`)
  return Object.values(s.csp_blocked || {}).reduce((a, b) => a + b, 0)
}

{
  const before = await cspCount()
  const page = await newPage()
  await page.goto(`${API}${fx.probe_path}`, { waitUntil: 'load' })
  await sleep(2500)
  const p = await page.evaluate(() => ({ ...window.__probe, inline: window.__inline ?? null }))
  const has = (dir, what) => p.violations.some((v) => v.startsWith(dir) && v.includes(what))
  const expect = [
    ['connect-src', 'undeclared.example.org', '请求没声明的域名'],
    ['script-src-elem', 'evil.example.org', '加载外部脚本'],
    ['script-src-elem', 'inline', '内联脚本'],
    ['script-src', 'eval', 'eval'],
    ['frame-src', 'example.org', '嵌 iframe'],
  ]
  for (const [dir, what, label] of expect) {
    if (has(dir, what)) ok(`CSP 拦下了${label}(${dir})`)
    else bad(`CSP 没拦下${label}:违规记录 ${JSON.stringify(p.violations)}`)
  }
  if (p.inline !== null || p.evalAllowed !== false) bad(`内联脚本或 eval 居然跑了:${JSON.stringify(p)}`)
  if (p.violations.some((v) => v.includes('api.example.com'))) bad('声明过的 api.example.com 也被拦了')
  else ok('声明过的服务器域名不拦')
  let after = before
  for (let i = 0; i < 10 && after <= before; i++) { await sleep(500); after = await cspCount() }
  if (after > before) ok(`违规报告送到了平台:开发者后台的 CSP 拦截计数 ${before} → ${after}`)
  else bad(`违规报告没到平台(计数一直是 ${before})`)
  await page.close()
}

// ---------------------------------------------------------------- 3. 模拟器(#338)

async function simulator(appid, label, run) {
  const page = await newPage('superz_dev_token', fx.dev_token)
  await page.goto(`${API}/dev/apps/${appid}`, { waitUntil: 'networkidle2' })
  await clickText(page, '.ant-tabs-tab-btn', '模拟器')
  await clickText(page, 'button', '启动')
  const frame = await (await page.waitForSelector('iframe[title="模拟器"]')).contentFrame()
  await page.waitForFunction(() => ![...document.querySelectorAll('.ant-tag')]
    .some((t) => t.textContent.includes('等 ready')), { timeout: 20000 })
  try {
    await run(page, frame)
    // 模拟器对每次加载的页面发 ping,官方小程序都引了 SDK,不该有「没回应 ping」的红字
    if (await page.evaluate(() => document.body.innerText.includes('没回应 ping'))) {
      throw new Error('桥调用日志里有「没回应 ping」—— 页面里的 SDK 太旧,或者宿主误判')
    }
  } catch (e) {
    bad(`${label}:${e.message}`)
    await shot(page, `${label}-失败`)
  }
  await page.close()
}

if (fx.notepad_appid) {
  await simulator(fx.notepad_appid, '模拟器 · 记事本', async (page, frame) => {
    // 「新建笔记」是宿主画的主按钮(模拟器的设备框里),不在页面里
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some((b) => b.textContent.includes('新建笔记')))
    await clickText(page, 'button', '新建笔记')
    const ta = await frame.waitForSelector('textarea')
    const title = `浏览器检查 ${Date.now() % 100000}`
    await ta.type(`${title}\n第二行内容`)
    await sleep(2000) // 停笔 0.8 秒自动保存,再留出一次往返
    await shot(page, 'sim-notepad-edit')
    await clickText(page, 'button', '模拟系统返回键')
    await frame.waitForFunction((t) => document.body.innerText.includes(t), { timeout: 10000 }, title)
    const { keys } = await api('POST', `/dev/v1/apps/${fx.notepad_appid}/sim/storage/keys`, {})
    const { items } = await api('POST', `/dev/v1/apps/${fx.notepad_appid}/sim/storage/get`, { keys })
    const saved = Object.values(items).some((x) => x && String(x.value).includes(title))
    if (!saved) throw new Error(`云存储里没有这条笔记:${JSON.stringify(keys)}`)
    await shot(page, 'sim-notepad-list')
    ok('模拟器 · 记事本:主按钮新建 → 自动保存 → 返回键回列表看得到 → 云存储里有')
  })
} else console.log('- 模拟器 · 记事本:没有打好的包,跳过')

if (fx.game_appid) {
  await simulator(fx.game_appid, '模拟器 · 2048', async (page, frame) => {
    await frame.waitForSelector('#board .tiles .tile')
    const snap = () => frame.evaluate(() => ({
      score: Number(document.querySelector('#score').textContent || 0),
      tiles: [...document.querySelectorAll('#board .tiles .tile')].map((t) => `${t.textContent}@${t.style.transform}`).sort().join('|'),
    }))
    const s0 = await snap()
    await frame.focus('#board')
    let changes = 0
    let last = s0
    for (let i = 0; i < 48; i++) {
      await page.keyboard.press(['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'][i % 4])
      await sleep(140)
      const s = await snap()
      if (s.tiles !== last.tiles) changes++
      last = s
    }
    if (changes < 5) throw new Error(`方向键按了 48 下,棋盘只变了 ${changes} 次`)
    if (last.score <= s0.score) throw new Error(`分数没涨:${s0.score} → ${last.score}`)
    // 存档:停手 0.5 秒写云存储(模拟器用开发者自己的命名空间)
    await sleep(1500)
    await shot(page, 'sim-2048')
    const { items } = await api('POST', `/dev/v1/apps/${fx.game_appid}/sim/storage/get`, { keys: ['state', 'best'] })
    const saved = items.state && JSON.parse(items.state.value)
    if (!saved || saved.score !== last.score) throw new Error(`云存储里的存档对不上:${items.state?.value?.slice(0, 120)}`)
    ok(`模拟器 · 2048:方向键 48 下,棋盘变了 ${changes} 次,分数 ${s0.score} → ${last.score},存档写进了云存储`)
  })
} else console.log('- 模拟器 · 2048:没有打好的包,跳过')

await browser.close()
if (problems.length) {
  console.error(`\n✗ ${problems.length} 项没过`)
  process.exit(1)
}
console.log('\n✓ 浏览器级检查全部通过')
