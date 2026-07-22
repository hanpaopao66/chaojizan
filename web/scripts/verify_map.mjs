// 大屏地图交互验证:真 Chrome(无头)+ 真实输入管线
import puppeteer from 'puppeteer-core'

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new',
  args: ['--window-size=1600,900', '--use-gl=angle'],
  defaultViewport: { width: 1600, height: 900 },
})
const page = await browser.newPage()
const logs = []
page.on('console', m => logs.push(m.text()))
await page.goto('http://localhost:5173/site/screen', { waitUntil: 'domcontentloaded', timeout: 30000 })
await page.waitForSelector('.sc-map-wrap canvas', { timeout: 15000 })
await new Promise(r => setTimeout(r, 2500))   // 等 geo 加载 + 首帧

const rect = await page.$eval('.sc-map-wrap canvas', el => {
  const r = el.getBoundingClientRect()
  return { w: r.width, h: r.height, x: r.left, y: r.top }
})
console.log('CANVAS_RECT', JSON.stringify(rect))

// 1) 悬停省份中部(地图中心偏东南=河南/湖北一带)
const hx = rect.x + rect.w * 0.55, hy = rect.y + rect.h * 0.52
await page.mouse.move(hx, hy, { steps: 8 })
await new Promise(r => setTimeout(r, 600))
const tip1 = await page.$eval('.sc-map-tip', el => el.textContent).catch(() => null)
console.log('HOVER_TIP', JSON.stringify(tip1))

// 2) 拖拽:按下左键横向拖 → 视角应旋转(截图对比留证)
await page.screenshot({ path: process.env.OUT + '/map_before_drag.png', clip: { x: rect.x, y: rect.y, width: rect.w, height: rect.h } })
await page.mouse.move(hx, hy)
await page.mouse.down()
await page.mouse.move(hx + 220, hy - 60, { steps: 12 })
await page.mouse.up()
await new Promise(r => setTimeout(r, 400))
await page.screenshot({ path: process.env.OUT + '/map_after_drag.png', clip: { x: rect.x, y: rect.y, width: rect.w, height: rect.h } })

// 3) 滚轮缩放
await page.mouse.wheel({ deltaY: -400 })
await new Promise(r => setTimeout(r, 400))
await page.screenshot({ path: process.env.OUT + '/map_after_zoom.png', clip: { x: rect.x, y: rect.y, width: rect.w, height: rect.h } })

// 4) 空品类省份悬停(新疆西部)
await page.mouse.move(rect.x + rect.w * 0.17, rect.y + rect.h * 0.30, { steps: 6 })
await new Promise(r => setTimeout(r, 600))
const tip2 = await page.$eval('.sc-map-tip', el => el.textContent).catch(() => null)
console.log('HOVER_TIP_EMPTY_PROVINCE', JSON.stringify(tip2))

console.log('MAP_HOVER_LOGS', logs.filter(l => l.includes('map-hover')).slice(0, 3))
await browser.close()
