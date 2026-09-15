// 方块消除引擎:和界面无关的纯函数。
//
// 规则:10 列 × 20 行;七种由 4 格组成的方块(代号 I O T S Z J L,只在代码里用),按「七个一袋」发:
// 每一袋七种各一个、顺序打乱 —— 不会连着很久等不来长条,也不会连着来一串同样的;
// 可以左右移、旋转(贴着墙转不开时试着挪一两格,叫「踢墙」)、软降(往下挪一格,得 1 分)、
// 硬降(直接落到底,每格得 2 分);落地后还有 0.5 秒可以挪,挪动或旋转会重新计时,一块最多重新计时 15 次;
// 满行消除:一次消 1 / 2 / 3 / 4 行得 100 / 300 / 500 / 800 × 等级;每消 10 行升一级,越往后落得越快;
// 新方块出不来、或者方块停在了顶上外面,就结束。
// 时间由界面传进来(tick(状态, 毫秒)),引擎里没有定时器,测试能一帧一帧地走;
// 发方块用带种子的 PRNG,种子存在状态里 —— 同一个种子、同一串操作,结果永远一样。
import { shuffle } from '../../shared/src/rand'

export const COLS = 10
export const ROWS = 20
/** 落地后还能挪的时间 */
export const LOCK_MS = 500
/** 一块落地后最多重新计时几次(防止一直转着不落) */
export const MAX_RESETS = 15
export const KINDS = ['I', 'O', 'T', 'S', 'Z', 'J', 'L'] as const
/** 一次消几行的基础分(再乘等级) */
export const LINE_SCORES = [0, 100, 300, 500, 800]

type Cell = [number, number] // [x, y]

// 每种方块在自己的方框里的样子(第 0 个朝向);其余朝向按方框顺时针转出来
const BASE: Array<{ box: number; cells: Cell[] }> = [
  { box: 4, cells: [[0, 1], [1, 1], [2, 1], [3, 1]] }, // I
  { box: 2, cells: [[0, 0], [1, 0], [0, 1], [1, 1]] }, // O
  { box: 3, cells: [[1, 0], [0, 1], [1, 1], [2, 1]] }, // T
  { box: 3, cells: [[1, 0], [2, 0], [0, 1], [1, 1]] }, // S
  { box: 3, cells: [[0, 0], [1, 0], [1, 1], [2, 1]] }, // Z
  { box: 3, cells: [[0, 0], [0, 1], [1, 1], [2, 1]] }, // J
  { box: 3, cells: [[2, 0], [0, 1], [1, 1], [2, 1]] }, // L
]

/** SHAPES[种类][朝向] = 4 个格子 */
export const SHAPES: Cell[][][] = BASE.map(({ box, cells }) => {
  const out: Cell[][] = [cells]
  for (let r = 1; r < 4; r++) out.push(out[r - 1].map(([x, y]) => [box - 1 - y, x] as Cell))
  return out
})

/** 转不开时依次试的挪法 [dx, dy](dy 为负是往上挪) */
const KICKS: Cell[] = [[0, 0], [-1, 0], [1, 0], [0, -1], [-1, -1], [1, -1], [-2, 0], [2, 0]]

export interface Piece {
  /** 种类 0–6 */
  k: number
  /** 朝向 0–3(顺时针) */
  r: number
  x: number
  y: number
}

export interface State {
  /** ROWS × COLS,0 是空,1–7 是方块种类 + 1 */
  cells: number[]
  /** 正在落的;结束了是 null */
  piece: Piece | null
  next: number
  /** 这一袋里还没发的 */
  bag: number[]
  /** PRNG 的当前状态 */
  seed: number
  score: number
  lines: number
  level: number
  /** 自然下落累计的毫秒 */
  fall: number
  /** 落地后累计的毫秒 */
  lock: number
  /** 这一块落地后重新计时的次数 */
  resets: number
  /** 这一块到过的最低一行(落到新低就把 resets 清零) */
  lowest: number
  over: boolean
}

export interface Result {
  state: State
  /** 这一步固定了一块 */
  locked: boolean
  /** 消掉的行(消之前的行号) */
  cleared: number[]
  /** 这一步得的分 */
  gained: number
  /** 消行之前的棋盘(界面据此让消掉的行闪一下) */
  board: number[] | null
}

/** 自然下落一格的毫秒数:第 1 级 1 秒,每升一级快 15%,最快 50ms */
export function gravity(level: number): number {
  return Math.max(50, Math.round(1000 * Math.pow(0.85, Math.max(0, level - 1))))
}

export function levelOf(lines: number): number {
  return 1 + Math.floor(lines / 10)
}

export function cellsOf(p: Piece): Cell[] {
  return SHAPES[p.k][p.r].map(([x, y]) => [p.x + x, p.y + y] as Cell)
}

/** 顶上外面还有两行看不见的缓冲:新方块在那儿转身、踢墙;停在那儿就算到顶了 */
export const HIDDEN = 2

