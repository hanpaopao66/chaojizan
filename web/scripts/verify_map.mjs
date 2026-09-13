// 大屏地图验证:真 Chrome(无头)+ 真实输入管线,接口用拦截喂固定数据(不依赖本地库里有什么)。
//
//   cd web && npm run dev                                  # 另开一个终端
//   node scripts/verify_map.mjs                            # 默认 http://localhost:5173/site/screen
//   SCREEN_URL=http://127.0.0.1:5191/site/screen OUT=/tmp node scripts/verify_map.mjs
//
// 查这几件事,任何一条不过退出码就是 1:
//  1. 投影:china.json 里 34 个省的标注点(经纬度)用 src/screen/geo.js 的投影算一遍,
//     和 films/chinaGeo.js 里生成好的 cp 逐个比 —— 城市点和省界是不是同一个坐标系;
//  2. 省界:34 个省级行政区一个不少(上海、澳门、香港、台湾、海南点名查),
//     南海诸岛附图在,岛礁点在,南海断续线附图十段、主图该画的几段都在;
//  3. 城市点:有坐标的城市画点,没坐标的(只有跑腿单的城市)不画;
//  4. 悬停:陕西浮层列出 TOP10 里的西安,新疆浮层说 TOP10 里没有;
//  5. 新单涟漪:第二轮轮询多出来的单,在它的城市泛一圈;跑腿单没坐标,按城市名落到那座城;
//  6. 减少动态效果:不泛涟漪、播报不滚、呼吸点不动;
//  7. 接口没取到:角标挂「接口未连」,数字是「–」不是 0;
//  8. 页面没有报错(接口故意回 502 的那一页除外)。
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import puppeteer from 'puppeteer-core'

import chinaGeo from '../src/films/chinaGeo.js'
import { project } from '../src/screen/geo.js'

const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const URL_ = process.env.SCREEN_URL || 'http://localhost:5173/site/screen'
const OUT = process.env.OUT
const fails = []
const check = (ok, msg) => { console.log(`${ok ? '✓' : '✗'} ${msg}`); if (!ok) fails.push(msg) }

// ---------- 1. 投影 ----------
const src = JSON.parse(readFileSync(fileURLToPath(new URL('../public/geo/china.json', import.meta.url))))
let worst = 0
for (const f of src.features) {
  const g = chinaGeo.provinces.find(p => p.n === f.properties.name)
  if (!g) continue
  const [x, y] = project(...f.properties.cp)
  worst = Math.max(worst, Math.abs(x - g.cp[0]), Math.abs(y - g.cp[1]))
}
check(worst < 0.3, `投影:34 个省的标注点和省界数据对得上(最大偏差 ${worst.toFixed(2)} 画幅单位)`)

// ---------- 固定数据 ----------
const ago = s => new Date(Date.now() - s * 1000).toISOString()
const stats = {
  registrations: { users: { total: 12846, today: 128 }, merchants: { total: 1204, today: 9 },
    riders: { total: 3470, today: 41 }, drivers: { total: 0, today: 0, coming: true } },
  orders: { total: 48219, gmv_cents: 1, today: 168, today_gmv_cents: 493200 },
  trend: Array.from({ length: 7 }, (_, i) => ({ day: `09-0${i + 1}`, orders: 90 + i * 10, gmv_cents: 0 })),
  hourly: { today: Array(24).fill(3), yesterday: Array(24).fill(2) },
  cities: [
    { city: '西安市', orders: 18426, gmv_cents: 0, lat: 34.34, lng: 108.94 },
    { city: '成都市', orders: 6820, gmv_cents: 0, lat: 30.66, lng: 104.08 },
    { city: '铜川市', orders: 120, gmv_cents: 0, lat: null, lng: null },   // 只有跑腿单:没坐标
  ],
  status_dist: ['paid', 'accepted', 'ready', 'picked_up', 'delivered', 'completed']
    .map((status, i) => ({ status, label: status, count: i + 1 })),
  delivery: { riders_online: 36, avg_minutes: 27.6, duration_buckets: [22, 61, 54, 31], ready_late_ratio: 0.034 },
  coverage: { cities: 3, merchants: 1204 },
  merchant_savings: { saved_cents: 72400000, industry_rate: 0.2 },
  eco: { no_tableware_orders: 54 },
  stays: { today_orders: 14, today_roomnights: 19, inhouse_rooms: 11 },
  vouchers: { today_redeemed: 37 },
  errands: { today_orders: 22 },
  show_gmv: true, demo: false,
}
const order = (id, extra) => ({ id, order_no_tail: String(id).padStart(6, '0'), status: 'paid',
  status_label: '待接单', amount_cents: 2600, created_at: ago(30), merchant: '张记面馆', city: '西安市',
  lat: 34.34, lng: 108.94, phone: '138****6421', ...extra })
