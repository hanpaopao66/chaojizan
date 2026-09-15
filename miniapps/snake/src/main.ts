// 贪吃蛇的界面:canvas 画棋盘,requestAnimationFrame 按 interval() 的节奏走格子。
// 规则全在 engine.ts;这里只管输入(滑动、方向键、屏幕方向键)、画、暂停、存档和宿主能力。
import '../../shared/src/base.css'
import './style.css'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import {
  $, Overlay, WebApp, bullets, button, cacheKey, cloud, confirmBox, el, followTheme, hostGame, local, reduced, row,
} from '../../shared/src/ui'
import {
  Best, Dir, EMPTY_BEST, State, interval, load, loadBest, mergeBest, newGame, rowCol, save, step, turn, updateBest,
} from './engine'
import { DARK, LIGHT, Palette } from './palette'

type Mode = 'ready' | 'running' | 'paused' | 'over'

const stage = $('stage')
const canvas = $<HTMLCanvasElement>('board')
const ctx = canvas.getContext('2d') as CanvasRenderingContext2D
const veil = $('veil')
const veilText = $('veil-text')
const scoreEl = $('score')
const bestEl = $('best')
const pauseBtn = $<HTMLButtonElement>('pause')
const live = $('live')
const overlay = new Overlay($('overlay'), () => canvas.focus())

const slot = new SaveSlot<State, Best>({
  cacheKey: cacheKey('snake'), cloud, local, loadState: load, saveState: save, loadBest, mergeBest,
  emptyBest: EMPTY_BEST,
  // 一边玩一边存:云端最多 5 秒写一次(暂停、撞了、切走时立刻写)
  delay: 1000, minGap: 5000,
})

let state: State = newGame(freshSeed())
let best: Best = EMPTY_BEST
let mode: Mode = 'ready'
let pal: Palette = LIGHT
let cell = 16

// ---------------------------------------------------------------- 画

function layout(): void {
  const w = stage.clientWidth
  const h = stage.clientHeight
  if (!w || !h) return
  cell = Math.max(8, Math.floor(Math.min(w / state.cols, h / state.rows)))
  const cw = cell * state.cols
  const ch = cell * state.rows
  const dpr = Math.min(3, window.devicePixelRatio || 1)
  canvas.style.width = `${cw}px`
  canvas.style.height = `${ch}px`
  canvas.width = Math.round(cw * dpr)
  canvas.height = Math.round(ch * dpr)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  draw()
}

function center(i: number): [number, number] {
  const [r, c] = rowCol(state, i)
  return [(c + 0.5) * cell, (r + 0.5) * cell]
}

