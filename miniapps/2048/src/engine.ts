// 2048 引擎:和界面无关的纯函数(DEV-PROMPTS-39 #328)。
//
// 规则:4×4;开局两块;每步在空格随机出 2(90%)或 4(10%);滑动合并,**每块每步最多合并一次**;
// 合并得分累加;拼出 2048 可以继续;无路可走即结束。不做撤销。
// 随机数是带种子的 PRNG(mulberry32),种子存在状态里 —— 同一个种子、同一串操作,结果永远一样,
// 关了再开也接得上。

export const SIZE = 4
export const WIN = 2048

export type Dir = 'up' | 'down' | 'left' | 'right'

export interface Tile {
  id: number
  value: number
  row: number
  col: number
}

export interface State {
  tiles: Tile[]
  score: number
  /** PRNG 的当前状态(不是初始种子):每取一次随机数就往前走一步 */
  seed: number
  moves: number
  /** 拼出过 2048 */
  won: boolean
  over: boolean
  nextId: number
}

export interface MoveResult {
  state: State
  moved: boolean
  gained: number
  /** 这一步合并出来的块(界面据此做「弹一下」) */
  merged: Tile[]
  /** 被合并掉的块 id 和它滑到的位置(界面据此先滑过去再消失) */
  consumed: Array<{ id: number; row: number; col: number }>
  spawned: Tile | null
  /** 这一步刚刚拼出 2048 */
  justWon: boolean
}

/** mulberry32:32 位状态,够小够快,分布对这个游戏足够 */
export function rand(seed: number): [number, number] {
  let t = (seed + 0x6d2b79f5) >>> 0
  const next = t
  t = Math.imul(t ^ (t >>> 15), t | 1)
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
  return [((t ^ (t >>> 14)) >>> 0) / 4294967296, next]
}

/** 把一行(已经按滑动方向排好)往前挤、合并。纯数值版,单测用 */
export function slideLine(line: number[]): { out: number[]; gained: number } {
  const vals = line.filter((v) => v)
  const out: number[] = []
  let gained = 0
  for (let i = 0; i < vals.length; i++) {
    if (i + 1 < vals.length && vals[i] === vals[i + 1]) {
      out.push(vals[i] * 2)
      gained += vals[i] * 2
      i++ // 合并过的块这一步不再参与合并
    } else {
      out.push(vals[i])
    }
  }
  while (out.length < line.length) out.push(0)
  return { out, gained }
}

function grid(tiles: Tile[]): (Tile | null)[][] {
  const g: (Tile | null)[][] = Array.from({ length: SIZE }, () => Array(SIZE).fill(null))
  for (const t of tiles) g[t.row][t.col] = t
  return g
}

export function emptyCells(tiles: Tile[]): Array<[number, number]> {
  const g = grid(tiles)
  const out: Array<[number, number]> = []
  for (let r = 0; r < SIZE; r++) for (let c = 0; c < SIZE; c++) if (!g[r][c]) out.push([r, c])
  return out
}

/** 在空格里随机出一块:2(90%)或 4(10%)。没有空格返回原状态 */
export function spawn(s: State): { state: State; tile: Tile | null } {
  const empty = emptyCells(s.tiles)
  if (!empty.length) return { state: s, tile: null }
  let [a, seed] = rand(s.seed)
  const [row, col] = empty[Math.floor(a * empty.length)]
  ;[a, seed] = rand(seed)
  const tile: Tile = { id: s.nextId, value: a < 0.9 ? 2 : 4, row, col }
  return { state: { ...s, seed, nextId: s.nextId + 1, tiles: [...s.tiles, tile] }, tile }
}

export function newGame(seed: number): State {
  let s: State = { tiles: [], score: 0, seed: seed >>> 0, moves: 0, won: false, over: false, nextId: 1 }
  s = spawn(s).state
  s = spawn(s).state
  return s
}

/** 按方向取每一条线上的坐标,从「被挤向的那一头」开始 */
function lines(dir: Dir): Array<Array<[number, number]>> {
  const out: Array<Array<[number, number]>> = []
  for (let i = 0; i < SIZE; i++) {
    const line: Array<[number, number]> = []
    for (let j = 0; j < SIZE; j++) {
      if (dir === 'left') line.push([i, j])
      else if (dir === 'right') line.push([i, SIZE - 1 - j])
      else if (dir === 'up') line.push([j, i])
      else line.push([SIZE - 1 - j, i])
    }
    out.push(line)
  }
  return out
}

