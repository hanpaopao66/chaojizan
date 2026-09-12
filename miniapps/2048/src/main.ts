// 2048 的界面:DOM 方块 + CSS transform(16 个方块用不着 canvas,还便于读屏)。
// 规则全在 engine.ts;这里只管输入、动画、存档和宿主能力(全屏、锁方向、触感)。
import WebApp from '../../../packages/miniapp-sdk/src/index'
import {
  Best, Dir, MoveResult, SIZE, State, Tile, load, maxTile, move, newGame, save, updateBest,
} from './engine'
import { tileColor } from './palette'
import './style.css'

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T
const board = $('board')
const tilesEl = board.querySelector('.tiles') as HTMLElement
const cellsEl = board.querySelector('.cells') as HTMLElement
const scoreEl = $('score')
const bestEl = $('best')
const overlay = $('overlay')
const live = $('live')
const SLIDE_MS = 120
const SAVE_DELAY = 500
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches

// 本机缓存按 open_id 分开(同一台设备换账号,接不上上一个人的棋局)
const who = WebApp.initDataUnsafe.user?.open_id || 'anon'
const cacheKey = `2048:v1:${who}`

let state: State = newGame((Math.random() * 2 ** 32) >>> 0)
let best: Best = { v: 1, score: 0, max_tile: 0, games: 0 }
let animating = false
let pending: Dir | null = null
let saveTimer: ReturnType<typeof setTimeout> | undefined
let savedAt = 0
const els = new Map<number, HTMLElement>()

// ---------------------------------------------------------------- 画

function layout(): void {
  const w = tilesEl.clientWidth
  if (!w) return
  const g = Math.round(w * 0.03)
  const cell = (w - g * (SIZE - 1)) / SIZE
  board.style.setProperty('--cell', `${cell}px`)
  board.style.setProperty('--g', `${g}px`)
  board.style.setProperty('--step', `${cell + g}px`)
}

function tileEl(t: Tile, cls = ''): HTMLElement {
  const el = document.createElement('div')
  const digits = String(t.value).length
  el.className = `tile d${Math.max(2, digits)} ${cls} ${t.value === 2048 ? 'v2048' : ''}`.trim()
  const { bg, fg } = tileColor(t.value)
  const b = document.createElement('b')
  b.textContent = String(t.value)
  b.style.background = bg
  b.style.color = fg
  el.append(b)
  place(el, t)
  el.setAttribute('role', 'gridcell')
  el.setAttribute('aria-label', `第 ${t.row + 1} 行第 ${t.col + 1} 列:${t.value}`)
  return el
}

function place(el: HTMLElement, t: { row: number; col: number }): void {
  el.style.setProperty('--r', String(t.row))
  el.style.setProperty('--c', String(t.col))
}

function drawAll(): void {
  tilesEl.textContent = ''
  els.clear()
  for (const t of state.tiles) {
    const el = tileEl(t)
    els.set(t.id, el)
    tilesEl.append(el)
  }
  drawScores(false)
}

function drawScores(bump: boolean): void {
  scoreEl.textContent = String(state.score)
  bestEl.textContent = String(Math.max(best.score, state.score))
  if (bump && !reduced()) {
    const box = scoreEl.parentElement as HTMLElement
    box.classList.remove('bump')
    void box.offsetWidth
    box.classList.add('bump')
  }
}

function animate(r: MoveResult): void {
  // ① 所有留下来的块滑到新位置,被合并掉的两块滑到合并点
  for (const t of r.state.tiles) {
    const el = els.get(t.id)
    if (el) place(el, t)
  }
  for (const c of r.consumed) {
    const el = els.get(c.id)
    if (el) place(el, c)
  }
  const finish = () => {
    // ② 滑完:删掉被合并的,放上合并出来的(弹一下)和新出的块(从 0.6 放大)
    for (const c of r.consumed) {
      els.get(c.id)?.remove()
      els.delete(c.id)
    }
    for (const m of r.merged) {
      const el = tileEl(m, 'pop')
      els.set(m.id, el)
      tilesEl.append(el)
    }
    if (r.spawned) {
      const el = tileEl(r.spawned, 'new')
      els.set(r.spawned.id, el)
      tilesEl.append(el)
    }
    animating = false
    if (pending) {
      const d = pending
      pending = null
      step(d)
    }
  }
  if (reduced()) finish()
  else setTimeout(finish, SLIDE_MS)
}

