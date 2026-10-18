// 存档里的战绩与设置。和界面无关的纯函数:读坏档返回 null,两台设备合并时各项取大的,输赢记连胜。
//
// 只存「自己的成绩」:场次、胜、负、当前连胜、最佳连胜、累计击杀/安放/开枪/命中,以及难度和声音开关。
// 不存进行中的比赛 —— 回合制,关掉就从首页开新局(「关于」里写清楚了)。

import { Difficulty } from './combat'

export interface Profile {
  v: 1
  games: number
  wins: number
  losses: number
  /** 当前连胜(输了清零) */
  streak: number
  /** 最佳连胜 */
  bestStreak: number
  kills: number
  plants: number
  shots: number
  hits: number
  /** 上一次选的难度 */
  difficulty: Difficulty
  /** 声音开关 */
  sound: boolean
}

export const EMPTY_PROFILE: Profile = {
  v: 1,
  games: 0,
  wins: 0,
  losses: 0,
  streak: 0,
  bestStreak: 0,
  kills: 0,
  plants: 0,
  shots: 0,
  hits: 0,
  difficulty: 'normal',
  sound: true,
}

const MAX_COUNT = 999999

function count(value: unknown, fallback = 0): number {
  const n = typeof value === 'number' && Number.isFinite(value) ? Math.floor(value) : fallback
  return Math.min(MAX_COUNT, Math.max(0, n))
}

/** 存档里的一坨东西 → Profile;版本不对或者根本不是对象就返回 null(当作没有存档) */
export function loadProfile(raw: unknown): Profile | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (r.v !== 1) return null
  return {
    v: 1,
    games: count(r.games),
    wins: count(r.wins),
    losses: count(r.losses),
    streak: count(r.streak),
    bestStreak: count(r.bestStreak),
    kills: count(r.kills),
    plants: count(r.plants),
    shots: count(r.shots),
    hits: count(r.hits),
    difficulty: r.difficulty === 'hard' ? 'hard' : r.difficulty === 'casual' ? 'casual' : 'normal',
    sound: r.sound !== false,
  }
}

/** Profile → 能 JSON 序列化的存档。字段写清楚,方便以后加版本号迁移 */
export function saveProfile(p: Profile): unknown {
  return {
    v: 1,
    games: p.games,
    wins: p.wins,
    losses: p.losses,
    streak: p.streak,
    bestStreak: p.bestStreak,
    kills: p.kills,
    plants: p.plants,
    shots: p.shots,
    hits: p.hits,
    difficulty: p.difficulty,
    sound: p.sound,
  }
}

function bigger(a: number, b: number): number {
  return Math.max(a, b)
}

/**
 * 两台设备各有一份存档:场次、胜负、累计数据都取大的(谁打得多听谁的);
 * 当前连胜和设置跟这台设备(本地那份),本地还没打过就听云端的。
 */
export function mergeProfile(local: Profile, cloud: Profile): Profile {
  const fresh = local.games === 0 && local.kills === 0
  // 两台设备上的胜负都只增不减,合并后「至少赢过 wins 场、至少输过 losses 场」;
  // 场次不能少于胜负之和,否则会出现「4 场 3 胜 4 负」这种自相矛盾的存档。
  const wins = bigger(local.wins, cloud.wins)
  const losses = bigger(local.losses, cloud.losses)
  return {
    v: 1,
    games: Math.max(bigger(local.games, cloud.games), wins + losses),
    wins,
    losses,
    streak: fresh ? cloud.streak : local.streak,
    bestStreak: bigger(local.bestStreak, cloud.bestStreak),
    kills: bigger(local.kills, cloud.kills),
    plants: bigger(local.plants, cloud.plants),
    shots: bigger(local.shots, cloud.shots),
    hits: bigger(local.hits, cloud.hits),
    difficulty: fresh ? cloud.difficulty : local.difficulty,
    sound: fresh ? cloud.sound : local.sound,
  }
}

export interface MatchResult {
  won: boolean
  kills: number
  plants: number
  shots: number
  hits: number
}

/** 一场比赛结束:记场次、胜负、连胜、累计数据。难度用这一场实际选的 */
export function recordMatch(p: Profile, result: MatchResult): Profile {
  const streak = result.won ? p.streak + 1 : 0
  return {
    ...p,
    games: p.games + 1,
    wins: p.wins + (result.won ? 1 : 0),
    losses: p.losses + (result.won ? 0 : 1),
    streak,
    bestStreak: Math.max(p.bestStreak, streak),
    kills: p.kills + count(result.kills),
    plants: p.plants + count(result.plants),
    shots: p.shots + count(result.shots),
    hits: p.hits + count(result.hits),
  }
}

/** 命中率(0..1;没开枪就是 0) */
export function accuracy(p: Pick<Profile, 'hits' | 'shots'>): number {
  return p.shots === 0 ? 0 : p.hits / p.shots
}

/** 设置:难度和声音。和战绩一起存,换设备也跟过来 */
export function withSettings(p: Profile, difficulty: Difficulty, sound: boolean): Profile {
  if (p.difficulty === difficulty && p.sound === sound) return p
  return { ...p, difficulty, sound }
}
