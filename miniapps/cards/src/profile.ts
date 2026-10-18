// 战绩档案 v2:场次、胜场、连胜之外,再记成就需要的累计数(斩杀胜、疲劳胜、单局最高伤害/出牌、满血胜、困难胜、每套牌胜场)
// 和上次选的英雄 / 难度。和界面无关;坏档、v1 旧档都在这里兜住。
import { heroOrNull, LEVELS } from './data'
import type { Level, OverReason } from './types'

export interface Profile {
  v: 2
  /** 一共打了几局 */
  games: number
  /** 赢了几局 */
  wins: number
  /** 当前连胜(输一局清零) */
  streak: number
  /** 最佳连胜 */
  bestStreak: number
  /** 每套卡组各赢过几局(hero id → 胜场) */
  winsByHero: Record<string, number>
  /** 把对面英雄打到 0 的胜局数(成就:斩杀 10 次) */
  lethals: number
  /** 对面被疲劳伤害耗死的胜局数 */
  fatigueWins: number
  /** 单局对敌方造成的最高伤害 */
  maxDealt: number
  /** 单局最多出了几张牌 */
  maxPlayed: number
  /** 满血(30 点)获胜的次数 */
  flawlessWins: number
  /** 困难难度获胜次数 */
  hardWins: number
  /** 新手提示看过没有(首局内联提示) */
  tutorialSeen: boolean
  /** 已经解锁的成就 id */
  achievements: string[]
  /** 上次用的英雄(卡组) */
  lastHero: string
  lastLevel: Level
}

/** 一局结束时要记下来的东西(结算页和档案都用) */
export interface Outcome {
  won: boolean
  draw: boolean
  hero: string
  level: Level
  reason: OverReason
  /** 结束时我方英雄剩多少血 */
  myHp: number
  /** 这局对敌方造成的总伤害 */
  dealt: number
  /** 这局出了几张牌 */
  played: number
}

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0

export function newProfile(): Profile {
  return {
    v: 2, games: 0, wins: 0, streak: 0, bestStreak: 0, winsByHero: {}, lethals: 0, fatigueWins: 0,
    maxDealt: 0, maxPlayed: 0, flawlessWins: 0, hardWins: 0, tutorialSeen: false, achievements: [],
    lastHero: 'forge', lastLevel: 'normal',
  }
}

function normalizeAchievements(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  return v.filter((x): x is string => typeof x === 'string' && /^[a-z0-9_]{1,40}$/.test(x))
}

function normalizeWinsByHero(v: unknown): Record<string, number> {
  const out: Record<string, number> = {}
  if (v && typeof v === 'object') {
    for (const [k, n] of Object.entries(v as Record<string, unknown>)) {
      if (heroOrNull(k) && isInt(n)) out[k] = n
    }
  }
  return out
}

/** 读档案:v2 校验字段;v1 旧档补齐新字段(升级不丢战绩);坏的返回 null(当作全新档案) */
export function loadProfile(raw: unknown): Profile | null {
  if (!raw || typeof raw !== 'object') return null
  const p = raw as Record<string, unknown>
  if (p.v !== 1 && p.v !== 2) return null
  if (!isInt(p.games) || !isInt(p.wins) || !isInt(p.streak) || !isInt(p.bestStreak)) return null
  if (p.wins > p.games || p.streak > p.games || p.bestStreak < p.streak) return null
  if (!heroOrNull(p.lastHero)) return null
  if (LEVELS.indexOf(p.lastLevel as Level) < 0) return null
  const base = newProfile()
  if (p.v === 1) {
    return {
      ...base, games: p.games, wins: p.wins, streak: p.streak, bestStreak: p.bestStreak,
      lastHero: p.lastHero as string, lastLevel: p.lastLevel as Level,
    }
  }
  if (!isInt(p.lethals) || !isInt(p.fatigueWins) || !isInt(p.maxDealt) || !isInt(p.maxPlayed)
    || !isInt(p.flawlessWins) || !isInt(p.hardWins) || typeof p.tutorialSeen !== 'boolean') return null
  if (p.lethals > p.wins || p.fatigueWins > p.wins || p.flawlessWins > p.wins || p.hardWins > p.wins) return null
  return {
    ...base,
    games: p.games, wins: p.wins, streak: p.streak, bestStreak: p.bestStreak,
    winsByHero: normalizeWinsByHero(p.winsByHero),
    lethals: p.lethals, fatigueWins: p.fatigueWins, maxDealt: p.maxDealt, maxPlayed: p.maxPlayed,
    flawlessWins: p.flawlessWins, hardWins: p.hardWins, tutorialSeen: p.tutorialSeen,
    achievements: normalizeAchievements(p.achievements),
    lastHero: p.lastHero as string, lastLevel: p.lastLevel as Level,
  }
}

