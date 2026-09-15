// 扫雷的界面:DOM 格子(每一步只改变了的那几格),点一下 / 长按 / 双击 / 右键 / 键盘都能玩。
// 规则全在 engine.ts;这里只管输入、画、计时、存档和宿主能力。
import '../../shared/src/base.css'
import './style.css'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import {
  $, Overlay, WebApp, bullets, button, cacheKey, cloud, confirmBox, el, followTheme, hostGame, local, row,
} from '../../shared/src/ui'
import {
  Best, EMPTY_BEST, LEVELS, LEVEL_KEYS, Level, State, chord, count, load, loadBest, mergeBest, newGame, remaining,
  reveal, save, tickTime, toggleFlag, updateBest, neighbors,
} from './engine'
import { DARK, LIGHT } from './palette'

const LONG_PRESS = 380
const DOUBLE_TAP = 400

const scroller = $('scroller')
const board = $('board')
const leftEl = $('left')
const timeEl = $('time')
const zoomBtn = $<HTMLButtonElement>('zoom')
const live = $('live')
const overlay = new Overlay($('overlay'), () => board.focus())

const slot = new SaveSlot<State, Best>({
  cacheKey: cacheKey('minesweeper'), cloud, local, loadState: load, saveState: save, loadBest, mergeBest,
  emptyBest: EMPTY_BEST,
})

let state: State = newGame('easy', freshSeed())
let best: Best = EMPTY_BEST
/** 「插旗」模式:点一下是插旗,长按是翻开 */
let flagMode = false
let zoom = false
let cursor = -1
let cells: HTMLElement[] = []
let shown: string[] = []

// ---------------------------------------------------------------- 画

/** 按滚动区的宽度算格子大小;放大模式固定 36px,放不下就滚 */
function layout(): void {
  const w = scroller.clientWidth
  if (!w) return
  const fit = Math.floor((w - 2 - (state.cols - 1)) / state.cols)
  const cell = zoom ? Math.max(fit, 36) : Math.max(18, Math.min(44, fit))
  board.style.setProperty('--cell', `${cell}px`)
  board.style.setProperty('--cols', String(state.cols))
  // 格子小于 30px(中级、高级在手机上)才给「放大」
  zoomBtn.hidden = fit >= 30
  zoomBtn.textContent = zoom ? '缩小' : '放大'
  zoomBtn.setAttribute('aria-pressed', String(zoom))
}

function build(): void {
  board.textContent = ''
  cells = []
  shown = []
  for (let i = 0; i < state.cols * state.rows; i++) {
    const c = document.createElement('div')
    c.id = `c${i}`
    c.dataset.i = String(i)
    c.setAttribute('role', 'gridcell')
    board.append(c)
    cells.push(c)
    shown.push('')
  }
  cursor = Math.min(cursor, cells.length - 1)
  layout()
  render()
}

function describe(i: number, cls: string): string {
  const r = Math.floor(i / state.cols) + 1
  const c = (i % state.cols) + 1
  const what = cls.includes('boom') ? '踩到的雷' : cls.includes(' x') ? '插错的旗' : cls.includes(' f') ? '插了旗'
    : cls.includes(' m') ? '雷' : cls.includes(' h') ? '没翻开' : cls.includes(' n') ? `${count(state, i)}` : '空'
  return `第 ${r} 行第 ${c} 列,${what}`
}

function classOf(i: number): string {
  if (state.open[i]) {
    if (state.mine[i]) return 'c m boom'
    const n = count(state, i)
    return n ? `c n${n}` : 'c'
  }
  if (state.status === 'lost') {
    if (state.mine[i] && !state.flag[i]) return 'c m'
    if (state.flag[i] && !state.mine[i]) return 'c h f x'
  }
  return state.flag[i] ? 'c h f' : 'c h'
}

/** 只改变了的格子 */
function render(): void {
  for (let i = 0; i < cells.length; i++) {
    const cls = classOf(i) + (i === cursor ? ' cur' : '')
    if (cls === shown[i]) continue
    shown[i] = cls
    const c = cells[i]
    c.className = cls
    const n = state.open[i] && !state.mine[i] ? count(state, i) : 0
    c.textContent = n ? String(n) : ''
    c.setAttribute('aria-label', describe(i, cls))
  }
  board.classList.toggle('done', state.status === 'won' || state.status === 'lost')
  if (cursor >= 0) board.setAttribute('aria-activedescendant', `c${cursor}`)
  else board.removeAttribute('aria-activedescendant')
  drawInfo()
}

