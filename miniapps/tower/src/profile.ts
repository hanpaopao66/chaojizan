// 档案:关卡星级、解锁进度、成就、无尽最高波数、设置(声音/默认倍速)和累计统计。
// 和界面无关;读档 / 坏档兜底 / 两台设备合并 / 成就判定都在这里,单测直接调用。
import { ACHIEVEMENTS, towerDefOrNull } from './data'
import { LEVELS } from './levels'
import type { RunResult } from './save'
import type { TowerKind } from './types'

/** 累计统计:两台设备合并时逐项取大的(宁可少记,不要多算) */
export interface BestStats {
  games: number
  wins: number
  kills: number
  bossKills: number
  /** 累计赚到的金币 */
  gold: number
  /** 单局造塔最多的一座数 */
  maxTowers: number
}

export interface Best {
  v: 1
  /** 关卡 id → 星级(1–3);没通关过的没有这个键 */
  stars: Record<string, number>
  /** 无尽模式最高波数 */
  endlessBest: number
  achievements: string[]
  /** 看过的新手提示(只给第一关用) */
  seen: string[]
  sound: boolean
  speed: 1 | 2
  stats: BestStats
  /** 七种塔里造过哪些 */
  usedTowers: TowerKind[]
}

const MAX_LEVEL_ID = 12
const STAR_KEYS = new Set(LEVELS.map((l) => String(l.id)))
const ACH_IDS = new Set(ACHIEVEMENTS.map((a) => a.id))

const isInt = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number =>
  typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max

export function newProfile(): Best {
  return {
    v: 1,
    stars: {},
    endlessBest: 0,
    achievements: [],
    seen: [],
    sound: true,
    speed: 1,
    stats: { games: 0, wins: 0, kills: 0, bossKills: 0, gold: 0, maxTowers: 0 },
    usedTowers: [],
  }
}

/** 读档案;坏的、版本不对的返回 null(当作全新档案) */
export function loadBest(raw: unknown): Best | null {
  const b = raw as Best
  if (!b || typeof b !== 'object' || b.v !== 1) return null
  if (!b.stars || typeof b.stars !== 'object' || Array.isArray(b.stars)) return null
  const stars: Record<string, number> = {}
  for (const [k, v] of Object.entries(b.stars)) {
    if (!STAR_KEYS.has(k) || !isInt(v, 1, 3)) return null
    stars[k] = v
  }
  if (!isInt(b.endlessBest, 0, 5000)) return null
  if (!Array.isArray(b.achievements) || b.achievements.length > ACHIEVEMENTS.length) return null
  const achievements = [...new Set(b.achievements)]
  if (achievements.some((id) => typeof id !== 'string' || !ACH_IDS.has(id))) return null
  if (!Array.isArray(b.seen) || b.seen.length > 32 || b.seen.some((s) => typeof s !== 'string')) return null
  if (typeof b.sound !== 'boolean') return null
  if (b.speed !== 1 && b.speed !== 2) return null
  if (!b.stats || typeof b.stats !== 'object') return null
  const stats = b.stats
  for (const k of ['games', 'wins', 'kills', 'bossKills', 'gold', 'maxTowers'] as const) {
    if (!isInt(stats[k])) return null
  }
  if (stats.wins > stats.games) return null
  if (!Array.isArray(b.usedTowers) || b.usedTowers.length > 7) return null
  const usedTowers: TowerKind[] = []
  for (const t of b.usedTowers) {
    const def = towerDefOrNull(t)
    if (!def || usedTowers.includes(def.kind)) return null
    usedTowers.push(def.kind)
  }
  return {
    v: 1, stars, endlessBest: b.endlessBest, achievements, seen: [...new Set(b.seen)],
    sound: b.sound, speed: b.speed, stats: { ...stats }, usedTowers,
  }
}

/**
 * 两台设备的档案合并:星级逐关取高、无尽取高、成就和看过的提示取并集、统计逐项取大。
 * 设置(声音/倍速)跟游戏场次多的那台走。
 */
export function mergeBest(a: Best, b: Best): Best {
  const stars: Record<string, number> = { ...a.stars }
  for (const [k, v] of Object.entries(b.stars)) stars[k] = Math.max(stars[k] || 0, v)
  const big = b.stats.games > a.stats.games ? b : a
  const used = [...a.usedTowers]
  for (const t of b.usedTowers) if (!used.includes(t)) used.push(t)
  const achievements = ACHIEVEMENTS.map((x) => x.id).filter((id) =>
    a.achievements.includes(id) || b.achievements.includes(id))
  return {
    v: 1,
    stars,
    endlessBest: Math.max(a.endlessBest, b.endlessBest),
    achievements,
    seen: [...new Set([...a.seen, ...b.seen])],
    sound: big.sound,
    speed: big.speed,
    stats: {
      games: Math.max(a.stats.games, b.stats.games),
      wins: Math.max(a.stats.wins, b.stats.wins),
      kills: Math.max(a.stats.kills, b.stats.kills),
      bossKills: Math.max(a.stats.bossKills, b.stats.bossKills),
      gold: Math.max(a.stats.gold, b.stats.gold),
      maxTowers: Math.max(a.stats.maxTowers, b.stats.maxTowers),
    },
    usedTowers: used,
  }
}

