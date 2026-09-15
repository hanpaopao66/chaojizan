// 五子棋的界面:canvas 画棋盘;触屏「点一下选点、再点一次落子」(交叉点只有二十几像素宽,防手滑),
// 鼠标点了就下,键盘方向键挪、回车落子。规则和电脑的下法全在 engine.ts;这里只管输入、画、存档和宿主能力。
import '../../shared/src/base.css'
import './style.css'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import { $, Overlay, WebApp, bullets, button, cacheKey, cloud, el, followTheme, hostGame, local, row } from '../../shared/src/ui'
import {
  Best, Color, EMPTY_BEST, LEVELS, LEVEL_KEYS, Level, N, State, aiMove, canUndo, load, loadBest, mergeBest, newGame,
  play, revertBest, rowCol, save, turn, undo, updateBest,
} from './engine'
import { DARK, LIGHT, Palette } from './palette'

const STARS = [3 * N + 3, 3 * N + 11, 7 * N + 7, 11 * N + 3, 11 * N + 11]

const stage = $('stage')
const canvas = $<HTMLCanvasElement>('board')
const ctx = canvas.getContext('2d') as CanvasRenderingContext2D
const statusEl = $('status')
const whoStone = $('who-stone')
const whoText = $('who-text')
const undoBtn = $<HTMLButtonElement>('undo')
const hintEl = $('hint')
const live = $('live')
const overlay = new Overlay($('overlay'), () => canvas.focus())

const slot = new SaveSlot<State, Best>({
  cacheKey: cacheKey('gomoku'), cloud, local, loadState: load, saveState: save, loadBest, mergeBest,
  emptyBest: EMPTY_BEST,
})

let state: State = newGame(1, 'medium', freshSeed())
let best: Best = EMPTY_BEST
let pal: Palette = LIGHT
let size = 300
/** 触屏选中、还没落的点;鼠标悬停的点;键盘光标 —— 都画成半透明的棋子 */
let preview = -1
let thinking = false
/** 每开一局加一,电脑算完发现局已经换了就不落子 */
let generation = 0
let lastPointer = 'mouse'
let hadSave = false

/** 交叉点间距;最外一圈线离棋盘边 0.8 格,边上的棋子不贴边 */
const gap = () => size / (N - 1 + 1.6)
const pad = () => gap() * 0.8
const colorName = (c: Color) => (c === 1 ? '黑' : '白')
const yourTurn = () => !state.winner && !thinking && turn(state) === state.human

// ---------------------------------------------------------------- 画

function layout(): void {
  const w = stage.clientWidth
  const h = stage.clientHeight
  if (!w || !h) return
  size = Math.max(150, Math.floor(Math.min(w, h)))
  const dpr = Math.min(3, window.devicePixelRatio || 1)
  canvas.style.width = `${size}px`
  canvas.style.height = `${size}px`
  canvas.width = Math.round(size * dpr)
  canvas.height = Math.round(size * dpr)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  draw()
}

function xy(i: number): [number, number] {
  const [r, c] = rowCol(i)
  return [pad() + c * gap(), pad() + r * gap()]
}

function stone(i: number, color: Color, alpha = 1): void {
  const [x, y] = xy(i)
  const rad = gap() * 0.45
  ctx.globalAlpha = alpha
  const g = ctx.createRadialGradient(x - rad * 0.35, y - rad * 0.35, rad * 0.1, x, y, rad)
  if (color === 1) {
    g.addColorStop(0, '#55534D')
    g.addColorStop(1, pal.black)
  } else {
    g.addColorStop(0, '#FFFFFF')
    g.addColorStop(1, pal.white)
  }
  ctx.fillStyle = g
  ctx.beginPath()
  ctx.arc(x, y, rad, 0, Math.PI * 2)
  ctx.fill()
  ctx.lineWidth = Math.max(1, gap() * 0.05)
  ctx.strokeStyle = color === 1 ? pal.blackEdge : pal.whiteEdge
  ctx.stroke()
  ctx.globalAlpha = 1
}

