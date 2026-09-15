// 方块消除的界面:canvas 画棋盘和「下一个」,requestAnimationFrame 每一帧把过去的时间交给引擎。
// 规则全在 engine.ts;这里只管输入(按住连发的屏幕按键、键盘、棋盘上的手势)、画、暂停、存档和宿主能力。
import '../../shared/src/base.css'
import './style.css'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import {
  $, Overlay, WebApp, bullets, button, cacheKey, cloud, confirmBox, el, followTheme, hostGame, local, reduced, row,
} from '../../shared/src/ui'
import {
  Best, COLS, EMPTY_BEST, ROWS, Result, SHAPES, State, cellsOf, dropY, hardDrop, load, loadBest, mergeBest, move,
  newGame, rotate, save, softDrop, tick, updateBest,
} from './engine'
import { DARK, LIGHT, Palette } from './palette'

type Mode = 'ready' | 'running' | 'paused' | 'over'
type Act = 'left' | 'right' | 'down' | 'rotate' | 'ccw' | 'drop'

const play = $('play')
const frame = document.querySelector('.frame') as HTMLElement
const side = document.querySelector('.side') as HTMLElement
const canvas = $<HTMLCanvasElement>('board')
const ctx = canvas.getContext('2d') as CanvasRenderingContext2D
const nextCanvas = $<HTMLCanvasElement>('next')
const nctx = nextCanvas.getContext('2d') as CanvasRenderingContext2D
const veil = $('veil')
const veilText = $('veil-text')
const scoreEl = $('score')
const linesEl = $('lines')
const levelEl = $('level')
const bestEl = $('best')
const pauseBtn = $<HTMLButtonElement>('pause')
const live = $('live')
const overlay = new Overlay($('overlay'), () => canvas.focus())

const slot = new SaveSlot<State, Best>({
  cacheKey: cacheKey('blocks'), cloud, local, loadState: load, saveState: save, loadBest, mergeBest,
  emptyBest: EMPTY_BEST,
  // 每固定一块记一次;云端最多 5 秒写一次(暂停、结束、切走时立刻写)
  delay: 1000, minGap: 5000,
})

let state: State = newGame(freshSeed())
let best: Best = EMPTY_BEST
let mode: Mode = 'ready'
let pal: Palette = LIGHT
let cell = 20
let nextCell = 12
/** 刚消掉的行闪一下(这期间不走、不收输入) */
let flash: { rows: number[]; board: number[]; until: number } | null = null

const started = (s: State) => s.score > 0 || s.lines > 0 || s.cells.some((v) => v)

// ---------------------------------------------------------------- 画

function size(c: HTMLCanvasElement, g: CanvasRenderingContext2D, w: number, h: number): void {
  const dpr = Math.min(3, window.devicePixelRatio || 1)
  c.style.width = `${w}px`
  c.style.height = `${h}px`
  c.width = Math.round(w * dpr)
  c.height = Math.round(h * dpr)
  g.setTransform(dpr, 0, 0, dpr, 0, 0)
}

function layout(): void {
  const w = play.clientWidth - side.offsetWidth - 10
  const h = play.clientHeight
  if (w <= 0 || h <= 0) return
  cell = Math.max(8, Math.floor(Math.min(w / COLS, h / ROWS)))
  size(canvas, ctx, cell * COLS, cell * ROWS)
  nextCell = Math.max(8, Math.min(16, Math.floor((side.clientWidth - 16) / 4)))
  size(nextCanvas, nctx, nextCell * 4, nextCell * 2)
  draw()
}

/** 圆角方块(不用 ctx.roundRect:老 WebView 没有) */
function tile(g: CanvasRenderingContext2D, x: number, y: number, s: number, color: string): void {
  const r = Math.min(4, s * 0.18)
  const a = x + 1
  const b = y + 1
  const w = s - 2
  g.fillStyle = color
  g.beginPath()
  g.moveTo(a + r, b)
  g.arcTo(a + w, b, a + w, b + w, r)
  g.arcTo(a + w, b + w, a, b + w, r)
  g.arcTo(a, b + w, a, b, r)
  g.arcTo(a, b, a + w, b, r)
  g.closePath()
  g.fill()
}