function fmt(ms: number): string {
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function drawInfo(): void {
  leftEl.textContent = String(remaining(state))
  timeEl.textContent = fmt(state.elapsed)
  document.querySelectorAll<HTMLButtonElement>('#levels button').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.level === state.level))
  })
  document.querySelectorAll<HTMLButtonElement>('#mode button').forEach((b) => {
    b.setAttribute('aria-pressed', String((b.dataset.mode === 'flag') === flagMode))
  })
}

function applyPalette(): void {
  const p = document.documentElement.classList.contains('dark') ? DARK : LIGHT
  const root = document.documentElement.style
  root.setProperty('--ms-grid', p.grid)
  root.setProperty('--ms-hidden', p.hidden)
  root.setProperty('--ms-edge', p.edge)
  root.setProperty('--ms-open', p.open)
  root.setProperty('--ms-flag', p.flag)
  root.setProperty('--ms-mine', p.mine)
  root.setProperty('--ms-boom', p.boom)
  p.numbers.forEach((c, i) => root.setProperty(`--ms-n${i + 1}`, c))
}

// ---------------------------------------------------------------- 计时

let timer = 0
let lastT = 0
/** 在走表。接上的一局、切到后台回来,都等下一次操作再接着计 */
let timing = false

function startTiming(): void {
  timing = true
  if (timer) return
  lastT = performance.now()
  timer = window.setInterval(() => {
    const now = performance.now()
    const dt = now - lastT
    lastT = now
    if (!timing || document.visibilityState === 'hidden' || overlay.open) return
    state = tickTime(state, dt)
    timeEl.textContent = fmt(state.elapsed)
  }, 250)
}

function stopTiming(): void {
  timing = false
  if (timer) clearInterval(timer)
  timer = 0
}

// ---------------------------------------------------------------- 操作

const playable = () => !overlay.open && (state.status === 'ready' || state.status === 'playing')

function apply(next: State, opened: number[]): void {
  if (next === state) return
  const before = state.status
  state = next
  if (state.status === 'playing') startTiming()
  render()
  slot.change(state)
  if (opened.length > 8) WebApp.HapticFeedback.impactOccurred('light')
  if (state.status === 'lost' && before !== 'lost') lost()
  else if (state.status === 'won' && before !== 'won') won()
}

function revealAt(i: number): void {
  if (!playable()) return
  const r = reveal(state, i)
  apply(r.state, r.opened)
}

function flagAt(i: number): void {
  if (!playable()) return
  const next = toggleFlag(state, i)
  if (next === state) return
  WebApp.HapticFeedback.selectionChanged()
  apply(next, [])
}

/** 数字上快速翻开;旗不够就让周围没翻开的格子亮一下,告诉你它在看哪几格 */
function chordAt(i: number): void {
  if (!playable()) return
  const r = chord(state, i)
  if (r.state === state) {
    peek(i)
    return
  }
  apply(r.state, r.opened)
}

function peek(i: number): void {
  const around = neighbors(state, i).filter((j) => !state.open[j] && !state.flag[j])
  for (const j of around) cells[j].classList.add('peek')
  setTimeout(() => { for (const j of around) cells[j]?.classList.remove('peek') }, 180)
}

function won(): void {
  stopTiming()
  const prev = best[state.level].time
  best = updateBest(best, state)
  slot.setBest(best)
  void slot.flush()
  WebApp.HapticFeedback.notificationOccurred('success')
  live.textContent = `扫完了,用时 ${fmt(state.elapsed)}`
  const record = !prev || state.elapsed < prev
  setTimeout(() => showEnd(record), 300)
}

function lost(): void {
  stopTiming()
  best = updateBest(best, state)
  slot.setBest(best)
  void slot.flush()
  WebApp.HapticFeedback.notificationOccurred('error')
  live.textContent = '踩到雷了'
  // 先让人看一眼雷都在哪,再弹结果
  setTimeout(() => showEnd(false), 800)
}

function startNew(level: Level): void {
  overlay.hide()
  // 玩到一半放弃也记一局
  if (state.status === 'playing') {
    best = updateBest(best, state)
    slot.setBest(best)
  }
  stopTiming()
  const sameSize = level === state.level
  state = newGame(level, freshSeed())
  zoom = zoom && sameSize
  slot.change(state)
  void slot.flush()
  scroller.scrollTo?.(0, 0)
  build()
  board.focus()
}