function draw(): void {
  const g = gap()
  ctx.fillStyle = pal.board
  ctx.fillRect(0, 0, size, size)
  ctx.strokeStyle = pal.line
  ctx.lineWidth = 1
  ctx.beginPath()
  const lo = pad()
  const hi = pad() + (N - 1) * g
  for (let k = 0; k < N; k++) {
    const p = Math.round(pad() + k * g) + 0.5
    ctx.moveTo(lo, p)
    ctx.lineTo(hi, p)
    ctx.moveTo(p, lo)
    ctx.lineTo(p, hi)
  }
  ctx.stroke()
  ctx.fillStyle = pal.line
  for (const s of STARS) {
    const [x, y] = xy(s)
    ctx.beginPath()
    ctx.arc(x, y, Math.max(2, g * 0.1), 0, Math.PI * 2)
    ctx.fill()
  }
  state.board.forEach((v, i) => { if (v) stone(i, v as Color) })
  // 连成五子的圈
  if (state.line.length) {
    ctx.strokeStyle = pal.win
    ctx.lineWidth = Math.max(2, g * 0.09)
    for (const i of state.line) {
      const [x, y] = xy(i)
      ctx.beginPath()
      ctx.arc(x, y, g * 0.47, 0, Math.PI * 2)
      ctx.stroke()
    }
  }
  // 最后一手的小红点
  const last = state.moves[state.moves.length - 1]
  if (last !== undefined) {
    const [x, y] = xy(last)
    ctx.fillStyle = pal.mark
    ctx.beginPath()
    ctx.arc(x, y, Math.max(2.5, g * 0.12), 0, Math.PI * 2)
    ctx.fill()
  }
  // 选中 / 悬停 / 键盘光标:半透明的一颗,外面一个框
  if (preview >= 0 && !state.board[preview] && yourTurn()) {
    stone(preview, state.human, 0.55)
    const [x, y] = xy(preview)
    ctx.strokeStyle = pal.win
    ctx.lineWidth = 2
    ctx.strokeRect(x - g / 2 + 1, y - g / 2 + 1, g - 2, g - 2)
  }
}

function syncUi(): void {
  whoStone.className = `stone ${state.human === 1 ? 'b' : 'w'}`
  whoText.textContent = `你执${colorName(state.human)}${state.human === 1 ? '先手' : '后手'} · ${LEVELS[state.level]}`
  statusEl.classList.toggle('think', thinking)
  statusEl.textContent = state.winner === 3 ? '和棋' : state.winner === state.human ? '你赢了'
    : state.winner ? '电脑赢了' : thinking ? '电脑在想…' : '轮到你'
  undoBtn.disabled = thinking || !canUndo(state)
  hintEl.textContent = state.winner ? '' : lastPointer === 'mouse' ? '点交叉点落子;方向键挪、回车落子也行'
    : preview >= 0 ? '再点一次这里落子,点别处换个点' : '点一下选点,再点一次落子'
  const [r, c] = preview >= 0 ? rowCol(preview) : [-1, -1]
  canvas.setAttribute('aria-label', `五子棋棋盘,已下 ${state.moves.length} 手,${statusEl.textContent}${
    preview >= 0 ? `,选中第 ${r + 1} 行第 ${c + 1} 列` : ''}`)
}

// ---------------------------------------------------------------- 走棋

function say(color: Color, i: number): void {
  const [r, c] = rowCol(i)
  live.textContent = `${color === state.human ? '你' : '电脑'}下在第 ${r + 1} 行第 ${c + 1} 列`
}

function place(i: number): void {
  if (!yourTurn() || state.board[i] || overlay.open) return
  const next = play(state, i)
  if (next === state) return
  state = next
  preview = -1
  WebApp.HapticFeedback.selectionChanged()
  say(state.human, i)
  slot.change(state)
  draw()
  if (state.winner) finish()
  else runAi()
  syncUi()
}

/**
 * 电脑走一手。先把「电脑在想…」显示出来,隔一小会儿再算(算在同一个线程上,最多几百毫秒)。
 * 用 setTimeout 不用 requestAnimationFrame:页面在后台时后者根本不触发,电脑就一直「在想」
 */
function runAi(): void {
  if (state.winner || turn(state) === state.human) return
  thinking = true
  syncUi()
  const gen = generation
  setTimeout(() => {
    if (gen !== generation) return
    const next = aiMove(state)
    thinking = false
    if (next !== state) {
      state = next
      say((3 - state.human) as Color, state.moves[state.moves.length - 1])
      slot.change(state)
    }
    draw()
    if (state.winner) finish()
    syncUi()
  }, 280)
}

