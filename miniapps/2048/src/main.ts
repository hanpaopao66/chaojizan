// 2048 的界面:DOM 方块 + CSS transform(16 个方块用不着 canvas,还便于读屏)。
// 规则全在 engine.ts;这里只管输入、动画、声音、存档和宿主能力(全屏、锁方向、触感)。
// 声音/触感走 shared/src/sfx.ts 的统一合成音;弹层、主题、宿主能力走 shared/src/ui.ts。
import '../../shared/src/base.css'
import './style.css'
import {
  haptic, installSfxUnlock, playSfx, sfxMuted, toggleSfxMuted,
} from '../../shared/src/sfx'
import {
  Best, Dir, MoveResult, SIZE, State, Tile, load, maxTile, move, newGame, save, updateBest,
} from './engine'
import { tileColor } from './palette'
import {
  $, Overlay, WebApp, button, cacheKey, cloud, el, followTheme, hostGame, local, reduced, row,
} from '../../shared/src/ui'

const board = $('board')
const tilesEl = board.querySelector('.tiles') as HTMLElement
const cellsEl = board.querySelector('.cells') as HTMLElement
const scoreEl = $('score')
const bestEl = $('best')
const live = $('live')
const soundBtn = $<HTMLButtonElement>('sound')
const overlay = new Overlay($('overlay'), () => board.focus())
const SLIDE_MS = 120
const SAVE_DELAY = 500

// 本机缓存的键按 open_id 分开(同一台设备换账号,接不上上一个人的棋局)
const cacheKeyName = cacheKey('2048')

let state: State = newGame((Math.random() * 2 ** 32) >>> 0)
let best: Best = { v: 1, score: 0, max_tile: 0, games: 0 }
let animating = false
let pending: Dir | null = null
let saveTimer: ReturnType<typeof setTimeout> | undefined
let savedAt = 0
const els = new Map<number, HTMLElement>()

// ---------------------------------------------------------------- 声音

/** 静音按钮:状态存在设备级 localStorage(shared 统一键),跨应用共用 */
function syncSound(): void {
  const muted = sfxMuted()
  soundBtn.textContent = muted ? '声音:关' : '声音:开'
  soundBtn.setAttribute('aria-label', muted ? '声音已关,点击打开声音' : '声音已开,点击静音')
}

soundBtn.addEventListener('click', () => {
  const muted = toggleSfxMuted()
  if (!muted) playSfx('ok')
  haptic('light')
  syncSound()
  live.textContent = muted ? '声音已关' : '声音已开'
})

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
  if (overlay.open) return
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
  if (r.gained) playSfx('merge')
  else playSfx('move')
  if (r.merged.some((t) => t.value >= 128)) haptic('light')
  live.textContent = r.gained ? `合并得 ${r.gained} 分,共 ${state.score} 分` : `得分 ${state.score}`
  if (state.score > best.score || maxTile(state.tiles) > best.max_tile) best = updateBest(best, state, false)
  scheduleSave()
  if (r.justWon) {
    playSfx('win')
    haptic('success')
    setTimeout(showWin, SLIDE_MS + 60)
  } else if (state.over) {
    playSfx('lose')
    haptic('warning')
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

function showWin(): void {
  overlay.show((p) => {
    p.append(el('h2', '你拼出了 2048'), el('p', `${state.moves} 步,${state.score} 分`))
    p.append(row(button('新游戏', restart), button('继续玩', () => overlay.hide(), 'primary')))
  }, { onDismiss: () => overlay.hide() })
}

function showOver(): void {
  overlay.show((p) => {
    p.append(el('h2', '没有路可走了'), el('div', String(state.score), 'big'),
      el('p', `最大方块 ${maxTile(state.tiles)} · 最好成绩 ${best.score}`))
    p.append(row(button('再来一局', restart, 'primary')))
  })
  live.textContent = `没有路可走了,得分 ${state.score}`
}

function showAbout(): void {
  overlay.show((p) => {
    p.append(el('h2', '关于 2048'))
    const ul = document.createElement('ul')
    for (const t of [
      '滑动或用方向键(也可以用 W A S D),相同的数字合并;拼出 2048 之后还能接着玩。',
      '没有广告,没有内购,没有排行榜。',
      '前端游戏的分数没法由服务器验证,所以成绩只存在你自己这里,不给别人看。',
      '每一步自动存档到超级赞云存储,关了再开、换设备都能接着玩。',
      `玩过 ${best.games} 局,最好 ${best.score} 分,最大方块 ${best.max_tile || '—'}。`,
      '音效由浏览器现场合成(WebAudio),不加载任何音频文件;声音开关只记在这台设备上。',
    ]) ul.append(el('li', t))
    p.append(ul)
    p.append(row(button('知道了', () => overlay.hide(), 'primary')))
  }, { cls: 'about', onDismiss: () => overlay.hide() })
}

function restart(): void {
  overlay.hide()
  if (state.moves > 0 && !state.over) best = updateBest(best, state, true)
  state = newGame((Math.random() * 2 ** 32) >>> 0)
  drawAll()
  saveNow()
  playSfx('start')
  haptic('medium')
  live.textContent = '新游戏开始'
  board.focus()
}

$('new').addEventListener('click', async () => {
  playSfx('tap')
  if (state.moves > 0 && !state.over) {
    const ok = await WebApp.showConfirm('放弃这一局,开始新游戏?').catch(() => window.confirm('放弃这一局,开始新游戏?'))
    if (!ok) return
  }
  restart()
})
$('about-btn').addEventListener('click', () => { playSfx('tap'); showAbout() })
WebApp.SettingsButton.show().onClick(() => { playSfx('tap'); showAbout() })

// 弹层里的按钮(新游戏 / 继续玩 / 知道了…)都补一声轻反馈;游戏动作有自己的音
document.addEventListener('click', (e) => {
  if ((e.target as HTMLElement | null)?.closest?.('#overlay button')) playSfx('tap', { gain: 0.8 })
}, true)


// ---------------------------------------------------------------- 存档(沿用 1.0 的云/本机格式,升级不丢档)

function writeLocal(): void {
  local.setItem(cacheKeyName, JSON.stringify({ state: save(state), best, at: savedAt }))
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
  cloud.setItem('state', payload).catch(() => undefined)
  cloud.setItem('best', JSON.stringify(best)).catch(() => undefined)
}

async function restore(): Promise<void> {
  // ① 本机缓存秒开
  try {
    const cached = JSON.parse(local.getItem(cacheKeyName) || 'null')
    if (cached) {
      const s = load(JSON.stringify(cached.state))
      if (s) { state = s; savedAt = Number(cached.at) || 0 }
      if (cached.best?.v === 1) best = cached.best
    }
  } catch (_) { /* 没有缓存 */ }
  drawAll()
  // ② 云端更新的话(别的设备上接着玩过),换成云端的
  try {
    const r = await cloud.getItems(['state', 'best'])
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

for (let i = 0; i < SIZE * SIZE; i++) cellsEl.append(document.createElement('i'))
installSfxUnlock()
syncSound()
followTheme()
layout()
new ResizeObserver(layout).observe(tilesEl)
restore().finally(() => {
  WebApp.ready().catch(() => undefined)
  board.focus()
})
// 小游戏:全屏、锁竖屏、切后台立刻存档(superz.json 里 orientation 也写了 portrait)
hostGame(saveNow)