/** 放得下吗:不出左右和底边、不压着已有的格子;顶上外面最多探出 HIDDEN 行 */
export function fits(cells: number[], p: Piece): boolean {
  for (const [x, y] of cellsOf(p)) {
    if (x < 0 || x >= COLS || y >= ROWS || y < -HIDDEN) return false
    if (y >= 0 && cells[y * COLS + x]) return false
  }
  return true
}

export function grounded(cells: number[], p: Piece): boolean {
  return !fits(cells, { ...p, y: p.y + 1 })
}

/** 直接落下去会停在哪一行 */
export function dropY(cells: number[], p: Piece): number {
  let y = p.y
  while (fits(cells, { ...p, y: y + 1 })) y++
  return y
}

/** 新方块出现的位置:横着居中,最上面一格贴着顶 */
export function spawn(k: number): Piece {
  const top = Math.min(...SHAPES[k][0].map(([, y]) => y))
  return { k, r: 0, x: k === 1 ? 4 : 3, y: -top }
}

/** 从袋子里拿下一个;袋子空了洗一袋新的 */
function draw(bag: number[], seed: number): { k: number; bag: number[]; seed: number } {
  let b = bag
  let s = seed
  if (!b.length) [b, s] = shuffle([0, 1, 2, 3, 4, 5, 6], s)
  return { k: b[0], bag: b.slice(1), seed: s }
}

function none(state: State): Result {
  return { state, locked: false, cleared: [], gained: 0, board: null }
}

export function newGame(seed: number): State {
  const a = draw([], seed >>> 0)
  const b = draw(a.bag, a.seed)
  return {
    cells: new Array(COLS * ROWS).fill(0), piece: spawn(a.k), next: b.k, bag: b.bag, seed: b.seed,
    score: 0, lines: 0, level: 1, fall: 0, lock: 0, resets: 0, lowest: spawn(a.k).y, over: false,
  }
}

/** 挪动或旋转成功之后:落地的话重新计时(有次数上限),到了新低把次数清零 */
function settle(s: State, p: Piece): State {
  let { lock, resets, lowest } = s
  if (p.y > lowest) {
    lowest = p.y
    resets = 0
  }
  if (grounded(s.cells, p) && resets < MAX_RESETS) {
    lock = 0
    resets++
  }
  return { ...s, piece: p, lock, resets, lowest }
}

/** 左右挪一格(dx = -1 / 1)。挪不动返回原状态 */
export function move(s: State, dx: number): State {
  if (s.over || !s.piece) return s
  const p = { ...s.piece, x: s.piece.x + dx }
  return fits(s.cells, p) ? settle(s, p) : s
}

/** 旋转(dir = 1 顺时针,-1 逆时针)。原地转不开就按 KICKS 试着挪 */
export function rotate(s: State, dir: 1 | -1): State {
  if (s.over || !s.piece) return s
  if (s.piece.k === 1) return s // 正方形转了也一样
  const r = (s.piece.r + dir + 4) % 4
  for (const [dx, dy] of KICKS) {
    const p = { ...s.piece, r, x: s.piece.x + dx, y: s.piece.y + dy }
    if (fits(s.cells, p)) return settle(s, p)
  }
  return s
}

/** 软降:往下挪一格,得 1 分。到底了就不动(等落地计时) */
export function softDrop(s: State): State {
  if (s.over || !s.piece) return s
  const p = { ...s.piece, y: s.piece.y + 1 }
  if (!fits(s.cells, p)) return s
  return { ...settle(s, p), score: s.score + 1, fall: 0 }
}

/** 硬降:直接落到底并固定,每格得 2 分 */
export function hardDrop(s: State): Result {
  if (s.over || !s.piece) return none(s)
  const y = dropY(s.cells, s.piece)
  const bonus = 2 * (y - s.piece.y)
  const r = lockPiece({ ...s, piece: { ...s.piece, y }, score: s.score + bonus })
  return { ...r, gained: r.gained + bonus }
}

/** 时间过去 dt 毫秒:自然下落;落地够久就固定 */
export function tick(s: State, dt: number): Result {
  if (s.over || !s.piece) return none(s)
  const g = gravity(s.level)
  let p = s.piece
  let fall = s.fall + dt
  let st = s
  while (fall >= g) {
    const down = { ...p, y: p.y + 1 }
    if (!fits(s.cells, down)) {
      fall = 0 // 落地了,自然下落不再攒着
      break
    }
    p = down
    fall -= g
    if (p.y > st.lowest) st = { ...st, lowest: p.y, resets: 0 }
  }
  st = { ...st, piece: p, fall }
  if (!grounded(s.cells, p)) return none({ ...st, lock: 0 })
  const lock = st.lock + dt
  if (lock >= LOCK_MS) return lockPiece({ ...st, lock: 0 })
  return none({ ...st, lock })
}