// ---------------------------------------------------------------- 走一步

function step(dir: Dir): void {
  if (!overlay.hidden) return
  if (animating) {
    pending = dir // 动画期间最多缓存 1 步
    return
  }
  const r = move(state, dir)
  if (!r.moved) return
  animating = true
  state = r.state
  animate(r)
  drawScores(r.gained > 0)
  if (r.merged.some((t) => t.value >= 128)) WebApp.HapticFeedback.impactOccurred('light')
  live.textContent = r.gained ? `合并得 ${r.gained} 分,共 ${state.score} 分` : ''
  if (state.score > best.score || maxTile(state.tiles) > best.max_tile) best = updateBest(best, state, false)
  scheduleSave()
  if (r.justWon) {
    WebApp.HapticFeedback.notificationOccurred('success')
    setTimeout(showWin, SLIDE_MS + 60)
  } else if (state.over) {
    WebApp.HapticFeedback.notificationOccurred('warning')
    best = updateBest(best, state, true)
    saveNow()
    setTimeout(showOver, SLIDE_MS + 60)
  }
}

// ---------------------------------------------------------------- 输入

const KEYS: Record<string, Dir> = {
  ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
  w: 'up', s: 'down', a: 'left', d: 'right', W: 'up', S: 'down', A: 'left', D: 'right',
}
window.addEventListener('keydown', (e) => {
  const d = KEYS[e.key]
  if (!d || e.metaKey || e.ctrlKey || e.altKey) return
  e.preventDefault()
  step(d)
})

let start: { x: number; y: number } | null = null
const THRESHOLD = 24
board.addEventListener('pointerdown', (e) => {
  start = { x: e.clientX, y: e.clientY }
  board.setPointerCapture?.(e.pointerId)
})
board.addEventListener('pointerup', (e) => {
  if (!start) return
  const dx = e.clientX - start.x
  const dy = e.clientY - start.y
  start = null
  const ax = Math.abs(dx)
  const ay = Math.abs(dy)
  if (Math.max(ax, ay) < THRESHOLD) return
  // 斜着划不算:一个方向要明显大于另一个
  if (ax > ay * 1.3) step(dx > 0 ? 'right' : 'left')
  else if (ay > ax * 1.3) step(dy > 0 ? 'down' : 'up')
})
board.addEventListener('pointercancel', () => { start = null })

// ---------------------------------------------------------------- 弹层

function panel(html: (root: HTMLElement) => void, cls = ''): void {
  overlay.textContent = ''
  const p = document.createElement('div')
  p.className = `panel ${cls}`
  p.setAttribute('role', 'dialog')
  html(p)
  overlay.append(p)
  overlay.hidden = false
  ;(p.querySelector('button.primary') as HTMLElement | null)?.focus()
}

function button(text: string, onClick: () => void, primary = false): HTMLButtonElement {
  const b = document.createElement('button')
  b.type = 'button'
  b.textContent = text
  if (primary) b.className = 'primary'
  b.addEventListener('click', onClick)
  return b
}

function el(tag: string, text: string, cls = ''): HTMLElement {
  const e = document.createElement(tag)
  e.textContent = text
  if (cls) e.className = cls
  return e
}

function closePanel(): void {
  overlay.hidden = true
  overlay.textContent = ''
  board.focus()
}

function showWin(): void {
  panel((p) => {
    p.append(el('h2', '你拼出了 2048'), el('p', `${state.moves} 步,${state.score} 分`))
    const row = el('div', '', 'row')
    row.append(button('新游戏', restart), button('继续玩', closePanel, true))
    p.append(row)
  })
}

function showOver(): void {
  panel((p) => {
    p.append(el('h2', '没有路可走了'), el('div', String(state.score), 'big'),
      el('p', `最大方块 ${maxTile(state.tiles)} · 最好成绩 ${best.score}`))
    const row = el('div', '', 'row')
    row.append(button('再来一局', restart, true))
    p.append(row)
  })
}

