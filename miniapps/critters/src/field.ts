// 对局的数据结构、战场几何和几个查询。和界面无关;battle.ts(模拟)和 ai.ts(电脑)都用它。
//
// 对局状态是纯数据(可以 JSON 往返,存档就存它);随机数状态也在里面,同一个种子、同一串操作,结果一样。
import {
  AiParams, BASE_TOWER, BASE_Y, CardDef, FIELD_H, FIELD_W, Goal, LANE_HALF, LANE_TOWER, LANE_X, Objective, ShotKind,
  Side, TOWER_Y, Theme, UnitStats, ZONE, card, statMul,
} from './data'

export const DT = 0.05 // 模拟一步 50 毫秒(每秒 20 步),画面按插值补到 60 帧

export interface DeckSpec {
  /** 8 张卡的 id(电脑的卡组可以有重复) */
  cards: string[]
  /** 卡 id → 等级 */
  levels: Record<string, number>
}

export interface BattleConfig {
  seed: number
  /** 一局多少秒 */
  duration: number
  objective: Objective
  /** 速攻要推倒几座塔(大本营算三座) */
  target: number
  decks: [DeckSpec, DeckSpec]
  /** 哪一边由电脑下:null 是玩家 */
  ai: [AiParams | null, AiParams | null]
  regen: [number, number]
  startEnergy: [number, number]
  towerHp: [number, number]
  /** 塔的等级(和卡牌一样每级 ×1.1):玩家按出战卡组的平均等级,电脑按章节 */
  towerLevel: [number, number]
  closed: number[]
  /** 移动速度倍率(冰面) */
  speed: number
  stars: [Goal, Goal, Goal]
  /** 这一局是哪一关:'1-3' / 'daily:2026-09-15' */
  tag: string
  theme: Theme
}

export interface Unit {
  id: number
  card: string
  side: Side
  lane: number
  x: number
  y: number
  /** 上一步的位置(界面插值用) */
  px: number
  py: number
  /** 在路里偏左还是偏右(相对路中线) */
  ox: number
  hp: number
  max: number
  lvl: number
  building: boolean
  air: boolean
  /** 攻击冷却(秒) */
  cd: number
  /** 目标 id,-1 是没有 */
  tgt: number
  /** 冲锋:连续走了几格 */
  run: number
  charged: boolean
  /** 什么时候能再扑 */
  leapAt: number
  leaping: boolean
  slowT: number
  slowK: number
  frozenT: number
  stunT: number
  poisonT: number
  poisonD: number
  rageT: number
  healT: number
  healR: number
  /** 建筑剩下几秒 */
  life: number
  /** 下次孵化 / 下次发作还有几秒 */
  spawnT: number
  pulseT: number
  born: number
}

export interface Tower {
  id: number
  side: Side
  /** 0/1/2 是三路的哨塔,-1 是大本营 */
  lane: number
  x: number
  y: number
  hp: number
  max: number
  atk: number
  rate: number
  range: number
  radius: number
  cd: number
  tgt: number
  frozenT: number
  alive: boolean
}

export interface Shot {
  id: number
  side: Side
  kind: ShotKind
  x: number
  y: number
  px: number
  py: number
  tgt: number
  /** 目标没了就飞到最后看到的位置 */
  tx: number
  ty: number
  speed: number
  dmg: number
  splash: number
  hitsAir: boolean
  slow: number
  poison: number
}

export interface SideState {
  energy: number
  /** 手里的 4 张 */
  hand: string[]
  /** 排队的,第一张是「下一张」 */
  queue: string[]
}

export interface Stats {
  /** 击倒敌方单位数 */
  kills: number
  /** 靠击倒返还的能量 */
  refund: number
  /** 出了几张牌 */
  played: number
  /** 推倒对面几座哨塔 */
  towers: number
  /** 推倒了对面的大本营 */
  base: boolean
  /** 自己丢了几座哨塔 */
  lost: number
  /** 对塔造成的伤害 */
  towerDmg: number
}

export interface AiMem {
  /** 下次想事情的时间 */
  next: number
  /** 各路发现威胁的时间,-1 是没有 */
  alarm: number[]
  /** 轮流进攻用:上次打的哪一路 */
  lane: number
}

export interface Over {
  /** 0 玩家赢,1 电脑赢,-1 平局 */
  winner: Side | -1
  reason: 'base' | 'blitz' | 'time' | 'defend' | 'timeout' | 'draw' | 'quit'
  t: number
}

export interface Battle {
  v: 1
  cfg: BattleConfig
  t: number
  seed: number
  nextId: number
  sides: [SideState, SideState]
  units: Unit[]
  shots: Shot[]
  towers: Tower[]
  ai: [AiMem | null, AiMem | null]
  stats: [Stats, Stats]
  over: Over | null
}

export interface Cmd {
  side: Side
  /** 手里第几张(0–3) */
  slot: number
  /** 这张的 id(防止界面和状态对不上) */
  card: string
  x: number
  y: number
}

