// 扫雷引擎:和界面无关的纯函数。
//
// 三档:初级 9×9 10 颗雷、中级 16×16 40 颗、高级 16 列 × 30 行 99 颗(经典的 30×16 竖过来,竖屏放得下)。
// 第一下永远不是雷:雷在第一次翻开时才埋,避开点的那一格和它周围一圈(格子不够时只避开那一格),
//   所以第一下总能翻开一片;
// 翻到 0 自动往外翻(插了旗的不翻);翻到雷就输;不是雷的格子全翻开就赢(剩下的雷自动插上旗);
// 旗只能插在没翻开的格子上;在翻开的数字上快速翻开(界面上是双击):周围的旗数等于这个数字,
//   就把周围没插旗的格子都翻开 —— 旗插错了会翻到雷,和经典规则一样;
// 计时从第一次翻开算起,由界面把过去的毫秒数传进来(tickTime)。
// 埋雷用带种子的 PRNG,种子存在状态里:同一个种子、同一串操作,结果永远一样。
import { shuffle } from '../../shared/src/rand'

export type Level = 'easy' | 'medium' | 'hard'
export const LEVEL_KEYS: Level[] = ['easy', 'medium', 'hard']
export const LEVELS: Record<Level, { name: string; cols: number; rows: number; mines: number }> = {
  easy: { name: '初级', cols: 9, rows: 9, mines: 10 },
  medium: { name: '中级', cols: 16, rows: 16, mines: 40 },
  hard: { name: '高级', cols: 16, rows: 30, mines: 99 },
}

export type Status = 'ready' | 'playing' | 'won' | 'lost'

export interface State {
  level: Level
  cols: number
  rows: number
  mines: number
  /** 哪些格子是雷;第一次翻开之前全是 false */
  mine: boolean[]
  open: boolean[]
  flag: boolean[]
  status: Status
  /** PRNG 的当前状态 */
  seed: number
  /** 用了多少毫秒 */
  elapsed: number
  /** 踩到的那颗雷;没有是 -1 */
  boom: number
}

export interface Move {
  state: State
  /** 这一步新翻开的格子 */
  opened: number[]
}

export function newGame(level: Level, seed: number): State {
  const { cols, rows, mines } = LEVELS[level]
  const n = cols * rows
  return { level, cols, rows, mines, mine: new Array(n).fill(false), open: new Array(n).fill(false),
    flag: new Array(n).fill(false), status: 'ready', seed: seed >>> 0, elapsed: 0, boom: -1 }
}

/** 周围一圈(最多 8 格) */
export function neighbors(s: { cols: number; rows: number }, i: number): number[] {
  const r = Math.floor(i / s.cols)
  const c = i % s.cols
  const out: number[] = []
  for (let dr = -1; dr <= 1; dr++) {
    for (let dc = -1; dc <= 1; dc++) {
      if (!dr && !dc) continue
      const rr = r + dr
      const cc = c + dc
      if (rr >= 0 && rr < s.rows && cc >= 0 && cc < s.cols) out.push(rr * s.cols + cc)
    }
  }
  return out
}

/** 周围有几颗雷 */
export function count(s: State, i: number): number {
  return neighbors(s, i).filter((j) => s.mine[j]).length
}

export function flagsAround(s: State, i: number): number {
  return neighbors(s, i).filter((j) => s.flag[j]).length
}

/** 还剩几颗雷没插旗(可能是负数:旗插多了) */
export function remaining(s: State): number {
  return s.mines - s.flag.filter(Boolean).length
}

/** 第一次翻开时埋雷:避开 first 和它周围一圈 */
export function placeMines(s: State, first: number): State {
  const n = s.cols * s.rows
  const around = new Set([first, ...neighbors(s, first)])
  const avoid = n - around.size >= s.mines ? around : new Set([first])
  const spots: number[] = []
  for (let i = 0; i < n; i++) if (!avoid.has(i)) spots.push(i)
  const [picked, seed] = shuffle(spots, s.seed)
  const mine = new Array(n).fill(false)
  for (const i of picked.slice(0, s.mines)) mine[i] = true
  return { ...s, mine, seed }
}