async function askNew(level: Level): Promise<void> {
  if (state.status === 'playing') {
    const msg = level === state.level ? '放弃这一局,重新开始?' : `放弃这一局,换成${LEVELS[level].name}?`
    if (!(await confirmBox(msg))) return
  }
  startNew(level)
}

// ---------------------------------------------------------------- 输入

function cellOf(t: EventTarget | null): number {
  const c = (t as HTMLElement | null)?.closest?.('.c') as HTMLElement | null
  return c && c.dataset.i ? Number(c.dataset.i) : -1
}

let press: { i: number; id: number; x: number; y: number; timer: number; done: boolean; moved: boolean } | null = null
let lastTap = { i: -1, t: 0 }
let lastPointer = 'mouse'
let lastTouched = -1

board.addEventListener('pointerdown', (e) => {
  lastPointer = e.pointerType
  const i = cellOf(e.target)
  if (i < 0) return
  if (e.button === 2) return // 右键交给 contextmenu
  if (e.button === 1) { // 中键:快速翻开
    e.preventDefault()
    chordAt(i)
    return
  }
  if (press) clearTimeout(press.timer)
  press = { i, id: e.pointerId, x: e.clientX, y: e.clientY, done: false, moved: false,
    timer: window.setTimeout(() => {
      if (!press || press.moved) return
      press.done = true
      // 长按:数字上是快速翻开;没翻开的格子上是「另一种」操作
      if (state.open[press.i]) chordAt(press.i)
      else if (flagMode) revealAt(press.i)
      else flagAt(press.i)
    }, LONG_PRESS) }
})
board.addEventListener('pointermove', (e) => {
  if (!press || e.pointerId !== press.id || press.moved) return
  if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > 8) {
    press.moved = true // 在滚动,不是点
    clearTimeout(press.timer)
  }
})
board.addEventListener('pointerup', (e) => {
  if (!press || e.pointerId !== press.id) return
  const p = press
  press = null
  clearTimeout(p.timer)
  if (p.done || p.moved) return
  lastTouched = p.i // 键盘接着操作时从这一格开始(点的时候不画键盘光标,手机上是干扰)
  tap(p.i, e.timeStamp)
})
board.addEventListener('pointercancel', () => {
  if (press) clearTimeout(press.timer)
  press = null
})
// 电脑右键插旗。手机长按也会发 contextmenu,那边已经由长按处理了,这里只拦掉系统菜单
board.addEventListener('contextmenu', (e) => {
  e.preventDefault()
  const i = cellOf(e.target)
  if (i >= 0 && lastPointer === 'mouse') flagAt(i)
})

function tap(i: number, t: number): void {
  if (state.open[i]) {
    // 翻开的数字:双击快速翻开;单击只让周围亮一下
    if (lastTap.i === i && t - lastTap.t < DOUBLE_TAP) {
      lastTap = { i: -1, t: 0 }
      chordAt(i)
    } else {
      lastTap = { i, t }
      if (count(state, i)) peek(i)
    }
    return
  }
  lastTap = { i: -1, t: 0 }
  if (flagMode) flagAt(i)
  else revealAt(i)
}

function setCursor(i: number): void {
  cursor = i
  render()
  cells[i]?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
}

// 键盘:方向键移动,空格 / 回车翻开(数字上是翻开周围),F 插旗
board.addEventListener('keydown', (e) => {
  if (overlay.open || e.metaKey || e.ctrlKey || e.altKey) return
  const moves: Record<string, [number, number]> = {
    ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
    Up: [-1, 0], Down: [1, 0], Left: [0, -1], Right: [0, 1],
  }
  const m = moves[e.key]
  if (m) {
    e.preventDefault()
    // 第一下方向键先把光标放出来(在最后点过的那格,没点过就在正中),之后才挪
    const fresh = cursor < 0
    const at = fresh ? (lastTouched >= 0 && lastTouched < cells.length ? lastTouched
      : Math.floor(state.rows / 2) * state.cols + Math.floor(state.cols / 2)) : cursor
    const r = Math.min(state.rows - 1, Math.max(0, Math.floor(at / state.cols) + (fresh ? 0 : m[0])))
    const c = Math.min(state.cols - 1, Math.max(0, (at % state.cols) + (fresh ? 0 : m[1])))
    setCursor(r * state.cols + c)
    return
  }
  if (cursor < 0) return
  if (e.key === ' ' || e.key === 'Enter') {
    e.preventDefault()
    if (state.open[cursor]) chordAt(cursor)
    else if (flagMode) flagAt(cursor)
    else revealAt(cursor)
  } else if (e.key === 'f' || e.key === 'F') {
    e.preventDefault()
    flagAt(cursor)
  }
})
board.addEventListener('blur', () => {
  if (cursor >= 0 && !board.matches(':focus-within')) {
    cursor = -1
    render()
  }
})