function draw(): void {
  const W = COLS * cell
  const H = ROWS * cell
  ctx.fillStyle = pal.board
  ctx.fillRect(0, 0, W, H)
  ctx.fillStyle = pal.grid
  for (let x = 1; x < COLS; x++) ctx.fillRect(x * cell, 0, 1, H)
  for (let y = 1; y < ROWS; y++) ctx.fillRect(0, y * cell, W, 1)
  const cells = flash ? flash.board : state.cells
  for (let y = 0; y < ROWS; y++) {
    for (let x = 0; x < COLS; x++) {
      const v = cells[y * COLS + x]
      if (v) tile(ctx, x * cell, y * cell, cell, pal.pieces[v - 1])
    }
  }
  if (flash) {
    ctx.globalAlpha = 0.75
    ctx.fillStyle = pal.flash
    for (const y of flash.rows) ctx.fillRect(0, y * cell, W, cell)
    ctx.globalAlpha = 1
  } else if (state.piece) {
    const p = state.piece
    const color = pal.pieces[p.k]
    // 落点提示:方块占的那几列,从方块底下到落点铺一条淡淡的带子
    const land = dropY(state.cells, p) - p.y
    if (land > 0) {
      ctx.globalAlpha = 0.1
      ctx.fillStyle = color
      const cols = new Map<number, number>()
      for (const [x, y] of cellsOf(p)) cols.set(x, Math.max(cols.get(x) ?? -99, y))
      cols.forEach((bottom, x) => {
        const from = Math.max(0, bottom + 1)
        const to = bottom + land
        if (to >= from) ctx.fillRect(x * cell + 1, from * cell, cell - 2, (to - from + 1) * cell)
      })
      ctx.globalAlpha = 1
    }
    for (const [x, y] of cellsOf(p)) if (y >= 0) tile(ctx, x * cell, y * cell, cell, color)
  }
  drawNext()
}

function drawNext(): void {
  const n = nextCell
  nctx.clearRect(0, 0, n * 4, n * 2)
  const shape = SHAPES[state.next][0]
  const xs = shape.map(([x]) => x)
  const ys = shape.map(([, y]) => y)
  const w = Math.max(...xs) - Math.min(...xs) + 1
  const h = Math.max(...ys) - Math.min(...ys) + 1
  const ox = (4 - w) / 2 - Math.min(...xs)
  const oy = (2 - h) / 2 - Math.min(...ys)
  for (const [x, y] of shape) tile(nctx, (x + ox) * n, (y + oy) * n, n, pal.pieces[state.next])
}

function drawStats(bump = false): void {
  scoreEl.textContent = String(state.score)
  linesEl.textContent = String(state.lines)
  levelEl.textContent = String(state.level)
  bestEl.textContent = String(Math.max(best.score, state.score))
  if (bump && !reduced()) {
    const box = scoreEl.parentElement as HTMLElement
    box.classList.remove('bump')
    void box.offsetWidth
    box.classList.add('bump')
  }
}

function syncUi(): void {
  pauseBtn.textContent = { ready: '开始', running: '暂停', paused: '继续', over: '暂停' }[mode]
  pauseBtn.disabled = mode === 'over'
  const tips: Partial<Record<Mode, string[]>> = {
    ready: ['点一下开始', '左右划挪动,点一下旋转', '往下一甩直接落底'],
    paused: ['已暂停', '点一下棋盘或按任意键继续'],
  }
  const tip = tips[mode]
  veil.hidden = !tip
  if (tip) {
    veilText.textContent = tip[0]
    for (const line of tip.slice(1)) veilText.append(el('small', line))
  }
  // 玩着的时候显示宿主返回键:安卓的返回手势先暂停,不会一划就把这一局关掉
  if (mode === 'running') WebApp.BackButton.show()
  else WebApp.BackButton.hide()
  canvas.setAttribute('aria-label', `方块消除棋盘,${state.score} 分,消了 ${state.lines} 行,第 ${state.level} 级,${
    { ready: '还没开始', running: '进行中', paused: '已暂停', over: '已结束' }[mode]}`)
}