function showAbout(): void {
  panel((p) => {
    p.append(el('h2', '关于 2048'))
    const ul = document.createElement('ul')
    for (const t of [
      '滑动或用方向键(也可以用 W A S D),相同的数字合并;拼出 2048 之后还能接着玩。',
      '没有广告,没有内购,没有排行榜。',
      '前端游戏的分数没法由服务器验证,所以成绩只存在你自己这里,不给别人看。',
      '每一步自动存档到超级赞云存储,关了再开、换设备都能接着玩。',
      `玩过 ${best.games} 局,最好 ${best.score} 分,最大方块 ${best.max_tile || '—'}。`,
    ]) ul.append(el('li', t))
    p.append(ul)
    const row = el('div', '', 'row')
    row.append(button('知道了', closePanel, true))
    p.append(row)
  }, 'about')
}

function restart(): void {
  closePanel()
  if (state.moves > 0 && !state.over) best = updateBest(best, state, true)
  state = newGame((Math.random() * 2 ** 32) >>> 0)
  drawAll()
  saveNow()
}

$('new').addEventListener('click', async () => {
  if (state.moves > 0 && !state.over) {
    const ok = await WebApp.showConfirm('放弃这一局,开始新游戏?').catch(() => window.confirm('放弃这一局,开始新游戏?'))
    if (!ok) return
  }
  restart()
})
$('about-btn').addEventListener('click', showAbout)
overlay.addEventListener('click', (e) => { if (e.target === overlay && !state.over) closePanel() })
WebApp.SettingsButton.show().onClick(showAbout)

// ---------------------------------------------------------------- 存档

function writeLocal(): void {
  try { localStorage.setItem(cacheKey, JSON.stringify({ state: save(state), best, at: savedAt })) } catch (_) { /* 满了 */ }
}

function scheduleSave(): void {
  savedAt = Date.now()
  writeLocal()
  clearTimeout(saveTimer)
  saveTimer = setTimeout(saveNow, SAVE_DELAY)
}

function saveNow(): void {
  clearTimeout(saveTimer)
  savedAt = savedAt || Date.now()
  writeLocal()
  // 棋局按「最后一次写的赢」:同一局在两台设备上交替玩,以最近那一步为准
  const payload = JSON.stringify({ ...save(state), at: savedAt })
  WebApp.CloudStorage.setItem('state', payload).catch(() => undefined)
  WebApp.CloudStorage.setItem('best', JSON.stringify(best)).catch(() => undefined)
}

async function restore(): Promise<void> {
  // ① 本机缓存秒开
  try {
    const local = JSON.parse(localStorage.getItem(cacheKey) || 'null')
    if (local) {
      const s = load(JSON.stringify(local.state))
      if (s) { state = s; savedAt = Number(local.at) || 0 }
      if (local.best?.v === 1) best = local.best
    }
  } catch (_) { /* 没有缓存 */ }
  drawAll()
  // ② 云端更新的话(别的设备上接着玩过),换成云端的
  try {
    const r = await WebApp.CloudStorage.getItems(['state', 'best'])
    const cloudBest = r.best ? JSON.parse(r.best) as Best : null
    if (cloudBest?.v === 1) {
      best = { v: 1, score: Math.max(best.score, cloudBest.score), max_tile: Math.max(best.max_tile, cloudBest.max_tile),
        games: Math.max(best.games, cloudBest.games) }
    }
    if (r.state) {
      const at = Number(JSON.parse(r.state).at) || 0
      const s = load(r.state)
      if (s && at > savedAt) {
        state = s
        savedAt = at
        drawAll()
        writeLocal()
      }
    }
    drawScores(false)
  } catch (_) { /* 离线:接着玩本机的 */ }
  if (state.over) showOver()
}

// ---------------------------------------------------------------- 启动

function applyFallbackTheme(): void {
  const hasHostTheme = Object.keys(WebApp.themeParams).length > 0
  document.documentElement.classList.toggle('dark-fallback',
    !hasHostTheme && matchMedia('(prefers-color-scheme: dark)').matches)
}

for (let i = 0; i < SIZE * SIZE; i++) cellsEl.append(document.createElement('i'))
applyFallbackTheme()
WebApp.onEvent('themeChanged', applyFallbackTheme)
layout()
new ResizeObserver(layout).observe(tilesEl)
restore().finally(() => {
  WebApp.ready().catch(() => undefined)
  board.focus()
})
// 小游戏:全屏、锁竖屏(superz.json 里 orientation 也写了 portrait,宿主打开时就锁)
WebApp.requestFullscreen().catch(() => undefined)
WebApp.lockOrientation().catch(() => undefined)
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') saveNow() })