/** 从 starts 开始翻:0 就往外扩;返回新翻开的格子。open 原地改(调用方传进来的是拷贝) */
function flood(s: State, open: boolean[], starts: number[]): number[] {
  const opened: number[] = []
  const stack = starts.slice()
  while (stack.length) {
    const i = stack.pop() as number
    if (open[i] || s.flag[i] || s.mine[i]) continue
    open[i] = true
    opened.push(i)
    if (count(s, i) === 0) for (const j of neighbors(s, i)) if (!open[j]) stack.push(j)
  }
  return opened
}

function finishIfWon(s: State): State {
  const safe = s.cols * s.rows - s.mines
  if (s.open.filter(Boolean).length < safe) return s
  return { ...s, status: 'won', flag: s.mine.slice() }
}

function lose(s: State, open: boolean[], at: number): State {
  const o = open.slice()
  o[at] = true
  return { ...s, open: o, status: 'lost', boom: at }
}

/** 翻开一格。插了旗的、已经翻开的不动 */
export function reveal(s: State, i: number): Move {
  if (s.status === 'won' || s.status === 'lost' || s.open[i] || s.flag[i]) return { state: s, opened: [] }
  let st = s
  if (st.status === 'ready') st = { ...placeMines(st, i), status: 'playing' }
  if (st.mine[i]) return { state: lose(st, st.open, i), opened: [i] }
  const open = st.open.slice()
  const opened = flood(st, open, [i])
  return { state: finishIfWon({ ...st, open }), opened }
}

/** 插旗 / 拔旗(只能插在没翻开的格子上;结束了不能动) */
export function toggleFlag(s: State, i: number): State {
  if (s.status === 'won' || s.status === 'lost' || s.open[i]) return s
  const flag = s.flag.slice()
  flag[i] = !flag[i]
  return { ...s, flag }
}

/** 这个数字周围的旗够了吗(可以快速翻开) */
export function canChord(s: State, i: number): boolean {
  if (s.status !== 'playing' || !s.open[i]) return false
  const n = count(s, i)
  if (!n || flagsAround(s, i) !== n) return false
  return neighbors(s, i).some((j) => !s.open[j] && !s.flag[j])
}

/** 快速翻开:周围旗数等于数字时,把周围没插旗的都翻开。旗插错了就踩雷 */
export function chord(s: State, i: number): Move {
  if (!canChord(s, i)) return { state: s, opened: [] }
  const targets = neighbors(s, i).filter((j) => !s.open[j] && !s.flag[j])
  const hit = targets.find((j) => s.mine[j])
  if (hit !== undefined) return { state: lose(s, s.open, hit), opened: [hit] }
  const open = s.open.slice()
  const opened = flood(s, open, targets)
  return { state: finishIfWon({ ...s, open }), opened }
}

/** 时间过去 dt 毫秒(只在进行中计时) */
export function tickTime(s: State, dt: number): State {
  if (s.status !== 'playing' || dt <= 0) return s
  return { ...s, elapsed: Math.min(s.elapsed + dt, 999 * 60 * 1000) }
}

/** 输了之后要显示的:插错的旗(那一格其实不是雷) */
export function wrongFlags(s: State): number[] {
  const out: number[] = []
  if (s.status !== 'lost') return out
  s.flag.forEach((f, i) => { if (f && !s.mine[i]) out.push(i) })
  return out
}

// ---------------------------------------------------------------- 存档

export interface Saved {
  v: 1; level: Level; mine: string; cells: string; status: Status; seed: number; elapsed: number; boom: number
}
export interface LevelBest { time: number; wins: number; games: number }
export type Best = { v: 1 } & Record<Level, LevelBest>
export const EMPTY_BEST: Best = { v: 1, easy: { time: 0, wins: 0, games: 0 },
  medium: { time: 0, wins: 0, games: 0 }, hard: { time: 0, wins: 0, games: 0 } }