const FIRST = [order(10), order(9, { city: '成都市', lat: 30.66, lng: 104.08 })]
const SECOND = [
  order(12, { created_at: ago(1) }),                                              // 新单,西安
  order(11, { merchant: '帮我送', lat: null, lng: null, city: '成都市', created_at: ago(2) }), // 新跑腿单,按城市名落
  ...FIRST,
]
const fairness = { commission: { real_rate_30d: 0.0472, promised_cap: 0.05, tiers: [] },
  per100: { merchant: 81.1, rider: 14.2, commission: 4.7, subsidy: 0 }, window_days: 30 }

async function open(browser, { reduced = false, down = false } = {}) {
  const page = await browser.newPage()
  if (reduced) await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }])
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  let polls = 0
  await page.setRequestInterception(true)
  page.on('request', req => {
    const u = req.url()
    const json = body => req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    const api = /\/screen\/(stats|orders\/latest)|\/transparency\/fairness/.test(u)   // 页面自己的模块路径里也有 /screen/
    if (down && api) return req.respond({ status: 502, body: 'bad gateway' })
    if (u.includes('/screen/stats')) return json(stats)
    if (u.includes('/screen/orders/latest')) return json({ items: polls++ ? SECOND : FIRST, show_gmv: true, demo: false })
    if (u.includes('/transparency/fairness')) return json(fairness)
    return req.continue()
  })
  await page.goto(URL_, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('.sc-provinces path', { timeout: 15000 })
  if (!down) await page.waitForSelector('.sc-dots circle', { timeout: 15000 })
  return { page, errors }
}

