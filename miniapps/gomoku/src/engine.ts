// 五子棋引擎(人机):和界面无关的纯函数。
//
// 规则:15×15,黑先;横、竖、斜任一方向连成五子(或更多)就赢,不设禁手;下满没人连成是和棋。
// 悔棋一步:退回到你上一次落子之前(连同电脑的那一手);悔过之后要再下一子才能再悔。
//
// 电脑用评分法:对每个空点,看它在四个方向上能成什么棋型 ——
//   连五、活四(两头都能成五)、冲四(只有一头能成五)、活三(再下一子能成活四)、眠三、活二、眠二……
// 自己下在这里得「进攻分」,对方下在这里得「防守分」,加起来挑最高的。三档难度:
//   简单:防守看得轻、在几个还不错的点里随机挑(连五和堵对方连五不会漏);
//   中等:完整评分,挑最好的;
//   困难:中等之上再算「连续冲四」—— 自己有一路冲四冲到赢的就走,候选点走完会被对方冲四冲死的不走。
// 随机数(同分时挑哪个、简单档的随机)用带种子的 PRNG,种子存在状态里 —— 同一个种子、同一串落子,电脑的应手永远一样。
import { rand } from '../../shared/src/rand'

export const N = 15
export const CENTER = 7 * N + 7
export type Stone = 0 | 1 | 2
export type Color = 1 | 2
export type Level = 'easy' | 'medium' | 'hard'
export const LEVEL_KEYS: Level[] = ['easy', 'medium', 'hard']
export const LEVELS: Record<Level, string> = { easy: '简单', medium: '中等', hard: '困难' }

export interface State {
  board: Stone[]
  /** 落子顺序(格子下标 = 行 × 15 + 列) */
  moves: number[]
  /** 玩家执黑(1,先手)还是执白(2,后手) */
  human: Color
  level: Level
  /** PRNG 的当前状态 */
  seed: number
  /** 0 还没下完、1 黑胜、2 白胜、3 和棋 */
  winner: 0 | 1 | 2 | 3
  /** 连成五子的那几颗 */
  line: number[]
  /** 刚悔过一步:再落一子才能再悔 */
  undone: boolean
}

const DIRS: Array<[number, number]> = [[0, 1], [1, 0], [1, 1], [1, -1]]

export const rowCol = (i: number): [number, number] => [Math.floor(i / N), i % N]
const inside = (r: number, c: number) => r >= 0 && r < N && c >= 0 && c < N

/** 该谁下:黑先 */
export function turn(s: { moves: number[] }): Color {
  return s.moves.length % 2 === 0 ? 1 : 2
}

export function newGame(human: Color, level: Level, seed: number): State {
  return { board: new Array(N * N).fill(0), moves: [], human, level, seed: seed >>> 0, winner: 0, line: [],
    undone: false }
}

/** 经过 i 的连子(≥ 5 颗才返回,否则 null) */
export function fiveLine(board: Stone[], i: number): number[] | null {
  const color = board[i]
  if (!color) return null
  const [r, c] = rowCol(i)
  for (const [dr, dc] of DIRS) {
    const line = [i]
    for (const sign of [1, -1]) {
      let rr = r + dr * sign
      let cc = c + dc * sign
      while (inside(rr, cc) && board[rr * N + cc] === color) {
        line.push(rr * N + cc)
        rr += dr * sign
        cc += dc * sign
      }
    }
    if (line.length >= 5) return line.sort((a, b) => a - b)
  }
  return null
}

/** 落一子(该谁下就是谁的)。落不了(有子、下完了)返回原状态 */
export function play(s: State, i: number): State {
  if (s.winner || i < 0 || i >= N * N || s.board[i]) return s
  const color = turn(s)
  const board = s.board.slice()
  board[i] = color
  const moves = [...s.moves, i]
  const line = fiveLine(board, i)
  const winner = line ? color : moves.length === N * N ? 3 : 0
  return { ...s, board, moves, winner, line: line || [], undone: color === s.human ? false : s.undone }
}

/** 按落子顺序重放出一局(读档、悔棋用)。中途有非法的一步返回 null */
export function replay(moves: number[], human: Color, level: Level, seed: number, undone = false): State | null {
  let s = newGame(human, level, seed)
  for (const m of moves) {
    if (s.winner) return null // 分出胜负之后不该还有子
    const next = play(s, m)
    if (next === s) return null
    s = next
  }
  return { ...s, undone }
}