// ---------------------------------------------------------------- 走

let raf = 0
let lastT = 0

function loop(t: number): void {
  raf = 0
  if (mode !== 'running') return
  const dt = lastT ? Math.min(t - lastT, 250) : 0
  lastT = t
  if (flash) {
    if (t >= flash.until) {
      flash = null
      draw()
    }
  } else {
    const r = tick(state, dt)
    const y = state.piece?.y
    if (r.locked) handle(r)
    else {
      state = r.state
      if (state.piece?.y !== y) draw()
    }
  }
  if (mode === 'running') raf = requestAnimationFrame(loop)
}

function startLoop(): void {
  if (raf) return
  lastT = 0
  raf = requestAnimationFrame(loop)
}

/** 固定了一块之后:存档、消行的反馈、结束 */
function handle(r: Result): void {
  state = r.state
  if (r.locked) {
    slot.change(state)
    if (r.cleared.length) {
      WebApp.HapticFeedback.impactOccurred(r.cleared.length >= 4 ? 'heavy' : 'medium')
      live.textContent = `消了 ${r.cleared.length} 行,得 ${r.gained} 分`
      if (r.board && !reduced()) flash = { rows: r.cleared, board: r.board, until: performance.now() + 200 }
    }
    if (state.over) finish()
  }
  draw()
  drawStats(r.cleared.length > 0)
}

function finish(): void {
  mode = 'over'
  releaseAll()
  best = updateBest(best, state, true)
  slot.setBest(best)
  void slot.flush()
  syncUi()
  WebApp.HapticFeedback.notificationOccurred('warning')
  live.textContent = `到顶了,${state.score} 分,消了 ${state.lines} 行`
  setTimeout(() => {
    flash = null
    draw()
    showOver()
  }, reduced() ? 0 : 500)
}

// ---------------------------------------------------------------- 操作

/** 做一个动作;还没开始或暂停中,任何动作都只是「继续」。返回有没有动 */
function act(a: Act): boolean {
  if (overlay.open || mode === 'over') return false
  if (mode !== 'running') {
    resume()
    return false
  }
  if (flash) return false
  if (a === 'drop') {
    WebApp.HapticFeedback.impactOccurred('light')
    handle(hardDrop(state))
    return true
  }
  const next = a === 'left' ? move(state, -1) : a === 'right' ? move(state, 1) : a === 'down' ? softDrop(state)
    : rotate(state, a === 'rotate' ? 1 : -1)
  if (next === state) return false
  state = next
  draw()
  if (a === 'down') drawStats()
  return true
}

function pause(): void {
  if (mode !== 'running') return
  mode = 'paused'
  releaseAll()
  slot.change(state)
  void slot.flush()
  syncUi()
}

function resume(): void {
  if ((mode !== 'paused' && mode !== 'ready') || overlay.open) return
  mode = 'running'
  syncUi()
  startLoop()
}

function togglePause(): void {
  if (mode === 'running') pause()
  else resume()
}

function restart(): void {
  overlay.hide()
  if (started(state) && !state.over) {
    best = updateBest(best, state, true)
    slot.setBest(best)
  }
  state = newGame(freshSeed())
  mode = 'ready'
  flash = null
  slot.change(state)
  void slot.flush()
  syncUi()
  draw()
  drawStats()
  canvas.focus()
}

async function askRestart(): Promise<void> {
  if (!state.over && started(state)) {
    pause()
    if (!(await confirmBox('放弃这一局,重新开始?'))) return
  }
  restart()
}

// ---------------------------------------------------------------- 按住连发

/** [首次延迟, 之后每隔多久] 毫秒 */
const REPEAT: Partial<Record<Act, [number, number]>> = { left: [170, 50], right: [170, 50], down: [60, 40] }
const held = new Map<string, { a: Act; timeout: number; interval: number }>()

