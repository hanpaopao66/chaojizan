// 存档里的战绩与设置。和界面无关的纯函数:读坏档返回 null,两台设备合并时各项取大的,输赢记连胜。
//
// 只存「自己的成绩」:场次、胜、负、当前连胜、最佳连胜、累计击杀/安放/开枪/命中,以及难度和声音开关。
// 不存进行中的比赛 —— 回合制,关掉就从首页开新局(「关于」里写清楚了)。

import { Difficulty } from './combat'
import { DEFAULT_MAP_ID, MAP_IDS, MapId } from './map'

export const PROFILE_VERSION = 2

export interface Profile {
  v: 2
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
  /** 上次选的地图 */
  mapId: MapId
  /** 已解锁的成就 id */
  achievements: string[]
  /**
   * 存档是比当前客户端更新的版本写的:只读,不回写。
   * 不写进存档本身(loadProfile 发现 v > PROFILE_VERSION 时才标上)。
   */
  future?: boolean
}

export const EMPTY_PROFILE: Profile = {
  v: 2,
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
  mapId: DEFAULT_MAP_ID,
  achievements: [],
}

const MAX_COUNT = 999999

function count(value: unknown, fallback = 0): number {
  const n = typeof value === 'number' && Number.isFinite(value) ? Math.floor(value) : fallback
  return Math.min(MAX_COUNT, Math.max(0, n))
}

/** 存档里的一坨东西 → Profile;认 1.0 的 v1(补默认字段迁移到 v2);未知版本只读 */
export function loadProfile(raw: unknown): Profile | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const version = typeof r.v === 'number' && Number.isFinite(r.v) ? r.v : NaN
  if (!Number.isFinite(version) || version < 1) return null
  const parsed: Profile = {
    v: PROFILE_VERSION,
    games: count(r.games),
    wins: count(r.wins),
    losses: count(r.losses),
    streak: count(r.streak),
    bestStreak: count(r.bestStreak),
    kills: count(r.kills),
    plants: count(r.plants),
    shots: count(r.shots),
    hits: count(r.hits),
    // v1 没有 mapId / achievements:补默认值(迁移)
    difficulty: r.difficulty === 'hard' ? 'hard' : r.difficulty === 'casual' ? 'casual' : 'normal',
    sound: r.sound !== false,
    mapId: MAP_IDS.indexOf(r.mapId as MapId) >= 0 ? (r.mapId as MapId) : DEFAULT_MAP_ID,
    achievements: Array.isArray(r.achievements)
      ? r.achievements.filter((a): a is string => typeof a === 'string').slice(0, 64)
      : [],
  }
  if (version > PROFILE_VERSION) parsed.future = true
  return parsed
}

/** Profile → 能 JSON 序列化的存档。现在的版本是 v2(v1 客户端读不动,由 v2 客户端迁移旧的) */
export function saveProfile(p: Profile): unknown {
  return {
    v: PROFILE_VERSION,
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
    mapId: p.mapId,
    achievements: p.achievements,
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
  // 未来版本的存档:内容看不懂,原样保留、绝不合并出可回写的正常档
  if (isFuture(local)) return local
  if (isFuture(cloud)) return { ...cloud }
  const fresh = local.games === 0 && local.kills === 0
  // 两台设备上的胜负都只增不减,合并后「至少赢过 wins 场、至少输过 losses 场」;
  // 场次不能少于胜负之和,否则会出现「4 场 3 胜 4 负」这种自相矛盾的存档。
  const wins = bigger(local.wins, cloud.wins)
  const losses = bigger(local.losses, cloud.losses)
  return {
    v: PROFILE_VERSION,
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
    mapId: fresh ? cloud.mapId : local.mapId,
    // 成就是「达成过就永久保留」:两台设备取并集
    achievements: Array.from(new Set([...local.achievements, ...cloud.achievements])).sort(),
  }
}

/** 比本客户端更新的存档:不要回写,只读展示 */
export function isFuture(p: Profile): boolean {
  return p.future === true
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

/** 解锁一批成就;返回新 Profile(已经全都有了就返回原对象) */
export function unlockAchievements(p: Profile, ids: readonly string[]): Profile {
  const merged = Array.from(new Set([...p.achievements, ...ids])).sort()
  if (merged.length === p.achievements.length) return p
  return { ...p, achievements: merged }
}

/** 换地图;地图没变就返回原对象 */
export function withMap(p: Profile, mapId: MapId): Profile {
  return p.mapId === mapId ? p : { ...p, mapId }
}