document.querySelectorAll<HTMLButtonElement>('#levels button').forEach((b) => {
  b.addEventListener('click', () => {
    const level = b.dataset.level as Level
    if (level !== state.level) void askNew(level)
  })
})
document.querySelectorAll<HTMLButtonElement>('#mode button').forEach((b) => {
  b.addEventListener('click', () => {
    flagMode = b.dataset.mode === 'flag'
    $('hint').textContent = flagMode ? '点一下插旗 · 长按翻开' : '长按插旗 · 双击数字翻开周围'
    drawInfo()
  })
})
zoomBtn.addEventListener('click', () => {
  zoom = !zoom
  layout()
})
$('new').addEventListener('click', () => { void askNew(state.level) })
$('about-btn').addEventListener('click', showAbout)
WebApp.SettingsButton.show().onClick(showAbout)

// ---------------------------------------------------------------- 弹层

function showEnd(record: boolean): void {
  if (state.status !== 'won' && state.status !== 'lost') return
  const b = best[state.level]
  overlay.show((p) => {
    if (state.status === 'won') {
      p.append(el('h2', record ? '扫完了,新纪录' : '扫完了'), el('div', fmt(state.elapsed), 'big'),
        el('p', `${LEVELS[state.level].name} · 最快 ${fmt(b.time)} · 赢了 ${b.wins} / ${b.games} 局`))
    } else {
      p.append(el('h2', '踩到雷了'), el('p', `${LEVELS[state.level].name} · 用时 ${fmt(state.elapsed)} · 赢了 ${b.wins} / ${b.games} 局`))
    }
    p.append(row(button('看看棋盘', () => overlay.hide()), button('再来一局', () => startNew(state.level), 'primary')))
  }, { onDismiss: () => undefined })
}

function showAbout(): void {
  overlay.show((p) => {
    const stats = LEVEL_KEYS.map((k) => {
      const b = best[k]
      return `${LEVELS[k].name}:赢了 ${b.wins} / ${b.games} 局${b.time ? `,最快 ${fmt(b.time)}` : ''}`
    })
    p.append(el('h2', '关于扫雷'), bullets([
      '点一下翻开,长按插旗;切到底下的「插旗」,点一下就是插旗(长按变成翻开)。',
      '数字是周围 8 格里有几颗雷。在翻开的数字上双击(或长按):周围的旗插够了,就把其余的一次翻开。',
      '电脑上:右键插旗,双击数字或按鼠标中键翻开周围;键盘用方向键移动,空格或回车翻开,F 插旗。',
      '第一下永远不是雷。中级、高级格子小,可以点「放大」再滚着看。',
      '没有广告,没有内购,没有排行榜。',
      '前端游戏的成绩没法由服务器验证,所以成绩只存在你自己这里,不给别人看。',
      '每一步自动存档到超级赞云存储,关了再开、换设备都能接着玩;切走时计时停,回来点一下接着计。',
      ...stats,
    ]), row(button('知道了', () => overlay.hide(), 'primary')))
  }, { cls: 'about', onDismiss: () => undefined })
}

// ---------------------------------------------------------------- 存档与启动

function adopt(s: State): void {
  stopTiming() // 接上的一局等下一次操作再计时
  const rebuild = s.cols * s.rows !== cells.length
  state = s
  if (rebuild) build()
  else {
    layout()
    render()
  }
}

followTheme(applyPalette)
if (slot.restoreLocal() && slot.state) state = slot.state
best = slot.best
build()
new ResizeObserver(layout).observe(scroller)
hostGame(() => {
  stopTiming()
  slot.change(state)
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
  else if (r === 'cleared') adopt(newGame(state.level, freshSeed()))
  drawInfo()
}).finally(() => {
  ready()
  board.focus()
})