function press(id: string, a: Act): void {
  release(id)
  // 左右同时按住:后按的那个说了算
  if (a === 'left' || a === 'right') {
    held.forEach((h, other) => { if (h.a === (a === 'left' ? 'right' : 'left')) release(other) })
  }
  act(a)
  const rep = REPEAT[a]
  if (!rep) return
  const h = { a, timeout: 0, interval: 0 }
  h.timeout = window.setTimeout(() => {
    h.interval = window.setInterval(() => { if (mode === 'running') act(a) }, rep[1])
  }, rep[0])
  held.set(id, h)
}

function release(id: string): void {
  const h = held.get(id)
  if (!h) return
  clearTimeout(h.timeout)
  clearInterval(h.interval)
  held.delete(id)
}

function releaseAll(): void {
  for (const id of Array.from(held.keys())) release(id)
}

// ---------------------------------------------------------------- 输入

const KEYS: Record<string, Act> = {
  ArrowLeft: 'left', Left: 'left', a: 'left', A: 'left',
  ArrowRight: 'right', Right: 'right', d: 'right', D: 'right',
  ArrowDown: 'down', Down: 'down', s: 'down', S: 'down',
  ArrowUp: 'rotate', Up: 'rotate', w: 'rotate', W: 'rotate', x: 'rotate', X: 'rotate',
  z: 'ccw', Z: 'ccw', ' ': 'drop',
}
window.addEventListener('keydown', (e) => {
  if (overlay.open || e.metaKey || e.ctrlKey || e.altKey) return
  if (e.key === 'p' || e.key === 'P' || e.key === 'Escape') {
    e.preventDefault()
    togglePause()
    return
  }
  const a = KEYS[e.key]
  if (!a) return
  // 焦点在按钮上时空格是按那个按钮,不抢
  if (e.key === ' ' && (e.target as HTMLElement).tagName === 'BUTTON') return
  e.preventDefault()
  if (e.repeat) return // 连发自己管(系统的按键重复太慢,首次要等半秒)
  press(`k:${e.key.toLowerCase()}`, a)
})
window.addEventListener('keyup', (e) => release(`k:${e.key.toLowerCase()}`))
window.addEventListener('blur', releaseAll)

// 屏幕按键:按下就动,按住连发;键盘或读屏触发的 click(detail 为 0)也认
document.querySelectorAll<HTMLButtonElement>('.key').forEach((b) => {
  const a = b.dataset.act as Act
  b.addEventListener('pointerdown', (e) => {
    e.preventDefault()
    b.classList.add('hit')
    b.setPointerCapture?.(e.pointerId)
    press(`p:${e.pointerId}`, a)
  })
  const up = (e: PointerEvent) => {
    b.classList.remove('hit')
    release(`p:${e.pointerId}`)
  }
  b.addEventListener('pointerup', up)
  b.addEventListener('pointercancel', up)
  b.addEventListener('lostpointercapture', up)
  b.addEventListener('click', (e) => { if (e.detail === 0) act(a) })
})

// 棋盘上的手势:左右划(手指挪一格多就挪一列)、往下拖(一格一格降)、往下一甩(落底)、点一下(旋转)
let g: { id: number; x0: number; y0: number; t0: number; cols: number; rows: number; moved: boolean
  trail: Array<[number, number]> } | null = null