function finish(): void {
  best = updateBest(best, state)
  slot.setBest(best)
  void slot.flush()
  const won = state.winner === state.human
  WebApp.HapticFeedback.notificationOccurred(won ? 'success' : state.winner === 3 ? 'warning' : 'error')
  live.textContent = won ? '你赢了' : state.winner === 3 ? '下满了,和棋' : '电脑赢了'
  setTimeout(showEnd, 700)
}

function doUndo(): void {
  if (thinking || !canUndo(state)) return
  if (state.winner) best = revertBest(best, state) // 输了、和了又悔棋:刚记的那一笔撤回
  slot.setBest(best)
  state = undo(state)
  overlay.hide()
  preview = -1
  live.textContent = '悔了一步'
  slot.change(state)
  draw()
  syncUi()
}

function startGame(human: Color, level: Level): void {
  overlay.hide()
  generation++
  thinking = false
  state = newGame(human, level, freshSeed())
  preview = -1
  slot.change(state)
  void slot.flush()
  draw()
  syncUi()
  runAi() // 执白的话电脑先下
  canvas.focus()
}

// ---------------------------------------------------------------- 输入

/** 点到的最近的交叉点(棋盘边上那一圈留白也算最外一圈) */
function pointAt(e: PointerEvent): number {
  const rect = canvas.getBoundingClientRect()
  const scale = size / rect.width
  const c = Math.round(((e.clientX - rect.left) * scale - pad()) / gap())
  const r = Math.round(((e.clientY - rect.top) * scale - pad()) / gap())
  return r >= 0 && r < N && c >= 0 && c < N ? r * N + c : -1
}

canvas.addEventListener('pointermove', (e) => {
  if (e.pointerType !== 'mouse') return
  lastPointer = 'mouse'
  const i = pointAt(e)
  const p = i >= 0 && !state.board[i] ? i : -1
  if (p !== preview) {
    preview = p
    draw()
  }
})
canvas.addEventListener('pointerleave', (e) => {
  if (e.pointerType === 'mouse' && preview >= 0) {
    preview = -1
    draw()
  }
})
canvas.addEventListener('pointerup', (e) => {
  const was = lastPointer
  lastPointer = e.pointerType
  const i = pointAt(e)
  if (i < 0 || !yourTurn() || state.board[i]) return
  if (e.pointerType === 'mouse') place(i)
  else if (preview === i && was !== 'mouse') place(i) // 触屏:点同一个点第二次才落子
  else {
    preview = i
    WebApp.HapticFeedback.selectionChanged()
    draw()
    syncUi()
  }
})

canvas.addEventListener('keydown', (e) => {
  if (overlay.open || e.metaKey || e.ctrlKey || e.altKey) return
  const moves: Record<string, [number, number]> = {
    ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
    Up: [-1, 0], Down: [1, 0], Left: [0, -1], Right: [0, 1],
  }
  const m = moves[e.key]
  if (m) {
    e.preventDefault()
    lastPointer = 'mouse'
    const from = preview >= 0 ? preview : state.moves.length ? state.moves[state.moves.length - 1] : 7 * N + 7
    const [r, c] = rowCol(from)
    const rr = Math.min(N - 1, Math.max(0, r + (preview >= 0 ? m[0] : 0)))
    const cc = Math.min(N - 1, Math.max(0, c + (preview >= 0 ? m[1] : 0)))
    preview = rr * N + cc
    draw()
    syncUi()
  } else if ((e.key === 'Enter' || e.key === ' ') && preview >= 0) {
    e.preventDefault()
    place(preview)
  }
})

undoBtn.addEventListener('click', doUndo)
$('new').addEventListener('click', () => showSetup())
$('about-btn').addEventListener('click', showAbout)
WebApp.SettingsButton.show().onClick(showAbout)

// ---------------------------------------------------------------- 弹层