/**
 * 两台设备的档案合成一份。场次和胜场取大的而不是相加 —— 同一个账号在两台设备上各打了几局,
 * 相加会把「两边看到的是同一份云端档案」的场次重复计算;单项累计也取大的。
 * 成就取并集,新手提示看过就看过。宁可少记,不要多算。
 */
export function mergeProfile(a: Profile, b: Profile): Profile {
  const big = b.games > a.games ? b : a
  const winsByHero: Record<string, number> = { ...a.winsByHero }
  for (const [k, n] of Object.entries(b.winsByHero)) winsByHero[k] = Math.max(winsByHero[k] || 0, n)
  return {
    v: 2,
    games: Math.max(a.games, b.games),
    wins: Math.max(a.wins, b.wins),
    streak: Math.max(a.streak, b.streak),
    bestStreak: Math.max(a.bestStreak, b.bestStreak),
    winsByHero,
    lethals: Math.max(a.lethals, b.lethals),
    fatigueWins: Math.max(a.fatigueWins, b.fatigueWins),
    maxDealt: Math.max(a.maxDealt, b.maxDealt),
    maxPlayed: Math.max(a.maxPlayed, b.maxPlayed),
    flawlessWins: Math.max(a.flawlessWins, b.flawlessWins),
    hardWins: Math.max(a.hardWins, b.hardWins),
    tutorialSeen: a.tutorialSeen || b.tutorialSeen,
    achievements: Array.from(new Set([...a.achievements, ...b.achievements])).sort(),
    lastHero: big.lastHero,
    lastLevel: big.lastLevel,
  }
}

/** 一局结束:记场次、输赢、连胜和成就要用的累计数(成就解锁在 achievements.ts 里判) */
export function recordResult(p: Profile, o: Outcome): Profile {
  const streak = o.won ? p.streak + 1 : 0
  const winsByHero = { ...p.winsByHero }
  if (o.won) winsByHero[o.hero] = (winsByHero[o.hero] || 0) + 1
  return {
    ...p,
    games: p.games + 1,
    wins: p.wins + (o.won ? 1 : 0),
    streak,
    bestStreak: Math.max(p.bestStreak, streak),
    winsByHero,
    lethals: p.lethals + (o.won && o.reason === 'hp' ? 1 : 0),
    fatigueWins: p.fatigueWins + (o.won && o.reason === 'fatigue' ? 1 : 0),
    maxDealt: Math.max(p.maxDealt, o.dealt),
    maxPlayed: Math.max(p.maxPlayed, o.played),
    flawlessWins: p.flawlessWins + (o.won && o.myHp >= 30 ? 1 : 0),
    hardWins: p.hardWins + (o.won && o.level === 'hard' ? 1 : 0),
    lastHero: o.hero,
    lastLevel: o.level,
  }
}

/** 点开始对局时记一下这次的选择(输了赢了都记,下次打开还是这套) */
export function rememberChoice(p: Profile, hero: string, level: Level): Profile {
  if (p.lastHero === hero && p.lastLevel === level) return p
  return { ...p, lastHero: hero, lastLevel: level }
}

/** 首局新手提示:看过就不再弹 */
export function markTutorialSeen(p: Profile): Profile {
  if (p.tutorialSeen) return p
  return { ...p, tutorialSeen: true }
}

/** 把新解锁的成就写进档案(已经有的不重复写) */
export function withAchievements(p: Profile, ids: string[]): Profile {
  if (ids.length === 0) return p
  const have = new Set(p.achievements)
  for (const id of ids) have.add(id)
  return { ...p, achievements: Array.from(have).sort() }
}