frame.addEventListener('pointerdown', (e) => {
  if (e.button > 0) return
  g = { id: e.pointerId, x0: e.clientX, y0: e.clientY, t0: e.timeStamp, cols: 0, rows: 0, moved: false,
    trail: [[e.timeStamp, e.clientY]] }
  frame.setPointerCapture?.(e.pointerId)
})
frame.addEventListener('pointermove', (e) => {
  if (!g || e.pointerId !== g.id) return
  const dx = e.clientX - g.x0
  const dy = e.clientY - g.y0
  if (!g.moved && Math.hypot(dx, dy) > 10) g.moved = true
  if (!g.moved || mode !== 'running') return
  g.trail.push([e.timeStamp, e.clientY])
  while (g.trail.length > 2 && e.timeStamp - g.trail[0][0] > 150) g.trail.shift()
  const step = Math.max(12, cell * 0.9)
  const cols = Math.trunc(dx / step)
  while (g.cols < cols) { act('right'); g.cols++ }
  while (g.cols > cols) { act('left'); g.cols-- }
  if (dy > Math.abs(dx)) {
    const rows = Math.floor(dy / step)
    while (g.rows < rows) { act('down'); g.rows++ }
  }
})
frame.addEventListener('pointerup', (e) => {
  if (!g || e.pointerId !== g.id) return
  const gg = g
  g = null
  const dx = e.clientX - gg.x0
  const dy = e.clientY - gg.y0
  if (!gg.moved) {
    if (e.timeStamp - gg.t0 < 400) act('rotate') // 还没开始或暂停中,点一下是继续
    return
  }
  const old = gg.trail.find(([t]) => e.timeStamp - t <= 100) || gg.trail[0]
  const v = (e.clientY - old[1]) / Math.max(1, e.timeStamp - old[0])
  if (v > 0.9 && dy > cell * 2 && dy > Math.abs(dx) * 2) act('drop')
})
frame.addEventListener('pointercancel', () => { g = null })

pauseBtn.addEventListener('click', () => {
  togglePause()
  canvas.focus()
})
$('new').addEventListener('click', () => { void askRestart() })
$('about-btn').addEventListener('click', showAbout)
WebApp.SettingsButton.show().onClick(showAbout)
WebApp.BackButton.onClick(pause)

// ---------------------------------------------------------------- 弹层

function showOver(): void {
  if (mode !== 'over') return
  overlay.show((p) => {
    p.append(el('h2', '到顶了'), el('div', String(state.score), 'big'),
      el('p', `消了 ${state.lines} 行 · 第 ${state.level} 级 · 最好成绩 ${best.score}`),
      row(button('再来一局', restart, 'primary')))
  }, { onDismiss: () => undefined })
}

function showAbout(): void {
  pause()
  overlay.show((p) => {
    p.append(el('h2', '关于方块消除'), bullets([
      '按钮:左右挪、往下降(按住左右或往下会连着动)、落底、旋转。',
      '在棋盘上:左右划挪动,往下拖慢慢降,往下一甩直接落底,点一下旋转。',
      '键盘:← → 挪,↓ 降,↑ 或 X 顺时针转,Z 逆时针转,空格落底,P 暂停。',
      '一行满了就消掉,一次消得越多分越高;每消 10 行升一级,落得更快。',
      '没有广告,没有内购,没有排行榜。',
      '前端游戏的分数没法由服务器验证,所以成绩只存在你自己这里,不给别人看。',
      '每落下一块自动存档到超级赞云存储,关了再开、换设备都能接着玩(接上时先暂停着)。',
      `玩过 ${best.games} 局,最高 ${best.score} 分,最多消 ${best.lines} 行,最高第 ${best.level || 1} 级。`,
    ]), row(button('知道了', () => overlay.hide(), 'primary')))
  }, { cls: 'about', onDismiss: () => undefined })
}

// ---------------------------------------------------------------- 存档与启动

function adopt(s: State): void {
  state = s
  flash = null
  mode = s.over ? 'over' : started(s) ? 'paused' : 'ready'
}

function applyTheme(): void {
  pal = document.documentElement.classList.contains('dark') ? DARK : LIGHT
  draw()
}

followTheme(applyTheme)
if (slot.restoreLocal() && slot.state) adopt(slot.state)
best = slot.best
layout()
syncUi()
drawStats()
new ResizeObserver(layout).observe(play)
hostGame(() => {
  pause()
  void slot.flush()
})
let readied = false
const ready = () => {
  if (readied) return
  readied = true
  WebApp.ready().catch(() => undefined)
}
setTimeout(ready, 1500)
slot.restoreCloud().then((r) => {
  best = slot.best
  if (r === 'cloud' && slot.state) adopt(slot.state)
  else if (r === 'cleared') adopt(newGame(freshSeed()))
  draw()
  syncUi()
  drawStats()
}).finally(() => {
  if (mode === 'over') showOver()
  ready()
  canvas.focus()
})
