// 贪吃蛇引擎:和界面无关的纯函数。
//
// 规则:16 列 × 20 行;蛇开局 3 节、头朝上;吃到一个长一节、得 1 分;撞墙或咬到自己就结束;
// 格子被蛇占满(没地方放食物了)算赢。每走一格的间隔随长度慢慢变短(interval)。
// 转向排队:走一格之内最多记两次转向 —— 快速按「上、左」能在两格里拐过去;往反方向掉头不算数。
// 放食物用带种子的 PRNG,种子存在状态里:同一个种子、同一串操作,结果永远一样,关了再开也接得上。
import { randInt } from '../../shared/src/rand'

export const COLS = 16
export const ROWS = 20
export const START_LEN = 3

export type Dir = 'up' | 'down' | 'left' | 'right'
export const DIRS: Dir[] = ['up', 'down', 'left', 'right']
const DELTA: Record<Dir, [number, number]> = { up: [-1, 0], down: [1, 0], left: [0, -1], right: [0, 1] }
export const OPPOSITE: Record<Dir, Dir> = { up: 'down', down: 'up', left: 'right', right: 'left' }

export type Cause = '' | 'wall' | 'self' | 'full'

export interface State {
  cols: number
  rows: number
  /** 蛇身占的格子(下标 = 行 × 列数 + 列),头在前 */
  snake: number[]
  dir: Dir
  /** 还没走到的转向(最多 2 个)。不进存档 */
  queue: Dir[]
  /** 食物所在的格子;-1 表示格子满了 */
  food: number
  /** 吃到的个数 */
  score: number
  /** PRNG 的当前状态(不是初始种子) */
  seed: number
  steps: number
  over: boolean
  won: boolean
  /** 怎么结束的:撞墙、咬到自己、占满了 */
  cause: Cause
}

export interface StepResult {
  state: State
  ate: boolean
  died: boolean
}

/** 每走一格的毫秒数:180ms 起步,吃得越多越快,慢慢逼近 70ms */
export function interval(score: number): number {
  return Math.round(70 + 110 * Math.pow(0.97, Math.max(0, score)))
}

/** 在空格里随机放食物;没有空格返回 -1 */
export function placeFood(snake: number[], cols: number, rows: number, seed: number): [number, number] {
  const taken = new Uint8Array(cols * rows)
  for (const i of snake) taken[i] = 1
  const empty: number[] = []
  for (let i = 0; i < taken.length; i++) if (!taken[i]) empty.push(i)
  if (!empty.length) return [-1, seed]
  const [k, next] = randInt(seed, empty.length)
  return [empty[k], next]
}

export function newGame(seed: number, cols = COLS, rows = ROWS): State {
  const c = Math.floor(cols / 2)
  const r = Math.floor(rows / 2)
  const snake: number[] = []
  for (let k = 0; k < START_LEN; k++) snake.push((r + k) * cols + c)
  const [food, next] = placeFood(snake, cols, rows, seed >>> 0)
  return { cols, rows, snake, dir: 'up', queue: [], food, score: 0, seed: next, steps: 0,
    over: false, won: false, cause: '' }
}

/** 按了一个方向。和最后一个排着的方向相同或相反的不算;最多排两个 */
export function turn(s: State, d: Dir): State {
  if (s.over) return s
  const last = s.queue.length ? s.queue[s.queue.length - 1] : s.dir
  if (d === last || d === OPPOSITE[last] || s.queue.length >= 2) return s
  return { ...s, queue: [...s.queue, d] }
}