export function move(s: State, dir: Dir): MoveResult {
  const g = grid(s.tiles)
  const next: Tile[] = []
  const merged: Tile[] = []
  const consumed: MoveResult['consumed'] = []
  let gained = 0
  let moved = false
  let nextId = s.nextId
  for (const line of lines(dir)) {
    const tiles = line.map(([r, c]) => g[r][c]).filter((t): t is Tile => !!t)
    let slot = 0
    for (let i = 0; i < tiles.length; i++) {
      const [r, c] = line[slot]
      const a = tiles[i]
      const b = tiles[i + 1]
      if (b && a.value === b.value) {
        const m: Tile = { id: nextId++, value: a.value * 2, row: r, col: c }
        next.push(m)
        merged.push(m)
        consumed.push({ id: a.id, row: r, col: c }, { id: b.id, row: r, col: c })
        gained += m.value
        moved = true
        i++
      } else {
        if (a.row !== r || a.col !== c) moved = true
        next.push({ ...a, row: r, col: c })
      }
      slot++
    }
  }
  if (!moved) return { state: s, moved: false, gained: 0, merged: [], consumed: [], spawned: null, justWon: false }
  const justWon = !s.won && merged.some((t) => t.value >= WIN)
  let state: State = { ...s, tiles: next, score: s.score + gained, moves: s.moves + 1, won: s.won || justWon, nextId }
  const sp = spawn(state)
  state = sp.state
  state = { ...state, over: !canMove(state.tiles) }
  return { state, moved: true, gained, merged, consumed, spawned: sp.tile, justWon }
}

/** 还有没有路:有空格,或者有相邻的两块相等 */
export function canMove(tiles: Tile[]): boolean {
  if (tiles.length < SIZE * SIZE) return true
  const g = grid(tiles)
  for (let r = 0; r < SIZE; r++) {
    for (let c = 0; c < SIZE; c++) {
      const v = g[r][c]?.value
      if ((c + 1 < SIZE && g[r][c + 1]?.value === v) || (r + 1 < SIZE && g[r + 1][c]?.value === v)) return true
    }
  }
  return false
}

export function maxTile(tiles: Tile[]): number {
  return tiles.reduce((m, t) => Math.max(m, t.value), 0)
}

/** 从一个 4×4 数组造状态(测试和存档恢复用) */
export function fromBoard(board: number[][], rest: Partial<State> = {}): State {
  const tiles: Tile[] = []
  let id = 1
  board.forEach((row, r) => row.forEach((v, c) => { if (v) tiles.push({ id: id++, value: v, row: r, col: c }) }))
  return { tiles, score: 0, seed: 1, moves: 0, won: false, over: !canMove(tiles), nextId: id, ...rest }
}

export function toBoard(tiles: Tile[]): number[][] {
  const b = Array.from({ length: SIZE }, () => Array(SIZE).fill(0))
  for (const t of tiles) b[t.row][t.col] = t.value
  return b
}

// ---------------------------------------------------------------- 存档

export interface Saved { v: 1; board: number[][]; score: number; seed: number; moves: number; won: boolean }
export interface Best { v: 1; score: number; max_tile: number; games: number }

export function save(s: State): Saved {
  return { v: 1, board: toBoard(s.tiles), score: s.score, seed: s.seed, moves: s.moves, won: s.won }
}

export function load(raw: string | null | undefined): State | null {
  if (!raw) return null
  try {
    const o = JSON.parse(raw) as Saved
    if (o.v !== 1 || !Array.isArray(o.board) || o.board.length !== SIZE) return null
    if (!o.board.every((row) => Array.isArray(row) && row.length === SIZE
      && row.every((v) => v === 0 || (Number.isInteger(v) && v >= 2 && (v & (v - 1)) === 0)))) return null
    return fromBoard(o.board, { score: Number(o.score) || 0, seed: Number(o.seed) >>> 0,
      moves: Number(o.moves) || 0, won: !!o.won })
  } catch (_) {
    return null
  }
}

export function updateBest(best: Best | null, s: State, finished: boolean): Best {
  const b = best || { v: 1, score: 0, max_tile: 0, games: 0 }
  return { v: 1, score: Math.max(b.score, s.score), max_tile: Math.max(b.max_tile, maxTile(s.tiles)),
    games: b.games + (finished ? 1 : 0) }
}