export function canUndo(s: State): boolean {
  if (s.undone || s.winner === s.human) return false
  return s.moves.some((_, k) => (k % 2 === 0 ? 1 : 2) === s.human)
}

/** 悔棋一步:退到你上一次落子之前(电脑已经应了的话,连同它那一手) */
export function undo(s: State): State {
  if (!canUndo(s)) return s
  const moves = s.moves.slice()
  while (moves.length) {
    const k = moves.length - 1
    moves.pop()
    if ((k % 2 === 0 ? 1 : 2) === s.human) break
  }
  return replay(moves, s.human, s.level, s.seed, true) as State
}

// ---------------------------------------------------------------- 棋型

export const P = { NONE: 0, ONE: 1, TWO: 2, OPEN_TWO: 3, THREE: 4, OPEN_THREE: 5, FOUR: 6, OPEN_FOUR: 7, FIVE: 8 }
export const PATTERN_NAMES = ['', '单子', '眠二', '活二', '眠三', '活三', '冲四', '活四', '连五']

/**
 * 以某一点为中心、某个方向上前后各 4 格的「窗口」:0 空、1 自己、2 对方或棋盘外。中心那格当作自己。
 * 棋型按定义递归地算:再下一子能成五的点有 2 个以上是活四、1 个是冲四;再下一子能成活四是活三、成冲四是眠三……
 * 窗口一共 3^8 种,算过的记下来。
 */
const memo = new Int8Array(6561).fill(-1)

function runThrough(w: number[]): number {
  let n = 1
  for (let k = 3; k >= 0 && w[k] === 1; k--) n++
  for (let k = 5; k <= 8 && w[k] === 1; k++) n++
  return n
}

function keyOf(w: number[]): number {
  let key = 0
  for (let k = 8; k >= 0; k--) if (k !== 4) key = key * 3 + w[k]
  return key
}

export function classify(w: number[]): number {
  const key = keyOf(w)
  if (memo[key] >= 0) return memo[key]
  let result = P.NONE
  if (runThrough(w) >= 5) result = P.FIVE
  else {
    let fives = 0
    for (let k = 0; k < 9; k++) {
      if (w[k] !== 0) continue
      w[k] = 1
      if (runThrough(w) >= 5) fives++
      w[k] = 0
    }
    if (fives >= 2) result = P.OPEN_FOUR
    else if (fives === 1) result = P.FOUR
    else {
      // 再下一子能成什么,往下降一级;在这个窗口里怎么下都成不了五的(被堵死了)是「无」
      for (let k = 0; k < 9; k++) {
        if (w[k] !== 0) continue
        w[k] = 1
        const p = classify(w)
        w[k] = 0
        const up = p === P.OPEN_FOUR ? P.OPEN_THREE : p === P.FOUR ? P.THREE : p === P.OPEN_THREE ? P.OPEN_TWO
          : p === P.THREE ? P.TWO : p === P.OPEN_TWO || p === P.TWO ? P.ONE : P.NONE
        if (up > result) result = up
      }
    }
  }
  memo[key] = result
  return result
}

/** 用字符串写窗口(测试用):'x' 自己、'_' 空、'o' 对方或边;中心是第 5 个字符,必须是 'x' */
export function classifyText(t: string): number {
  return classify(t.split('').map((ch) => (ch === 'x' ? 1 : ch === '_' ? 0 : 2)))
}

/** 如果 color 下在 i,四个方向各成什么棋型 */
export function patternsAt(board: Stone[], i: number, color: Color): number[] {
  const [r, c] = rowCol(i)
  const out: number[] = []
  const w = new Array(9).fill(0)
  for (const [dr, dc] of DIRS) {
    for (let k = -4; k <= 4; k++) {
      if (!k) { w[4] = 1; continue }
      const rr = r + dr * k
      const cc = c + dc * k
      const v = inside(rr, cc) ? board[rr * N + cc] : 3
      w[k + 4] = v === 0 ? 0 : v === color ? 1 : 2
    }
    out.push(classify(w))
  }
  return out
}

const SCORE = [0, 10, 100, 800, 1000, 10_000, 20_000, 100_000, 10_000_000]
export const WIN = 10_000_000
export const THREAT = 1_000_000

