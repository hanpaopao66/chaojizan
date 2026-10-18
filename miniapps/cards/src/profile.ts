// 战绩档案:总场次、胜场、当前连胜、最佳连胜,以及上次选的英雄和难度。
// 和界面无关,读档/坏档兜底/两台设备合并都在这里,单测直接调用。
import { heroOrNull } from './data'
import type { Level } from './types'

export interface Profile {
  v: 1
  /** 一共打了几局 */
  games: number
  /** 赢了几局 */
  wins: number
  /** 当前连胜(输一局清零) */
  streak: number
  /** 最佳连胜 */
  bestStreak: number
  /** 上次用的英雄(卡组) */
  lastHero: string
  lastLevel: Level
}

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0

export function newProfile(): Profile {
  return { v: 1, games: 0, wins: 0, streak: 0, bestStreak: 0, lastHero: 'forge', lastLevel: 'normal' }
}

/** 读档案;坏的、版本不对的返回 null(当作全新档案) */
export function loadProfile(raw: unknown): Profile | null {
  const p = raw as Profile
  if (!p || typeof p !== 'object' || p.v !== 1) return null
  if (!isInt(p.games) || !isInt(p.wins) || !isInt(p.streak) || !isInt(p.bestStreak)) return null
  if (p.wins > p.games || p.streak > p.games || p.bestStreak < p.streak) return null
  if (!heroOrNull(p.lastHero)) return null
  if (p.lastLevel !== 'normal' && p.lastLevel !== 'hard') return null
  return p
}

/**
 * 两台设备的档案合成一份。场次和胜场取大的而不是相加 —— 同一个账号在两台设备上各打了几局,
 * 相加会把「两边看到的是同一份云端档案」的场次重复计算;连胜/最佳连胜也取大的。
 * 宁可少记,不要多算。上次选择跟场次多的那台走。
 */
export function mergeProfile(a: Profile, b: Profile): Profile {
  const big = b.games > a.games ? b : a
  return {
    v: 1,
    games: Math.max(a.games, b.games),
    wins: Math.max(a.wins, b.wins),
    streak: Math.max(a.streak, b.streak),
    bestStreak: Math.max(a.bestStreak, b.bestStreak),
    lastHero: big.lastHero,
    lastLevel: big.lastLevel,
  }
}

/** 一局结束:记场次、输赢和连胜 */
export function recordResult(p: Profile, won: boolean, hero: string, level: Level): Profile {
  const streak = won ? p.streak + 1 : 0
  return {
    v: 1,
    games: p.games + 1,
    wins: p.wins + (won ? 1 : 0),
    streak,
    bestStreak: Math.max(p.bestStreak, streak),
    lastHero: hero,
    lastLevel: level,
  }
}

/** 点开始对局时记一下这次的选择(输了赢了都记,下次打开还是这套) */
export function rememberChoice(p: Profile, hero: string, level: Level): Profile {
  if (p.lastHero === hero && p.lastLevel === level) return p
  return { ...p, lastHero: hero, lastLevel: level }
}