/** 一组二选一 / 三选一的按钮 */
function choice<T extends string | number>(title: string, options: Array<[T, string]>, current: T,
  onPick: (v: T) => void): HTMLElement {
  const box = el('div', '', 'choice')
  box.append(el('h3', title))
  const seg = el('div', '', 'seg')
  seg.setAttribute('role', 'radiogroup')
  seg.setAttribute('aria-label', title)
  const buttons = options.map(([v, label]) => {
    const b = button(label, () => {
      buttons.forEach((x, k) => x.setAttribute('aria-checked', String(options[k][0] === v)))
      onPick(v)
    })
    b.setAttribute('role', 'radio')
    b.setAttribute('aria-checked', String(v === current))
    return b
  })
  seg.append(...buttons)
  box.append(seg)
  return box
}

function showSetup(first = false): void {
  let human: Color = state.human
  let level: Level = state.level
  const playing = !first && !state.winner && state.moves.length > 0
  overlay.show((p) => {
    p.append(el('h2', first ? '下一盘五子棋' : '新的一局'),
      choice<Color>('先后手', [[1, '执黑先手'], [2, '执白后手']], human, (v) => { human = v }),
      choice<Level>('难度', LEVEL_KEYS.map((k) => [k, LEVELS[k]] as [Level, string]), level, (v) => { level = v }))
    if (playing) p.append(el('p', '正在下的这一局会放弃,不记输赢。', 'note'))
    const buttons = [button('开始', () => startGame(human, level), 'primary')]
    if (!first) buttons.unshift(button('取消', () => overlay.hide()))
    p.append(row(...buttons))
  }, first ? {} : { onDismiss: () => undefined })
}

function showEnd(): void {
  if (!state.winner) return
  const r = best[state.level]
  const won = state.winner === state.human
  overlay.show((p) => {
    p.append(el('h2', state.winner === 3 ? '和棋' : won ? '你赢了' : '电脑赢了'),
      el('p', `${LEVELS[state.level]} · 赢 ${r.win} 输 ${r.lose} 和 ${r.draw}`))
    const buttons = [button('换设置', () => showSetup()),
      button('再来一局', () => startGame(state.human, state.level), 'primary')]
    if (canUndo(state)) buttons.unshift(button('悔一步', doUndo))
    p.append(row(...buttons))
  }, { onDismiss: () => undefined })
}

function showAbout(): void {
  overlay.show((p) => {
    const stats = LEVEL_KEYS.map((k) => `${LEVELS[k]}:赢 ${best[k].win} 输 ${best[k].lose} 和 ${best[k].draw}`)
    p.append(el('h2', '关于五子棋'), bullets([
      '横、竖、斜任一方向连成五子就赢,不设禁手;黑先。开局可以选执黑先手还是执白后手,难度分简单、中等、困难。',
      '手机上点一下选点、再点一次落子(防手滑);电脑上点了就下,也可以用方向键挪、回车落子。',
      '悔棋一步:退回到你上一次落子之前;悔过之后要再下一子才能再悔。输了也能悔一步接着下,这一局就不算输。',
      '电脑按棋型打分(连五、活四、冲四、活三……),困难档还会往后看几手、算连续冲四。',
      '没有广告,没有内购,没有排行榜。',
      '前端游戏的输赢没法由服务器验证,所以战绩只存在你自己这里,不给别人看。',
      '每一手自动存档到超级赞云存储,关了再开、换设备都能接着下。',
      ...stats,
    ]), row(button('知道了', () => overlay.hide(), 'primary')))
  }, { cls: 'about', onDismiss: () => undefined })
}

// ---------------------------------------------------------------- 存档与启动

function adopt(s: State): void {
  generation++
  thinking = false
  state = s
  preview = -1
}

function applyTheme(): void {
  pal = document.documentElement.classList.contains('dark') ? DARK : LIGHT
  draw()
}

followTheme(applyTheme)
hadSave = slot.restoreLocal() && !!slot.state
if (hadSave && slot.state) state = slot.state
best = slot.best
layout()
syncUi()
new ResizeObserver(layout).observe(stage)
hostGame(() => { void slot.flush() })
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
    hadSave = true
    overlay.hide()
  } else if (r === 'cleared') {
    adopt(newGame(1, 'medium', freshSeed()))
    hadSave = false
  }
  draw()
  syncUi()
}).finally(() => {
  ready()
  if (!hadSave) showSetup(true) // 第一次打开:先选先后手和难度
  else if (state.winner) showEnd()
  else runAi() // 关的时候正轮到电脑:接着替它下
  canvas.focus()
})