/* 画幅坐标 → 视口像素(整屏有 transform 缩放,走 SVG 自己的屏幕矩阵) */
const toScreen = (page, x, y) => page.$eval('.sc-map svg', (svg, x, y) => {
  const p = new DOMPoint(x, y).matrixTransform(svg.getScreenCTM())
  return [p.x, p.y]
}, x, y)

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new',
  args: ['--window-size=1920,1080', '--no-proxy-server'],
  defaultViewport: { width: 1920, height: 1080 },
})
try {
  const { page, errors } = await open(browser)

  // ---------- 2. 省界 ----------
  const names = await page.$$eval('.sc-provinces path', ps => ps.map(p => p.getAttribute('data-name')))
  check(names.length === 34, `省界:${names.length} 个省级行政区`)
  for (const must of ['上海市', '澳门特别行政区', '香港特别行政区', '台湾省', '海南省']) {
    check(names.includes(must), `省界里有 ${must}`)
  }
  const islands = await page.$$eval('.sc-inset circle', cs => cs.length)
  const insetText = await page.$eval('.sc-inset text', t => t.textContent).catch(() => '')
  check(islands > 100 && insetText === '南海诸岛', `南海诸岛附图:${islands} 个岛礁点,标注「${insetText}」`)
  const insetDash = await page.$$eval('.sc-inset path.dash', ps => ps.length)
  const mainDash = await page.$$eval('.sc-dashline path', ps => ps.length)
  check(insetDash === 10 && mainDash === chinaGeo.dashMain.length && mainDash > 0,
    `南海断续线:附图 ${insetDash} 段(应 10),主图 ${mainDash} 段(应 ${chinaGeo.dashMain.length})`)

  // ---------- 3. 城市点 ----------
  const dots = await page.$$eval('.sc-dots circle', cs => cs.map(c => [+c.getAttribute('cx'), +c.getAttribute('cy')]))
  const [xx, xy] = project(108.94, 34.34)
  check(dots.length === 2, `城市点:有坐标的 2 座城画点,没坐标的不画(实际 ${dots.length} 个)`)
  check(dots.some(([x, y]) => Math.abs(x - xx) < 0.5 && Math.abs(y - xy) < 0.5), '西安的点落在西安的经纬度上')
  const label = await page.$eval('.sc-city-name', t => t.textContent).catch(() => null)
  check(label === '西安', `只标第一名:「${label}」`)

  // ---------- 4. 悬停 ----------
  const cp = n => chinaGeo.provinces.find(p => p.n === n).cp
  const [sx, sy] = await toScreen(page, ...cp('陕西省'))
  await page.mouse.move(sx, sy, { steps: 6 })
  await new Promise(r => setTimeout(r, 300))
  const tip1 = await page.$eval('.sc-map-tip', el => el.textContent).catch(() => '')
  check(tip1.includes('陕西省') && tip1.includes('西安') && tip1.includes('18,426'), `悬停陕西:「${tip1}」`)
  if (OUT) await page.screenshot({ path: `${OUT}/map_hover.png` })
  const [jx, jy] = await toScreen(page, ...cp('新疆维吾尔自治区'))
  await page.mouse.move(jx, jy, { steps: 6 })
  await new Promise(r => setTimeout(r, 300))
  const tip2 = await page.$eval('.sc-map-tip', el => el.textContent).catch(() => '')
  check(tip2.includes('新疆') && tip2.includes('TOP10 里暂无'), `悬停新疆:「${tip2}」`)
  await page.mouse.move(5, 5)

  // ---------- 5. 新单涟漪 ----------
  await page.waitForSelector('.sc-ripple', { timeout: 12000 }).catch(() => null)
  const rings = await page.$$eval('.sc-ripple', cs => cs.map(c => [+c.getAttribute('cx'), +c.getAttribute('cy')]))
  const [cx, cy] = project(104.08, 30.66)
  check(rings.some(([x, y]) => Math.abs(x - xx) < 0.5 && Math.abs(y - xy) < 0.5), '新单在西安泛了一圈')
  check(rings.some(([x, y]) => Math.abs(x - cx) < 0.5 && Math.abs(y - cy) < 0.5),
    '跑腿单没坐标,按城市名落到成都的点上')
  const fresh = await page.$$eval('.sc-ticker .item.fresh', els => els.length)
  check(fresh >= 2, `播报里两条新单在闪(${fresh} 个节点带 fresh)`)
  await new Promise(r => setTimeout(r, 700))   // 圈扩开一点再截,刚出来那一下只有点那么大
  if (OUT) await page.screenshot({ path: `${OUT}/map_ripple.png` })
  await new Promise(r => setTimeout(r, 3500))
  const left = await page.$$eval('.sc-ripple', cs => cs.length)
  check(left === 0, `涟漪播完就摘掉(剩 ${left} 个)`)
  check(errors.length === 0, `页面没有报错${errors.length ? ':' + errors.slice(0, 3).join(' | ') : ''}`)
  await page.close()

  // ---------- 6. 减少动态效果 ----------
  const r = await open(browser, { reduced: true })
  await new Promise(res => setTimeout(res, 6500))   // 等过第二轮轮询
  const rr = await r.page.$$eval('.sc-ripple', cs => cs.length)
  const still = await r.page.$eval('.sc-ticker .track', el => el.classList.contains('still')
    && getComputedStyle(el).animationName === 'none').catch(() => false)
  const breath = await r.page.$eval('.sc-dot', el => getComputedStyle(el).animationName)
  check(rr === 0 && still && breath === 'none',
    `减少动态效果:涟漪 ${rr} 个、播报${still ? '不滚' : '在滚'}、呼吸点动画 ${breath}`)
  check(r.errors.length === 0, '减少动态效果下页面没有报错')
  await r.page.close()

  // ---------- 7. 接口没取到 ----------
  const d = await open(browser, { down: true })
  await d.page.waitForSelector('.sc-pill.warn', { timeout: 8000 }).catch(() => null)
  const pill = await d.page.$eval('.sc-pill.warn', el => el.textContent).catch(() => '')
  const hero = await d.page.$eval('.sc-hero .n', el => el.textContent)
  check(pill.includes('接口未连') && hero === '–', `接口没取到:角标「${pill}」,累计订单显示「${hero}」`)
} finally {
  await browser.close()
}

console.log(fails.length ? `\n✗ ${fails.length} 项没过` : '\n✓ 全部通过')
process.exit(fails.length ? 1 : 0)