// ---------------------------------------------------------------- 几何

export const foe = (s: Side): Side => (s === 0 ? 1 : 0)
/** 这一边往前走是 y 变小(玩家)还是变大(电脑) */
export const fwd = (s: Side): number => (s === 0 ? -1 : 1)
export const dist = (ax: number, ay: number, bx: number, by: number): number => Math.hypot(ax - bx, ay - by)
export const clamp = (v: number, a: number, b: number): number => (v < a ? a : v > b ? b : v)

/** 离 x 最近的一路 */
export function nearestLane(x: number, closed: number[] = []): number {
  let best = -1
  let bd = Infinity
  for (let l = 0; l < 3; l++) {
    if (closed.indexOf(l) >= 0) continue
    const d = Math.abs(x - LANE_X[l])
    if (d < bd) {
      bd = d
      best = l
    }
  }
  return best
}

export function statsOf(id: string): UnitStats {
  const u = card(id).unit
  if (!u) throw new Error(`${id} 不是单位`)
  return u
}

export const hitsAir = (s: UnitStats): boolean => !!(s.hitsAir || s.air)

/** 这一边这一路的哨塔(封掉的路没有) */
export function laneTower(b: Battle, side: Side, lane: number): Tower | undefined {
  return b.towers.find((t) => t.side === side && t.lane === lane)
}

export function baseOf(b: Battle, side: Side): Tower {
  return b.towers.find((t) => t.side === side && t.lane === -1) as Tower
}

/** 这一路打到大本营了没有(这一路对面的哨塔倒了) */
export function laneOpen(b: Battle, side: Side, lane: number): boolean {
  const t = laneTower(b, foe(side), lane)
  return !t || !t.alive
}

export function levelOf(b: Battle, side: Side, id: string): number {
  return b.cfg.decks[side].levels[id] || 1
}

export function mulOf(b: Battle, side: Side, id: string): number {
  return statMul(levelOf(b, side, id))
}

/** 出牌落点:单位和建筑吸到最近的一路、限制在自己半场;法术哪儿都能放 */
export function placement(b: Battle, side: Side, c: CardDef, x: number, y: number):
  { ok: boolean; x: number; y: number; lane: number; why?: string } {
  if (c.kind === 'spell') {
    return { ok: true, x: clamp(x, 0.3, FIELD_W - 0.3), y: clamp(y, 0.3, FIELD_H - 0.3), lane: nearestLane(x) }
  }
  const any = nearestLane(x)
  const lane = nearestLane(x, b.cfg.closed)
  if (lane < 0) return { ok: false, x, y, lane: -1, why: '没有能走的路' }
  const [lo, hi] = ZONE[side]
  const px = clamp(x, LANE_X[lane] - (LANE_HALF - 0.1), LANE_X[lane] + (LANE_HALF - 0.1))
  const py = clamp(y, lo, hi)
  if (any !== lane && Math.abs(x - LANE_X[any]) < 1) return { ok: false, x: LANE_X[any], y: py, lane: any, why: '这一路走不通' }
  return { ok: true, x: px, y: py, lane }
}

// ---------------------------------------------------------------- 开局

export function newStats(): Stats {
  return { kills: 0, refund: 0, played: 0, towers: 0, base: false, lost: 0, towerDmg: 0 }
}

export function makeTowers(cfg: BattleConfig): Tower[] {
  const out: Tower[] = []
  let id = 1
  for (const side of [0, 1] as Side[]) {
    const mul = statMul(cfg.towerLevel[side])
    for (let lane = 0; lane < 3; lane++) {
      if (cfg.closed.indexOf(lane) >= 0) continue
      const hp = Math.round(LANE_TOWER.hp * cfg.towerHp[side] * mul)
      out.push({ id: id++, side, lane, x: LANE_X[lane], y: TOWER_Y[side], hp, max: hp, atk: LANE_TOWER.atk * mul,
        rate: LANE_TOWER.rate, range: LANE_TOWER.range, radius: LANE_TOWER.radius, cd: 0, tgt: -1, frozenT: 0, alive: true })
    }
    const hp = Math.round(BASE_TOWER.hp * cfg.towerHp[side] * mul)
    out.push({ id: id++, side, lane: -1, x: LANE_X[1], y: BASE_Y[side], hp, max: hp, atk: BASE_TOWER.atk * mul,
      rate: BASE_TOWER.rate, range: BASE_TOWER.range, radius: BASE_TOWER.radius, cd: 0, tgt: -1, frozenT: 0, alive: true })
  }
  return out
}

/** 一座塔被推倒时各算几座(速攻的目标):哨塔 1 座,大本营 3 座 */
export function towerWorth(t: Tower): number {
  return t.lane === -1 ? 3 : 1
}

/** 还站着的建筑(塔、大本营)血量比例之和 —— 时间到、推倒的塔一样多时比这个 */
export function standing(b: Battle, side: Side): number {
  let s = 0
  for (const t of b.towers) if (t.side === side && t.alive) s += t.hp / t.max
  return s
}