/** 每格一个字符:0 没翻开、1 翻开、2 插旗 */
export function save(s: State): Saved {
  return { v: 1, level: s.level, mine: s.mine.map((m) => (m ? '1' : '0')).join(''),
    cells: s.open.map((o, i) => (o ? '1' : s.flag[i] ? '2' : '0')).join(''), status: s.status, seed: s.seed,
    elapsed: Math.round(s.elapsed), boom: s.boom }
}

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v)

/** 读档。格子数、雷数、状态对不上的一律当坏档(返回 null) */
export function load(raw: unknown): State | null {
  const o = raw as Saved | null
  if (!o || typeof o !== 'object' || o.v !== 1 || LEVEL_KEYS.indexOf(o.level) < 0) return null
  const { cols, rows, mines } = LEVELS[o.level]
  const n = cols * rows
  if (typeof o.mine !== 'string' || typeof o.cells !== 'string' || o.mine.length !== n || o.cells.length !== n) return null
  if (!/^[01]*$/.test(o.mine) || !/^[012]*$/.test(o.cells)) return null
  if (['ready', 'playing', 'won', 'lost'].indexOf(o.status) < 0) return null
  const mine = o.mine.split('').map((c) => c === '1')
  const open = o.cells.split('').map((c) => c === '1')
  const flag = o.cells.split('').map((c) => c === '2')
  const placed = mine.filter(Boolean).length
  if (o.status === 'ready' ? placed !== 0 || open.some(Boolean) : placed !== mines) return null
  const boom = isInt(o.boom) && o.boom >= 0 && o.boom < n && mine[o.boom] ? o.boom : -1
  // 翻开的格子不能是雷(输了的那一颗除外)
  if (open.some((op, i) => op && mine[i] && !(o.status === 'lost' && i === boom))) return null
  if (o.status === 'lost' && boom < 0) return null
  const s: State = { level: o.level, cols, rows, mines, mine, open, flag, status: o.status, seed: Number(o.seed) >>> 0,
    elapsed: isInt(o.elapsed) && o.elapsed > 0 ? o.elapsed : 0, boom: o.status === 'lost' ? boom : -1 }
  if (o.status === 'won' && open.filter(Boolean).length !== n - mines) return null
  if (o.status === 'playing' && finishIfWon(s).status === 'won') return null
  return s
}

function levelBest(raw: unknown): LevelBest {
  const o = (raw || {}) as LevelBest
  const n = (v: unknown) => (isInt(v) && v > 0 ? v : 0)
  return { time: n(o.time), wins: n(o.wins), games: n(o.games) }
}

export function loadBest(raw: unknown): Best | null {
  const o = raw as Best | null
  if (!o || typeof o !== 'object' || o.v !== 1) return null
  return { v: 1, easy: levelBest(o.easy), medium: levelBest(o.medium), hard: levelBest(o.hard) }
}

export function mergeBest(a: Best, b: Best): Best {
  const m = (x: LevelBest, y: LevelBest): LevelBest => ({
    time: x.time && y.time ? Math.min(x.time, y.time) : x.time || y.time,
    wins: Math.max(x.wins, y.wins), games: Math.max(x.games, y.games),
  })
  return { v: 1, easy: m(a.easy, b.easy), medium: m(a.medium, b.medium), hard: m(a.hard, b.hard) }
}

/** 一局结束(或者玩到一半放弃)时记一笔;赢了看是不是最快 */
export function updateBest(b: Best, s: State): Best {
  const cur = b[s.level]
  const won = s.status === 'won'
  const took = Math.max(1, Math.round(s.elapsed)) // 0 表示「还没有纪录」,赢了至少记 1 毫秒
  const time = won ? (cur.time ? Math.min(cur.time, took) : took) : cur.time
  return { ...b, [s.level]: { time, wins: cur.wins + (won ? 1 : 0), games: cur.games + 1 } }
}
