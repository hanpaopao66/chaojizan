// 平衡模拟:固定种子、纯引擎跑 AI 对 AI 的整局,不渲染、不读存档。
// 用来回答「三套牌能不能玩 / 三档难度胜率对不对」,单测里也跑同一套代码。
//
// 口径:玩家(座位 0)固定用「标准」档的水平操作(代表普通玩家),电脑座位按难度参数打;
// 每套玩家卡组 × 三档难度 × 先手/后手各跑 gamesPerCell 局,对手卡组在另外两套里轮换。
import { aiNext } from './ai'
import { HEROES, LEVELS } from './data'
import { applyAction, newGame } from './engine'
import type { Level, OverReason, Side } from './types'

/** 一局最多走多少步(正常对局几百步内一定结束;防止坏局面把模拟卡死) */
export const MAX_ACTIONS = 1200

export interface SimOptions {
  seed: number
  playerHero: string
  aiHero: string
  playerLevel: Level
  aiLevel: Level
  first: Side
}

export interface SimResult {
  winner: Side | -1
  turns: number
  reason: OverReason | 'stuck'
  actions: number
}

/** 跑一整局,返回胜负。和界面完全无关,固定种子可复现 */
export function simulateGame(o: SimOptions): SimResult {
  let s = newGame({ seed: o.seed >>> 0, hero0: o.playerHero, hero1: o.aiHero, first: o.first }).state
  let actions = 0
  while (!s.over && actions < MAX_ACTIONS) {
    const level = s.active === 0 ? o.playerLevel : o.aiLevel
    const next = applyAction(s, aiNext(s, level))
    if (!next.ok) break
    s = next.state
    actions++
  }
  return {
    winner: s.over?.winner ?? -1,
    turns: s.turn,
    reason: s.over?.reason ?? 'stuck',
    actions,
  }
}

export interface CellStats {
  playerHero: string
  level: Level
  first: Side
  games: number
  wins: number
  draws: number
  /** 没能在步数上限内结束的局(应该是 0) */
  stuck: number
  /** 玩家视角胜率 */
  winRate: number
}

export interface Tally {
  games: number
  wins: number
  draws: number
  winRate: number
}

export interface BalanceReport {
  cells: CellStats[]
  byLevel: Record<Level, Tally>
  byHero: Record<string, Tally>
  total: Tally
}

const emptyTally = (): Tally => ({ games: 0, wins: 0, draws: 0, winRate: 0 })

function add(t: Tally, r: SimResult): void {
  t.games++
  if (r.winner === 0) t.wins++
  else if (r.winner === -1) t.draws++
}

function finish(t: Tally): Tally {
  t.winRate = t.games > 0 ? t.wins / t.games : 0
  return t
}

export interface BalanceOptions {
  /** 每个格子(卡组 × 难度 × 先手)跑几局 */
  gamesPerCell: number
  seed?: number
  /** 玩家那一侧用哪一档水平(默认标准) */
  playerLevel?: Level
  levels?: readonly Level[]
}

/**
 * 跑完整的平衡矩阵。默认:3 套玩家卡组 × 3 档难度 × 先手/后手 × gamesPerCell。
 * 种子是固定的,同样参数跑两遍结果完全一样。
 */
export function balanceReport(o: BalanceOptions): BalanceReport {
  const levels = o.levels ?? LEVELS
  const playerLevel = o.playerLevel ?? 'normal'
  const seedBase = (o.seed ?? 20261018) >>> 0
  const per = Math.max(1, Math.floor(o.gamesPerCell))
  const cells: CellStats[] = []
  const byLevel = {} as Record<Level, Tally>
  for (const level of levels) byLevel[level] = emptyTally()
  const byHero: Record<string, Tally> = {}
  for (const h of HEROES) byHero[h.id] = emptyTally()
  const total = emptyTally()
  let n = 0
  for (let hi = 0; hi < HEROES.length; hi++) {
    const playerHero = HEROES[hi].id
    for (const level of levels) {
      for (const first of [0, 1] as Side[]) {
        const cell: CellStats = { playerHero, level, first, games: 0, wins: 0, draws: 0, stuck: 0, winRate: 0 }
        for (let i = 0; i < per; i++) {
          const aiHero = HEROES[(hi + 1 + (i % 2)) % HEROES.length].id
          const seed = (seedBase + n * 7919 + i * 104729) >>> 0
          n++
          const r = simulateGame({ seed, playerHero, aiHero, playerLevel, aiLevel: level, first })
          cell.games++
          if (r.winner === 0) cell.wins++
          else if (r.winner === -1) cell.draws++
          if (r.reason === 'stuck') cell.stuck++
          add(byLevel[level], r)
          add(byHero[playerHero], r)
          add(total, r)
        }
        cell.winRate = cell.games > 0 ? cell.wins / cell.games : 0
        cells.push(cell)
      }
    }
  }
  for (const level of levels) finish(byLevel[level])
  for (const h of HEROES) finish(byHero[h.id])
  finish(total)
  return { cells, byLevel, byHero, total }
}