/** 四个方向合起来的分:连五最大;活四、双冲四、冲四活三是「下一手就赢」;双活三次之 */
export function combine(ps: number[]): number {
  let open4 = 0
  let four = 0
  let open3 = 0
  let sum = 0
  for (const p of ps) {
    if (p === P.FIVE) return WIN
    if (p === P.OPEN_FOUR) open4++
    else if (p === P.FOUR) four++
    else if (p === P.OPEN_THREE) open3++
    sum += SCORE[p]
  }
  if (open4 || four >= 2 || (four && open3)) return THREAT + sum
  if (open3 >= 2) return 200_000 + sum
  return sum
}

/** 值得考虑的空点:离已有棋子两格以内 */
export function candidates(board: Stone[]): number[] {
  const out: number[] = []
  for (let i = 0; i < N * N; i++) {
    if (board[i]) continue
    const [r, c] = rowCol(i)
    let near = false
    for (let dr = -2; dr <= 2 && !near; dr++) {
      for (let dc = -2; dc <= 2; dc++) {
        const rr = r + dr
        const cc = c + dc
        if (inside(rr, cc) && board[rr * N + cc]) { near = true; break }
      }
    }
    if (near) out.push(i)
  }
  return out
}

/** color 下在 i 之后,能一步成五的点 */
function fivePoints(board: Stone[], i: number, color: Color): number[] {
  const out: number[] = []
  const [r, c] = rowCol(i)
  for (const [dr, dc] of DIRS) {
    for (let k = -4; k <= 4; k++) {
      const rr = r + dr * k
      const cc = c + dc * k
      if (!k || !inside(rr, cc) || board[rr * N + cc]) continue
      const e = rr * N + cc
      board[e] = color
      if (fiveLine(board, i) && out.indexOf(e) < 0) out.push(e)
      board[e] = 0
    }
  }
  return out
}

/**
 * 连续冲四(VCF):color 一路冲四(对方每次只能堵那唯一的成五点),冲到活四或双四就赢。
 * 找到了返回第一步,没有返回 -1。depth 是最多冲几手,budget 是最多试多少个局面(防止算太久)。
 */
export function vcf(board: Stone[], color: Color, depth = 10, budget = { left: 3000 }): number {
  const b = board.slice()
  return vcfIn(b, color, depth, budget)
}

function vcfIn(b: Stone[], color: Color, depth: number, budget: { left: number }): number {
  if (depth <= 0 || budget.left <= 0) return -1
  budget.left--
  const other = (3 - color) as Color
  const cands = candidates(b)
  for (const e of cands) if (patternsAt(b, e, color).indexOf(P.FIVE) >= 0) return e
  // 对方已经有成五点:冲四也挡不住它,不算
  for (const e of cands) if (patternsAt(b, e, other).indexOf(P.FIVE) >= 0) return -1
  for (const e of cands) {
    const ps = patternsAt(b, e, color)
    if (ps.indexOf(P.FOUR) < 0 && ps.indexOf(P.OPEN_FOUR) < 0) continue
    b[e] = color
    const pts = fivePoints(b, e, color)
    let win = pts.length >= 2
    if (pts.length === 1) {
      b[pts[0]] = other
      win = vcfIn(b, color, depth - 1, budget) >= 0
      b[pts[0]] = 0
    }
    b[e] = 0
    if (win) return e
    if (budget.left <= 0) return -1
  }
  return -1
}

// ---------------------------------------------------------------- 电脑

interface Scored { i: number; a: number; d: number; v: number }

function centerBonus(i: number): number {
  const [r, c] = rowCol(i)
  return 7 - Math.max(Math.abs(r - 7), Math.abs(c - 7))
}

/** 在 list 里按 v 从大到小,v 相差不到 3% 的里随机挑一个 */
function pickBest(list: Scored[], seed: number): { i: number; seed: number } {
  const sorted = list.slice().sort((x, y) => y.v - x.v)
  const top = sorted[0].v
  const near = sorted.filter((x) => x.v >= top - Math.abs(top) * 0.03)
  const [a, next] = rand(seed)
  return { i: near[Math.floor(a * near.length)].i, seed: next }
}

