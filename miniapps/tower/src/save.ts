// 存档:把一局状态序列化成普通 JSON、读回来时逐字段校验(坏档当作没有)、以及结算用的汇总。
// 和 engine.ts 共用同一份数据形状;规则本身在 engine.ts,这里只管「能存能读」。
import { STEP, enemyDefOrNull, towerDefOrNull } from './data'
import { levelByIdOrNull, waveCount } from './levels'
import type { Enemy, GameState } from './types'

const SAVE_V = 1
const MAX_ENEMIES = 300
const MAX_TOWERS = 64
const MAX_SPAWNS = 800
const MAX_SHOTS = 64
const MAX_WAVE = 5000

/** 序列化成可以放进 JSON 的普通对象(子弹只留最后 32 发,控制大小) */
export function saveGame(state: GameState): unknown {
  return {
    ...state,
    acc: 0,
    shots: state.shots.slice(-32),
    stats: { ...state.stats, towers: [...state.stats.towers] },
    spawns: state.spawns.map((s) => ({ ...s })),
    enemies: state.enemies.map((e) => ({ ...e })),
    towers: state.towers.map((t) => ({ ...t })),
  }
}

const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const int = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number =>
  typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max

/** 读一份存档;任何不对劲的地方都返回 null(当作没有存档),不抛错 */
export function loadGame(raw: unknown): GameState | null {
  const s = raw as GameState
  if (!s || typeof s !== 'object' || s.v !== SAVE_V) return null
  const level = levelByIdOrNull(s.levelId)
  if (!level) return null
  if (typeof s.endless !== 'boolean' || s.endless !== (level.id === 'endless')) return null
  if (!int(s.gold, 0, 1e9) || !int(s.hp, 0, 1e4)) return null
  if (!int(s.maxHp, 1, 1e4) || s.maxHp !== level.goalHp || s.hp > s.maxHp) return null
  if (!int(s.wave, 0, level.id === 'endless' ? MAX_WAVE : waveCount(level))) return null
  if (s.phase !== 'prep' && s.phase !== 'wave' && s.phase !== 'over') return null
  if (s.over !== null && s.over !== 'win' && s.over !== 'lose') return null
  if ((s.over === null) === (s.phase === 'over')) return null
  if (!int(s.stars, 0, 3)) return null
  if (s.over === 'win' ? s.stars < 1 : s.stars !== 0) return null
  if (s.speed !== 1 && s.speed !== 2) return null
  if (typeof s.paused !== 'boolean' || typeof s.summoned !== 'boolean' || typeof s.bossWave !== 'boolean') return null
  if (!num(s.time) || s.time < 0 || s.time > 1e7) return null
  if (!num(s.prep) || s.prep < 0 || !num(s.clock) || s.clock < 0) return null
  if (!num(s.rng) || !int(s.nextId, 1, 1e9) || !num(s.acc) || s.acc < 0 || s.acc > STEP * 2) return null
  if (!Array.isArray(s.enemies) || s.enemies.length > MAX_ENEMIES) return null
  if (!Array.isArray(s.towers) || s.towers.length > MAX_TOWERS) return null
  if (!Array.isArray(s.spawns) || s.spawns.length > MAX_SPAWNS) return null
  if (!Array.isArray(s.shots) || s.shots.length > MAX_SHOTS) return null
  const stats = s.stats
  if (!stats || typeof stats !== 'object') return null
  for (const k of ['kills', 'bossKills', 'leaks', 'goldEarned', 'built', 'sold', 'upgrades'] as const) {
    if (!int(stats[k], 0, 1e9)) return null
  }
  if (!Array.isArray(stats.towers) || stats.towers.length > 16 || stats.towers.some((k) => !towerDefOrNull(k))) {
    return null
  }

  const enemies: Enemy[] = []
  const ids = new Set<number>()
  for (const rawE of s.enemies) {
    if (!rawE || typeof rawE !== 'object') return null
    const def = enemyDefOrNull(rawE.kind)
    if (!def) return null
    if (!int(rawE.id, 1, 1e9) || ids.has(rawE.id) || !int(rawE.hp, 1, 1e9)) return null
    if (!int(rawE.maxHp, 1, 1e9) || rawE.hp > rawE.maxHp) return null
    const path = rawE.path
    if (!int(path, 0, level.world.polys.length - 1)) return null
    const span = def.flying
      ? Math.hypot(level.world.target.x - level.world.starts[path].x, level.world.target.y - level.world.starts[path].y)
      : level.world.lens[path]
    if (!num(rawE.dist) || rawE.dist < 0 || rawE.dist > span + 1) return null
    for (const k of ['slowUntil', 'slowFactor', 'freezeUntil', 'poisonUntil', 'poisonDps',
      'burnUntil', 'burnDps', 'flash'] as const) {
      if (!num(rawE[k]) || rawE[k] < 0) return null
    }
    ids.add(rawE.id)
    enemies.push({
      id: rawE.id, kind: rawE.kind, hp: rawE.hp, maxHp: rawE.maxHp,
      dist: Math.min(span, rawE.dist), span, path,
      slowUntil: rawE.slowUntil, slowFactor: rawE.slowFactor, freezeUntil: rawE.freezeUntil,
      poisonUntil: rawE.poisonUntil, poisonDps: rawE.poisonDps, burnUntil: rawE.burnUntil,
      burnDps: rawE.burnDps, flash: rawE.flash,
    })
  }

  const towers: GameState['towers'] = []
  const slots = new Set<number>()
  for (const rawT of s.towers) {
    if (!rawT || typeof rawT !== 'object') return null
    const def = towerDefOrNull(rawT.kind)
    if (!def) return null
    if (!int(rawT.id, 1, 1e9) || ids.has(rawT.id) || !int(rawT.slot, 0, level.slots.length - 1)) return null
    if (slots.has(rawT.slot)) return null
    if (!int(rawT.level, 1, 3) || !num(rawT.cd) || rawT.cd < 0 || rawT.cd > 60) return null
    if (!num(rawT.aim) || !num(rawT.invested) || rawT.invested < def.cost) return null
    slots.add(rawT.slot)
    ids.add(rawT.id)
    towers.push({
      id: rawT.id, kind: rawT.kind, level: rawT.level as 1 | 2 | 3, slot: rawT.slot,
      cd: rawT.cd, aim: rawT.aim, invested: rawT.invested,
    })
  }

  const spawns: GameState['spawns'] = []
  for (const rawS of s.spawns) {
    if (!rawS || typeof rawS !== 'object' || !enemyDefOrNull(rawS.kind)) return null
    if (!num(rawS.at) || rawS.at < 0 || rawS.at > 1e6) return null
    if (!int(rawS.path, 0, level.world.polys.length - 1)) return null
    spawns.push({ kind: rawS.kind, at: rawS.at, path: rawS.path })
  }

  const shots: GameState['shots'] = []
  for (const rawShot of s.shots) {
    if (!rawShot || typeof rawShot !== 'object') return null
    if (rawShot.kind !== 'pea' && rawShot.kind !== 'bow' && rawShot.kind !== 'pepper') return null
    if (![rawShot.x, rawShot.y, rawShot.tx, rawShot.ty, rawShot.life, rawShot.max].every(num)) return null
    if (rawShot.life < 0 || rawShot.max <= 0 || rawShot.life > rawShot.max) return null
    shots.push({ kind: rawShot.kind, x: rawShot.x, y: rawShot.y, tx: rawShot.tx, ty: rawShot.ty, life: rawShot.life, max: rawShot.max })
  }

  return {
    v: 1,
    levelId: s.levelId,
    seed: Math.floor(s.seed) >>> 0 || 1,
    rng: Math.floor(s.rng) >>> 0 || 1,
    gold: s.gold,
    hp: s.hp,
    maxHp: s.maxHp,
    wave: s.wave,
    phase: s.phase,
    prep: s.prep,
    clock: s.clock,
    spawns,
    enemies,
    towers,
    shots,
    nextId: Math.max(s.nextId, [...ids].reduce((m, v) => Math.max(m, v), 0) + 1, 1),
    over: s.over,
    stars: s.stars,
    time: s.time,
    summoned: s.summoned,
    paused: s.paused,
    speed: s.speed,
    endless: s.endless,
    stats: {
      kills: stats.kills, bossKills: stats.bossKills, leaks: stats.leaks, goldEarned: stats.goldEarned,
      built: stats.built, sold: stats.sold, upgrades: stats.upgrades, towers: [...stats.towers],
    },
    acc: 0,
    bossWave: s.bossWave,
  }
}

/** 一局结束时的战报(结算页用) */
export interface RunResult {
  levelId: number | 'endless'
  won: boolean
  stars: number
  hp: number
  maxHp: number
  kills: number
  bossKills: number
  leaks: number
  goldEarned: number
  built: number
  waves: number
  time: number
  endlessWave: number
  towerKinds: GameState['stats']['towers']
}

/** 结算用的汇总 */
export function resultOf(state: GameState): RunResult {
  return {
    levelId: state.levelId,
    won: state.over === 'win',
    stars: state.stars,
    hp: state.hp,
    maxHp: state.maxHp,
    kills: state.stats.kills,
    bossKills: state.stats.bossKills,
    leaks: state.stats.leaks,
    goldEarned: state.stats.goldEarned,
    built: state.stats.built,
    waves: state.wave,
    time: state.time,
    endlessWave: state.endless ? state.wave : 0,
    towerKinds: state.stats.towers,
  }
}
