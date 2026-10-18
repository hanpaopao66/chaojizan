// 跨局/跨设备保留的玩家档案:累计统计 + 已解锁成就。
//
// 这份档案存进 SaveSlot 的 **best** 槽:两台设备之合并时统计取较大值、成就取并集,
// 所以挖了多少、走了多少不会因为换了设备而丢或翻倍。世界本身的存档还是「谁新用谁」。
import { ACHIEVEMENTS } from './data'
import { LIMITS } from './data'

export interface Profile {
  v: 2
  /** 累计挖掉多少方块 */
  mined: number
  /** 累计放下多少方块 */
  placed: number
  /** 累计走了多少米 */
  walked: number
  /** 累计游玩时长(秒) */
  seconds: number
  /** 已解锁成就:id → 解锁时间(毫秒时间戳) */
  achievements: Record<string, number>
}

/** 统计字段名,给增量更新用 */
export type StatKey = 'mined' | 'placed' | 'walked' | 'seconds'

const MAX_STAT = 1e9
const ACHIEVEMENT_IDS = new Set(ACHIEVEMENTS.map((a) => a.id))

export function emptyProfile(): Profile {
  return { v: 2, mined: 0, placed: 0, walked: 0, seconds: 0, achievements: {} }
}

/** 深拷贝一份档案(游戏里会就地改,存档槽里要留一份用于比较/合并) */
export function copyProfile(p: Profile): Profile {
  return {
    v: 2, mined: p.mined, placed: p.placed, walked: p.walked, seconds: p.seconds,
    achievements: { ...p.achievements },
  }
}

const isStat = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= MAX_STAT

/** 读档;坏档返回 null(当作没有档案)。旧版空的 {v:1} 也当空档案。 */
export function loadProfile(raw: unknown): Profile | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (r.v === 1) return emptyProfile()
  if (r.v !== 2) return null
  if (!isStat(r.mined) || !isStat(r.placed) || !isStat(r.walked) || !isStat(r.seconds)) return null
  const ach = r.achievements
  if (!ach || typeof ach !== 'object' || Array.isArray(ach)) return null
  const achievements: Record<string, number> = {}
  for (const [id, at] of Object.entries(ach as Record<string, unknown>)) {
    // 不认识的成就 id 丢掉(换版本不崩);时间是坏的就用 1 兜底
    if (!ACHIEVEMENT_IDS.has(id)) continue
    achievements[id] = isStat(at) && at > 0 ? Math.floor(at) : 1
  }
  return {
    v: 2,
    mined: Math.floor(r.mined),
    placed: Math.floor(r.placed),
    walked: Math.round(r.walked * 100) / 100,
    seconds: Math.round(r.seconds * 100) / 100,
    achievements,
  }
}

/** Profile → 可以直接 JSON.stringify 的普通对象(字段拷贝,防止写出去后被内存改到) */
export function profileOf(p: Profile): unknown {
  return {
    v: 2,
    mined: Math.floor(p.mined),
    placed: Math.floor(p.placed),
    walked: Math.round(p.walked * 100) / 100,
    seconds: Math.round(p.seconds * 100) / 100,
    achievements: { ...p.achievements },
  }
}

/** 两台设备的档案合并:统计取大、成就取并集(解锁时间取更早的) */
export function mergeProfile(a: Profile, b: Profile): Profile {
  const achievements: Record<string, number> = { ...a.achievements }
  for (const [id, at] of Object.entries(b.achievements)) {
    const old = achievements[id]
    achievements[id] = old === undefined ? at : Math.min(old, at)
  }
  return {
    v: 2,
    mined: Math.max(a.mined, b.mined),
    placed: Math.max(a.placed, b.placed),
    walked: Math.max(a.walked, b.walked),
    seconds: Math.max(a.seconds, b.seconds),
    achievements,
  }
}

/** 给统计加一笔。浮点先原样累计(每帧都四舍五入会累积误差),写档时再收成两位小数 */
export function addStat(p: Profile, key: StatKey, delta: number): void {
  if (!(delta > 0)) return
  const next = p[key] + delta
  p[key] = Math.min(MAX_STAT, key === 'mined' || key === 'placed' ? Math.floor(next) : next)
}

/** 解锁一个成就;已经解锁过就返回 false(不覆盖原来的时间) */
export function unlock(p: Profile, id: string, at: number): boolean {
  if (!ACHIEVEMENT_IDS.has(id)) return false
  if (p.achievements[id] !== undefined) return false
  p.achievements[id] = Math.max(1, Math.floor(at))
  return true
}

export function isUnlocked(p: Profile, id: string): boolean {
  return p.achievements[id] !== undefined
}

export function unlockedCount(p: Profile): number {
  return Object.keys(p.achievements).length
}

export function totalAchievements(): number {
  return ACHIEVEMENT_IDS.size
}

/** 「1 小时 23 分」/「23 分 5 秒」/「45 秒」——统计面板用 */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s} 秒`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分 ${s % 60} 秒`
  const h = Math.floor(m / 60)
  return `${h} 小时 ${m % 60} 分`
}

/** 「123 米」/「1.2 公里」 */
export function formatDistance(metres: number): string {
  const m = Math.max(0, Math.round(metres))
  if (m < 1000) return `${m} 米`
  return `${(m / 1000).toFixed(1)} 公里`
}

/** 改动容量显示用:「3600 / 4000 格」 */
export function formatEdits(count: number): string {
  return `${count} / ${LIMITS.MAX_EDITS} 格`
}