/** 这一关拿过几星(没打过 0) */
export function levelStars(best: Best, id: number): number {
  return best.stars[String(id)] || 0
}

/** 这一关解锁了吗:第 1 关永远解锁,后面一关要前一关通关 */
export function levelUnlocked(best: Best, id: number): boolean {
  if (id <= 1) return true
  if (id > MAX_LEVEL_ID) return false
  return levelStars(best, id - 1) > 0
}

/** 全部关卡都通关了吗(不限星级) */
export function allCleared(best: Best): boolean {
  return LEVELS.every((l) => levelStars(best, l.id as number) > 0)
}

/** 无尽模式:通关第 12 关后解锁 */
export function endlessUnlocked(best: Best): boolean {
  return levelStars(best, MAX_LEVEL_ID) > 0
}

/** 一共多少星(满 36) */
export function totalStars(best: Best): number {
  return LEVELS.reduce((sum, l) => sum + levelStars(best, l.id as number), 0)
}

/** 「继续」按钮去哪一关:第一关还没通关的(都已通关就去最后一关) */
export function nextLevelId(best: Best): number {
  for (const l of LEVELS) {
    const id = l.id as number
    if (levelStars(best, id) === 0 && levelUnlocked(best, id)) return id
  }
  return MAX_LEVEL_ID
}

/** 新手提示看过没有 */
export function hasSeen(best: Best, tag: string): boolean {
  return best.seen.includes(tag)
}

/** 记下看过的新手提示(没变就返回原对象) */
export function markSeen(best: Best, tag: string): Best {
  if (best.seen.includes(tag)) return best
  return { ...best, seen: [...best.seen, tag] }
}

/** 记下这一局用过的塔(给「七种武器」成就) */
function mergeUsed(best: Best, kinds: readonly TowerKind[]): TowerKind[] {
  const out = [...best.usedTowers]
  for (const k of kinds) if (!out.includes(k)) out.push(k)
  return out
}

/**
 * 一局结束:更新星级、无尽最高波数、累计统计、用过的塔,再判一次成就。
 * 输了也记场次和击杀,但不动星级;返回新档案和新解锁的成就 id。
 */
export function recordResult(best: Best, result: RunResult): { best: Best; unlocked: string[] } {
  const key = result.levelId === 'endless' ? null : String(result.levelId)
  const stars = { ...best.stars }
  if (key && result.won) stars[key] = Math.max(stars[key] || 0, Math.max(1, Math.min(3, result.stars)))
  const endlessBest = result.levelId === 'endless'
    ? Math.max(best.endlessBest, result.endlessWave)
    : best.endlessBest
  const next: Best = {
    ...best,
    stars,
    endlessBest,
    stats: {
      games: best.stats.games + 1,
      wins: best.stats.wins + (result.won ? 1 : 0),
      kills: best.stats.kills + result.kills,
      bossKills: best.stats.bossKills + result.bossKills,
      gold: best.stats.gold + result.goldEarned,
      maxTowers: Math.max(best.stats.maxTowers, result.built),
    },
    usedTowers: mergeUsed(best, result.towerKinds),
  }
  return claimAchievements(next)
}

/** 满足条件的成就全部点亮;返回新档案和新点亮的 id(已经点过的不重复给) */
export function claimAchievements(best: Best): { best: Best; unlocked: string[] } {
  const got: string[] = []
  for (const a of ACHIEVEMENTS) {
    if (!best.achievements.includes(a.id) && meets(a.id, best)) got.push(a.id)
  }
  if (!got.length) return { best, unlocked: got }
  return {
    best: { ...best, achievements: ACHIEVEMENTS.map((a) => a.id).filter((id) =>
      best.achievements.includes(id) || got.includes(id)) },
    unlocked: got,
  }
}

/** 成就的判定条件(集中在一处,测试逐条覆盖) */
export function meets(id: string, best: Best): boolean {
  switch (id) {
    case 'first_win': return best.stats.wins >= 1
    case 'first_build': return best.stats.maxTowers >= 1
    case 'flawless': return Object.values(best.stars).some((s) => s >= 3)
    case 'garden_full': return [1, 2, 3, 4].every((id2) => levelStars(best, id2) >= 3)
    case 'orchard_guard': return levelStars(best, 8) >= 1
    case 'night_walker': return levelStars(best, 12) >= 1
    case 'boss_hunter': return best.stats.bossKills >= 3
    case 'tower_master': return best.stats.maxTowers >= 12
    case 'all_towers': return best.usedTowers.length >= 7
    case 'endless_10': return best.endlessBest >= 10
    case 'endless_20': return best.endlessBest >= 20
    case 'rich_farmer': return best.stats.gold >= 5000
    default: return false
  }
}

/** 关卡名(列表页与结算页用) */
export function levelName(id: number | 'endless'): string {
  if (id === 'endless') return '无尽瓜田'
  const l = LEVELS.find((x) => x.id === id)
  return l ? l.name : `第 ${id} 关`
}