function draw(): void {
  const { cols, rows, snake } = state
  ctx.fillStyle = pal.boardA
  ctx.fillRect(0, 0, cols * cell, rows * cell)
  ctx.fillStyle = pal.boardB
  for (let r = 0; r < rows; r++) {
    for (let c = (r + 1) % 2; c < cols; c += 2) ctx.fillRect(c * cell, r * cell, cell, cell)
  }
  if (state.food >= 0) {
    const [x, y] = center(state.food)
    ctx.fillStyle = pal.food
    ctx.beginPath()
    ctx.arc(x, y, cell * 0.34, 0, Math.PI * 2)
    ctx.fill()
  }
  // 蛇身:一条粗线穿过每一节的中心,拐弯处是圆的
  ctx.strokeStyle = pal.snake
  ctx.lineWidth = cell * 0.7
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.beginPath()
  snake.forEach((i, k) => {
    const [x, y] = center(i)
    if (k === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.stroke()
  // 蛇头和眼睛(眼睛朝着前进方向)
  const [hx, hy] = center(snake[0])
  const crashed = state.over && !state.won
  ctx.fillStyle = crashed ? pal.crash : pal.head
  ctx.beginPath()
  ctx.arc(hx, hy, cell * 0.44, 0, Math.PI * 2)
  ctx.fill()
  const [fx, fy] = ({ up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] } as Record<Dir, number[]>)[state.dir]
  ctx.fillStyle = pal.eye
  for (const side of [-1, 1]) {
    const ex = hx + fx * cell * 0.14 + -fy * side * cell * 0.19
    const ey = hy + fy * cell * 0.14 + fx * side * cell * 0.19
    ctx.beginPath()
    ctx.arc(ex, ey, Math.max(1.2, cell * 0.08), 0, Math.PI * 2)
    ctx.fill()
  }
}

function drawScores(bump = false): void {
  scoreEl.textContent = String(state.score)
  bestEl.textContent = String(Math.max(best.score, state.score))
  if (bump && !reduced()) {
    const box = scoreEl.parentElement as HTMLElement
    box.classList.remove('bump')
    void box.offsetWidth
    box.classList.add('bump')
  }
}

/** 暂停键的字、棋盘上的提示、宿主返回键:都跟着 mode 走 */
function syncUi(): void {
  pauseBtn.textContent = { ready: '开始', running: '暂停', paused: '继续', over: '暂停' }[mode]
  pauseBtn.disabled = mode === 'over'
  const tips: Partial<Record<Mode, [string, string]>> = {
    ready: ['滑动或按方向开始', '也可以用键盘的方向键、W A S D'],
    paused: ['已暂停', '点一下棋盘或按方向继续'],
  }
  const tip = tips[mode]
  veil.hidden = !tip
  if (tip) {
    veilText.textContent = tip[0]
    veilText.append(el('small', tip[1]))
    // 蛇头在上半边(开局就在正中偏上)就把提示放到下半边
    veil.classList.toggle('low', rowCol(state, state.snake[0])[0] <= state.rows / 2)
  }
  // 走着的时候显示宿主返回键:安卓的返回手势先暂停,不会一划就把正在跑的一局关掉
  if (mode === 'running') WebApp.BackButton.show()
  else WebApp.BackButton.hide()
  canvas.setAttribute('aria-label', `贪吃蛇棋盘,长度 ${state.snake.length},${
    { ready: '还没开始', running: '进行中', paused: '已暂停', over: '已结束' }[mode]}`)
}

// ---------------------------------------------------------------- 走

let raf = 0
let lastT = 0
let acc = 0

function loop(t: number): void {
  raf = 0
  if (mode !== 'running') return
  const dt = lastT ? Math.min(t - lastT, 250) : 0 // 卡了一下(切后台回来)不一口气补很多步
  lastT = t
  acc += dt
  let moved = false
  while (mode === 'running' && acc >= interval(state.score)) {
    acc -= interval(state.score)
    tick()
    moved = true
  }
  if (moved) draw()
  if (mode === 'running') raf = requestAnimationFrame(loop)
}

function startLoop(): void {
  if (raf) return
  lastT = 0
  acc = 0
  raf = requestAnimationFrame(loop)
}

function tick(): void {
  const r = step(state)
  state = r.state
  if (r.ate) {
    WebApp.HapticFeedback.impactOccurred('light')
    drawScores(true)
  }
  slot.change(state)
  if (state.over) finish()
}

function finish(): void {
  mode = 'over'
  best = updateBest(best, state, true)
  slot.setBest(best)
  void slot.flush()
  syncUi()
  draw()
  drawScores()
  WebApp.HapticFeedback.notificationOccurred(state.won ? 'success' : 'warning')
  const why = state.won ? '格子都占满了' : state.cause === 'wall' ? '撞墙了' : '咬到自己了'
  live.textContent = `${why},得 ${state.score} 分`
  // 先让人看一眼撞在哪,再弹结果
  setTimeout(showOver, reduced() ? 0 : 450)
}

// ---------------------------------------------------------------- 操作

function steer(d: Dir): void {
  if (overlay.open || mode === 'over') return
  const next = turn(state, d)
  if (mode === 'running') {
    state = next
    return
  }
  // 开局或暂停中按方向:走起来。按的是反方向(不算数)也照样继续
  state = next
  resume()
}

function pause(): void {
  if (mode !== 'running') return
  mode = 'paused'
  syncUi()
  void slot.flush()
}

function resume(): void {
  if (mode !== 'paused' && mode !== 'ready') return
  if (overlay.open) return
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
  if (state.steps > 0 && !state.over) {
    best = updateBest(best, state, true)
    slot.setBest(best)
  }
  state = newGame(freshSeed())
  mode = 'ready'
  slot.change(state)
  void slot.flush()
  syncUi()
  draw()
  drawScores()
  // 焦点别留在「新游戏」上:不然接着按空格想暂停,按到的是它
  canvas.focus()
}

async function askRestart(): Promise<void> {
  if (mode === 'running' || (mode === 'paused' && state.steps > 0)) {
    pause()
    if (!(await confirmBox('放弃这一局,重新开始?'))) return
  }
  restart()
}

// ---------------------------------------------------------------- 输入

const KEYS: Record<string, Dir> = {
  ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
  Up: 'up', Down: 'down', Left: 'left', Right: 'right', // 老浏览器的键名
  w: 'up', s: 'down', a: 'left', d: 'right', W: 'up', S: 'down', A: 'left', D: 'right',
}
window.addEventListener('keydown', (e) => {
  if (overlay.open || e.metaKey || e.ctrlKey || e.altKey) return
  const d = KEYS[e.key]
  if (d) {
    e.preventDefault()
    steer(d)
  } else if (e.key === ' ' || e.key === 'p' || e.key === 'P') {
    // 焦点在按钮上时空格是按那个按钮,不抢
    if (e.key === ' ' && (e.target as HTMLElement).tagName === 'BUTTON') return
    e.preventDefault()
    togglePause()
  }
})

// 滑动:手指移过一段距离就转向,然后从当前位置重新算 —— 不抬手也能连着拐几次
let anchor: { x: number; y: number; id: number; moved: boolean } | null = null
stage.addEventListener('pointerdown', (e) => {
  anchor = { x: e.clientX, y: e.clientY, id: e.pointerId, moved: false }
  stage.setPointerCapture?.(e.pointerId)
})
stage.addEventListener('pointermove', (e) => {
  if (!anchor || e.pointerId !== anchor.id) return
  const dx = e.clientX - anchor.x
  const dy = e.clientY - anchor.y
  const ax = Math.abs(dx)
  const ay = Math.abs(dy)
  const need = Math.max(14, Math.min(28, cell * 1.2))
  if (Math.max(ax, ay) < need) return
  if (ax > ay * 1.2) steer(dx > 0 ? 'right' : 'left')
  else if (ay > ax * 1.2) steer(dy > 0 ? 'down' : 'up')
  else return // 斜着划不算,等它偏向一边
  anchor = { x: e.clientX, y: e.clientY, id: e.pointerId, moved: true }
})
stage.addEventListener('pointerup', (e) => {
  if (!anchor || e.pointerId !== anchor.id) return
  const tapped = !anchor.moved && Math.hypot(e.clientX - anchor.x, e.clientY - anchor.y) < 10
  anchor = null
  // 点一下棋盘:暂停中继续;还没开始就朝着现在的方向走起来
  if (tapped && (mode === 'paused' || mode === 'ready')) resume()
})
stage.addEventListener('pointercancel', () => { anchor = null })

// 屏幕方向键:按下就转(不等抬手,少 100 多毫秒);键盘或读屏触发的 click(detail 为 0)也认
document.querySelectorAll<HTMLButtonElement>('.key[data-dir]').forEach((b) => {
  const d = b.dataset.dir as Dir
  b.addEventListener('pointerdown', (e) => {
    e.preventDefault()
    b.classList.add('hit')
    steer(d)
  })
  const up = () => b.classList.remove('hit')
  b.addEventListener('pointerup', up)
  b.addEventListener('pointercancel', up)
  b.addEventListener('pointerleave', up)
  b.addEventListener('click', (e) => { if (e.detail === 0) steer(d) })
})
pauseBtn.addEventListener('click', togglePause)
$('new').addEventListener('click', () => { void askRestart() })
$('about-btn').addEventListener('click', showAbout)
WebApp.SettingsButton.show().onClick(showAbout)
WebApp.BackButton.onClick(pause)

// ---------------------------------------------------------------- 弹层

function showOver(): void {
  if (mode !== 'over') return
  overlay.show((p) => {
    p.append(el('h2', state.won ? '格子都占满了' : state.cause === 'wall' ? '撞墙了' : '咬到自己了'),
      el('div', String(state.score), 'big'),
      el('p', `长度 ${state.snake.length} · 最好成绩 ${best.score}`),
      row(button('再来一局', restart, 'primary')))
  }, { onDismiss: () => undefined }) // 点空白处关掉可以看看最后的棋盘,「新游戏」随时能按
}

function showAbout(): void {
  pause()
  overlay.show((p) => {
    p.append(el('h2', '关于贪吃蛇'), bullets([
      '在棋盘上滑动、按方向键(也可以用 W A S D)或下面的方向按钮转向;空格或 P 暂停。',
      '吃到一个长一节、得 1 分,越长走得越快;撞墙或咬到自己就结束。',
      '没有广告,没有内购,没有排行榜。',
      '前端游戏的分数没法由服务器验证,所以成绩只存在你自己这里,不给别人看。',
      '一边玩一边自动存档到超级赞云存储,关了再开、换设备都能接着玩(接上时先暂停着,点一下再走)。',
      `玩过 ${best.games} 局,最好 ${best.score} 分。`,
    ]), row(button('知道了', () => overlay.hide(), 'primary')))
  }, { cls: 'about', onDismiss: () => undefined })
}

// ---------------------------------------------------------------- 存档与启动

/** 接上一局:结束的显示结果,走到一半的先暂停着 */
function adopt(s: State): void {
  state = s
  mode = s.over ? 'over' : s.steps > 0 ? 'paused' : 'ready'
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
drawScores()
new ResizeObserver(layout).observe(stage)
hostGame(() => {
  pause()
  void slot.flush()
})
// 等云端最多 1.5 秒再撤启动页:换了设备的一般这时已经接上了;网慢也不让人干等
let readied = false
const ready = () => {
  if (readied) return
  readied = true
  WebApp.ready().catch(() => undefined)
}
setTimeout(ready, 1500)
slot.restoreCloud().then((r) => {
  best = slot.best
  if (r === 'cloud' && slot.state) {
    adopt(slot.state)
    layout()
  } else if (r === 'cleared') {
    state = newGame(freshSeed())
    mode = 'ready'
    draw()
  }
  syncUi()
  drawScores()
}).finally(() => {
  if (mode === 'over') showOver()
  ready()
  canvas.focus()
})