/** 电脑在 board 上替 me 挑一手 */
export function chooseMove(board: Stone[], me: Color, level: Level, seed: number): { i: number; seed: number } {
  if (board.every((v) => !v)) return { i: CENTER, seed }
  const you = (3 - me) as Color
  const cands = candidates(board)
  const scored: Scored[] = cands.map((i) => {
    const a = combine(patternsAt(board, i, me))
    const d = combine(patternsAt(board, i, you))
    return { i, a, d, v: 0 }
  })
  // 自己能连五:下;对方下一手连五:堵
  const five = scored.filter((x) => x.a >= WIN)
  if (five.length) return pickBest(five.map((x) => ({ ...x, v: 1 })), seed)
  const block = scored.filter((x) => x.d >= WIN)
  if (block.length) return pickBest(block.map((x) => ({ ...x, v: x.a })), seed)

  if (level === 'easy') {
    // 防守看得轻;一半时候下自己眼里最好的点,一半时候在接下来的三个点里随便挑 —— 对方的活三常常看漏
    for (const x of scored) x.v = x.a + x.d * 0.35 + centerBonus(x.i)
    const sorted = scored.sort((x, y) => y.v - x.v)
    const [a, s1] = rand(seed)
    if (a < 0.5 || sorted.length < 2) return { i: sorted[0].i, seed: s1 }
    const rest = sorted.slice(1, 4)
    const [b, s2] = rand(s1)
    return { i: rest[Math.floor(b * rest.length)].i, seed: s2 }
  }

  for (const x of scored) x.v = x.a + x.d * 0.9 + centerBonus(x.i)
  if (level === 'medium') return pickBest(scored, seed)

  // 困难:自己有「下一手就赢」的先走;有连续冲四的走;
  // 否则往后看三手(我、对方、我),候选点走完会被对方连续冲四冲死的不走
  const threat = scored.filter((x) => x.a >= THREAT)
  if (threat.length) return pickBest(threat.map((x) => ({ ...x, v: x.a })), seed)
  // 预算是按中端手机算的:最坏一手也要在半秒左右算完(界面在同一个线程上,算久了会卡)
  const win = vcf(board, me, 10, { left: 1500 })
  if (win >= 0) return { i: win, seed }
  const top = scored.slice().sort((x, y) => y.v - x.v).slice(0, 8)
  const b = board.slice()
  const budget = { left: 2500 }
  const judged = top.map((x) => {
    b[x.i] = me
    const lost = vcf(b, you, 8, { left: 300 }) >= 0
    const look = lost ? -WIN : -negamax(b, you, 2, -Infinity, Infinity, budget, 4)
    b[x.i] = 0
    // 往后看的分为主,原来的评分只用来在差不多的点里分先后
    return { ...x, v: look + x.v * 0.001 }
  })
  return pickBest(judged, seed)
}

/** side 这一方最强的一手能到多少分 */
function bestAttack(b: Stone[], side: Color, cands: number[]): number {
  let m = 0
  for (const i of cands) {
    const v = combine(patternsAt(b, i, side))
    if (v > m) m = v
  }
  return m
}

/** 该 side 走时值得看的几手:能连五就只看连五;对方有成五点就只看堵的点;否则按评分取前 limit 个 */
function orderedMoves(b: Stone[], side: Color, cands: number[], limit: number): number[] {
  const other = (3 - side) as Color
  const scored = cands.map((i) => ({ i, a: combine(patternsAt(b, i, side)), d: combine(patternsAt(b, i, other)) }))
  const five = scored.find((x) => x.a >= WIN)
  if (five) return [five.i]
  const block = scored.filter((x) => x.d >= WIN)
  if (block.length) return block.map((x) => x.i)
  return scored.sort((x, y) => y.a + y.d * 0.9 - (x.a + x.d * 0.9)).slice(0, limit).map((x) => x.i)
}

/**
 * 从 side 的角度估一个局面:往后看 depth 手(α-β 剪枝)。看到头时用「双方各自最强的一手」估:
 * 轮到的一方能连五就是赢;能走出「下一手就赢」而对方没有成五点,也算赢;否则两边最强一手的分相减。
 * 对方有成五点(刚冲了四)时不算看到头,再往下看「堵」这一手(最多 extra 次),免得冲四链走一半就停下来估。
 */