/** 固定当前这一块:写进棋盘、消满行、算分升级、发下一块 */
function lockPiece(s: State): Result {
  const p = s.piece as Piece
  // 连同顶上的缓冲行一起算:探出去的格子在消行后会跟着往下掉,掉不回棋盘里才算到顶
  const ext = new Array(HIDDEN * COLS).fill(0).concat(s.cells)
  for (const [x, y] of cellsOf(p)) ext[(y + HIDDEN) * COLS + x] = p.k + 1
  const board = ext.slice(HIDDEN * COLS)
  const cleared: number[] = []
  for (let y = 0; y < ROWS; y++) {
    if (board.slice(y * COLS, (y + 1) * COLS).every((v) => v)) cleared.push(y)
  }
  let rows = ext
  if (cleared.length) {
    rows = []
    for (let y = -HIDDEN; y < ROWS; y++) {
      if (cleared.indexOf(y) < 0) rows.push(...ext.slice((y + HIDDEN) * COLS, (y + HIDDEN + 1) * COLS))
    }
    rows = new Array(cleared.length * COLS).fill(0).concat(rows)
  }
  const toppedOut = rows.slice(0, HIDDEN * COLS).some((v) => v)
  const rest = rows.slice(HIDDEN * COLS)
  const gained = LINE_SCORES[cleared.length] * s.level
  const lines = s.lines + cleared.length
  const base: State = { ...s, cells: rest, score: s.score + gained, lines, level: levelOf(lines),
    fall: 0, lock: 0, resets: 0 }
  const flash = cleared.length ? board : null
  if (toppedOut) {
    return { state: { ...base, piece: null, over: true }, locked: true, cleared, gained, board: flash }
  }
  const d = draw(s.bag, s.seed)
  const piece = spawn(s.next)
  const next: State = { ...base, piece, next: d.k, bag: d.bag, seed: d.seed, lowest: piece.y }
  if (!fits(rest, piece)) {
    return { state: { ...next, piece: null, over: true }, locked: true, cleared, gained, board: flash }
  }
  return { state: next, locked: true, cleared, gained, board: flash }
}

// ---------------------------------------------------------------- 存档

export interface Saved {
  v: 1; cells: string; piece: Piece | null; next: number; bag: number[]; seed: number
  score: number; lines: number; over: boolean
}
export interface Best { v: 1; score: number; lines: number; level: number; games: number }
export const EMPTY_BEST: Best = { v: 1, score: 0, lines: 0, level: 0, games: 0 }

export function save(s: State): Saved {
  return { v: 1, cells: s.cells.join(''), piece: s.piece ? { ...s.piece } : null, next: s.next, bag: s.bag.slice(),
    seed: s.seed, score: s.score, lines: s.lines, over: s.over }
}

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v)
const isKind = (v: unknown): v is number => isInt(v) && v >= 0 && v < 7

/** 读档。格子、方块、袋子有一样不对就当坏档(返回 null) */
export function load(raw: unknown): State | null {
  const o = raw as Saved | null
  if (!o || typeof o !== 'object' || o.v !== 1) return null
  if (typeof o.cells !== 'string' || !/^[0-7]*$/.test(o.cells) || o.cells.length !== COLS * ROWS) return null
  const cells = o.cells.split('').map(Number)
  if (!isKind(o.next) || !Array.isArray(o.bag) || o.bag.length > 6 || !o.bag.every(isKind)) return null
  if (new Set(o.bag).size !== o.bag.length) return null
  const over = !!o.over
  let piece: Piece | null = null
  if (o.piece) {
    const p = o.piece
    if (!isKind(p.k) || !isInt(p.r) || p.r < 0 || p.r > 3 || !isInt(p.x) || !isInt(p.y)) return null
    piece = { k: p.k, r: p.r, x: p.x, y: p.y }
    if (!fits(cells, piece)) return null
  }
  if (!over && !piece) return null
  const lines = isInt(o.lines) && o.lines >= 0 ? o.lines : 0
  return { cells, piece: over ? null : piece, next: o.next, bag: o.bag.slice(), seed: Number(o.seed) >>> 0,
    score: isInt(o.score) && o.score >= 0 ? o.score : 0, lines, level: levelOf(lines), fall: 0, lock: 0, resets: 0,
    lowest: piece ? piece.y : 0, over }
}

export function loadBest(raw: unknown): Best | null {
  const o = raw as Best | null
  if (!o || typeof o !== 'object' || o.v !== 1) return null
  const n = (v: unknown) => (isInt(v) && v > 0 ? v : 0)
  return { v: 1, score: n(o.score), lines: n(o.lines), level: n(o.level), games: n(o.games) }
}

export function mergeBest(a: Best, b: Best): Best {
  return { v: 1, score: Math.max(a.score, b.score), lines: Math.max(a.lines, b.lines),
    level: Math.max(a.level, b.level), games: Math.max(a.games, b.games) }
}

/** 最好成绩;finished 表示这一局算完了 */
export function updateBest(b: Best, s: State, finished: boolean): Best {
  return { v: 1, score: Math.max(b.score, s.score), lines: Math.max(b.lines, s.lines),
    level: Math.max(b.level, s.level), games: b.games + (finished ? 1 : 0) }
}