/** 走一格 */
export function step(s: State): StepResult {
  if (s.over) return { state: s, ate: false, died: false }
  const queue = s.queue.slice()
  const dir = queue.length ? (queue.shift() as Dir) : s.dir
  const head = s.snake[0]
  const [dr, dc] = DELTA[dir]
  const r = Math.floor(head / s.cols) + dr
  const c = (head % s.cols) + dc
  if (r < 0 || r >= s.rows || c < 0 || c >= s.cols) {
    return { state: { ...s, dir, queue: [], over: true, cause: 'wall' }, ate: false, died: true }
  }
  const next = r * s.cols + c
  const ate = next === s.food
  // 不长的话尾巴这一步会挪走,头可以跟进尾巴原来的格子
  const body = ate ? s.snake : s.snake.slice(0, -1)
  if (body.indexOf(next) >= 0) {
    return { state: { ...s, dir, queue: [], over: true, cause: 'self' }, ate: false, died: true }
  }
  const snake = [next, ...body]
  let { food, seed, score } = s
  let won = false
  if (ate) {
    score++
    ;[food, seed] = placeFood(snake, s.cols, s.rows, seed)
    won = food < 0
  }
  const state: State = { ...s, snake, dir, queue, food, seed, score, steps: s.steps + 1,
    over: won, won, cause: won ? 'full' : '' }
  return { state, ate, died: false }
}

export function rowCol(s: { cols: number }, i: number): [number, number] {
  return [Math.floor(i / s.cols), i % s.cols]
}

// ---------------------------------------------------------------- 存档

export interface Saved {
  v: 1; cols: number; rows: number; snake: number[]; dir: Dir; food: number; score: number
  seed: number; steps: number; over: boolean; won: boolean; cause: Cause
}
export interface Best { v: 1; score: number; games: number }
export const EMPTY_BEST: Best = { v: 1, score: 0, games: 0 }

export function save(s: State): Saved {
  return { v: 1, cols: s.cols, rows: s.rows, snake: s.snake.slice(), dir: s.dir, food: s.food, score: s.score,
    seed: s.seed, steps: s.steps, over: s.over, won: s.won, cause: s.cause }
}

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v)

/** 读档。格子数不对、蛇身不连着、重叠、食物压在蛇身上的一律当坏档(返回 null) */
export function load(raw: unknown): State | null {
  const o = raw as Saved | null
  if (!o || typeof o !== 'object' || o.v !== 1) return null
  if (o.cols !== COLS || o.rows !== ROWS || DIRS.indexOf(o.dir) < 0) return null
  const n = COLS * ROWS
  const snake = o.snake
  if (!Array.isArray(snake) || snake.length < START_LEN || snake.length > n) return null
  if (!snake.every((i) => isInt(i) && i >= 0 && i < n)) return null
  if (new Set(snake).size !== snake.length) return null
  for (let k = 1; k < snake.length; k++) {
    const [r1, c1] = rowCol(o, snake[k - 1])
    const [r2, c2] = rowCol(o, snake[k])
    if (Math.abs(r1 - r2) + Math.abs(c1 - c2) !== 1) return null
  }
  if (!isInt(o.food) || o.food >= n || o.food < -1 || snake.indexOf(o.food) >= 0) return null
  if (o.food === -1 && snake.length !== n) return null
  const score = snake.length - START_LEN
  const cause: Cause = o.cause === 'wall' || o.cause === 'self' || o.cause === 'full' ? o.cause : ''
  return { cols: COLS, rows: ROWS, snake: snake.slice(), dir: o.dir, queue: [], food: o.food, score,
    seed: Number(o.seed) >>> 0, steps: isInt(o.steps) && o.steps >= 0 ? o.steps : 0, over: !!o.over,
    won: !!o.won, cause: o.over ? cause : '' }
}

export function loadBest(raw: unknown): Best | null {
  const o = raw as Best | null
  if (!o || typeof o !== 'object' || o.v !== 1) return null
  return { v: 1, score: isInt(o.score) && o.score > 0 ? o.score : 0, games: isInt(o.games) && o.games > 0 ? o.games : 0 }
}

export function mergeBest(a: Best, b: Best): Best {
  return { v: 1, score: Math.max(a.score, b.score), games: Math.max(a.games, b.games) }
}

/** 最好成绩;finished 表示这一局算完了(撞了,或者没撞就开了新局) */
export function updateBest(b: Best, s: State, finished: boolean): Best {
  return { v: 1, score: Math.max(b.score, s.score), games: b.games + (finished ? 1 : 0) }
}