function negamax(b: Stone[], side: Color, depth: number, alpha: number, beta: number, budget: { left: number },
  extra: number): number {
  budget.left--
  const other = (3 - side) as Color
  const cands = candidates(b)
  if (!cands.length) return 0
  const mine = bestAttack(b, side, cands)
  if (mine >= WIN) return WIN
  const theirs = bestAttack(b, other, cands)
  const forced = theirs >= WIN
  if ((depth <= 0 && !(forced && extra > 0)) || budget.left <= 0) {
    if (forced) return -THREAT / 2 // 看到头时正被冲四:要先堵,局面不好说,按吃亏算
    if (mine >= THREAT) return THREAT
    return mine - theirs * 0.9
  }
  const moves = orderedMoves(b, side, cands, depth >= 2 ? 8 : 6)
  let best = -Infinity
  for (const m of moves) {
    b[m] = side
    const v = fiveLine(b, m) ? WIN
      : -negamax(b, other, depth - 1, -beta, -alpha, budget, forced ? extra - 1 : extra)
    b[m] = 0
    if (v > best) best = v
    if (best > alpha) alpha = best
    if (alpha >= beta) break
  }
  return best
}

/** 轮到电脑时替它走一手(不是电脑的回合、或者下完了返回原状态) */
export function aiMove(s: State): State {
  if (s.winner || turn(s) === s.human) return s
  const { i, seed } = chooseMove(s.board, turn(s), s.level, s.seed)
  return play({ ...s, seed }, i)
}

// ---------------------------------------------------------------- 存档

export interface Saved { v: 1; moves: number[]; human: Color; level: Level; seed: number; undone: boolean }
export interface LevelRecord { win: number; lose: number; draw: number }
export type Best = { v: 1 } & Record<Level, LevelRecord>
export const EMPTY_BEST: Best = { v: 1, easy: { win: 0, lose: 0, draw: 0 }, medium: { win: 0, lose: 0, draw: 0 },
  hard: { win: 0, lose: 0, draw: 0 } }

export function save(s: State): Saved {
  return { v: 1, moves: s.moves.slice(), human: s.human, level: s.level, seed: s.seed, undone: s.undone }
}

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v)

/** 读档:按落子顺序重放,有一步不对就当坏档(返回 null) */
export function load(raw: unknown): State | null {
  const o = raw as Saved | null
  if (!o || typeof o !== 'object' || o.v !== 1) return null
  if ((o.human !== 1 && o.human !== 2) || LEVEL_KEYS.indexOf(o.level) < 0) return null
  if (!Array.isArray(o.moves) || o.moves.length > N * N || !o.moves.every((m) => isInt(m) && m >= 0 && m < N * N)) {
    return null
  }
  return replay(o.moves, o.human, o.level, Number(o.seed) >>> 0, !!o.undone)
}

function record(raw: unknown): LevelRecord {
  const o = (raw || {}) as LevelRecord
  const n = (v: unknown) => (isInt(v) && v > 0 ? v : 0)
  return { win: n(o.win), lose: n(o.lose), draw: n(o.draw) }
}

export function loadBest(raw: unknown): Best | null {
  const o = raw as Best | null
  if (!o || typeof o !== 'object' || o.v !== 1) return null
  return { v: 1, easy: record(o.easy), medium: record(o.medium), hard: record(o.hard) }
}

export function mergeBest(a: Best, b: Best): Best {
  const m = (x: LevelRecord, y: LevelRecord): LevelRecord => ({
    win: Math.max(x.win, y.win), lose: Math.max(x.lose, y.lose), draw: Math.max(x.draw, y.draw) })
  return { v: 1, easy: m(a.easy, b.easy), medium: m(a.medium, b.medium), hard: m(a.hard, b.hard) }
}

function bump(b: Best, s: State, by: 1 | -1): Best {
  if (!s.winner) return b
  const r = b[s.level]
  const key: keyof LevelRecord = s.winner === 3 ? 'draw' : s.winner === s.human ? 'win' : 'lose'
  return { ...b, [s.level]: { ...r, [key]: Math.max(0, r[key] + by) } }
}

/** 一局下完记一笔 */
export function updateBest(b: Best, s: State): Best {
  return bump(b, s, 1)
}

/** 下完了又悔棋(输了、和了还能悔):把刚记的那一笔撤回,不然一局会记两次 */
export function revertBest(b: Best, s: State): Best {
  return bump(b, s, -1)
}
