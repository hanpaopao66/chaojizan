import puppeteer from 'puppeteer-core'
const b = await puppeteer.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: 'new', defaultViewport: { width: 1600, height: 900 } })
const p = await b.newPage()
await p.goto('http://localhost:5173/site/screen', { waitUntil: 'domcontentloaded' })
await p.waitForSelector('.sc-col')
await new Promise(r => setTimeout(r, 1500))
console.log(await p.evaluate(() => {
  const [l, r] = [...document.querySelectorAll('.sc-col')].map(c => c.getBoundingClientRect())
  const ce = document.querySelector('.sc-center').getBoundingClientRect()
  const rt = document.querySelector('.screen-root').getBoundingClientRect()
  const zoomTip = getComputedStyle(document.querySelector('.sc-rotate-tip')).display
  return JSON.stringify({ leftW: +l.width.toFixed(1), rightW: +r.width.toFixed(1), gapL: +(ce.left - l.right).toFixed(1), gapR: +(r.left - ce.right).toFixed(1), edgeL: +(l.left - rt.left).toFixed(1), edgeR: +(rt.right - r.right).toFixed(1), rotateTipHidden: zoomTip === 'none' })
}))
await b.close()
