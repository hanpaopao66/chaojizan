// 成就判定:纯函数。统计型成就看 profile 里的累计数;条件型看成运行时状态(高度、地形、连击…)。
//
// 判定只在「可能变化」的时候跑(挖/放/每 0.4 秒),不会每帧遍历 13 个成就。
import { ACHIEVEMENTS, type AchievementDef } from './data'
import type { Profile } from './profile'
import { unlock } from './profile'

/** 三种地形:踩到过草地 / 沙滩 / 石地 */
export const BIOME_GRASS = 1
export const BIOME_SAND = 2
export const BIOME_STONE = 4
export const BIOME_ALL = BIOME_GRASS | BIOME_SAND | BIOME_STONE

/** 条件型成就判定要看的运行时状态 */
export interface AchievementContext {
  /** 玩家脚底高度 */
  y: number
  /** 踩到过的地形位掩码 */
  biomeMask: number
  /** 九格快捷栏的数量(满热栏用) */
  inv: readonly number[]
  /** 当前连续挖掉多少块(按住挖不松手) */
  streak: number
  /** 夜里挖掉多少块 */
  nightMined: number
  /** 连续在水里待了多少秒 */
  swimSeconds: number
  /** 最高站到过多高 */
  maxY: number
}

export function emptyContext(): AchievementContext {
  return { y: 0, biomeMask: 0, inv: [], streak: 0, nightMined: 0, swimSeconds: 0, maxY: 0 }
}

const statValue = (p: Profile, def: AchievementDef): number => {
  if (!def.stat) return 0
  return p[def.stat]
}

/** 这个成就现在满足条件了吗(已解锁的当然算满足) */
export function met(def: AchievementDef, p: Profile, ctx: AchievementContext): boolean {
  if (def.stat) return statValue(p, def) >= def.goal
  switch (def.condition) {
    case 'tower40':
      return ctx.maxY >= 40
    case 'biomes3':
      return (ctx.biomeMask & BIOME_ALL) === BIOME_ALL
    case 'streak50':
      return ctx.streak >= 50
    case 'hotbarFull':
      return ctx.inv.length > 0 && ctx.inv.every((n) => n > 0)
    case 'nightMine10':
      return ctx.nightMined >= 10
    case 'swim10':
      return ctx.swimSeconds >= 10
    default:
      return false
  }
}

/** 当前还差多少 / 是否完成,给成就面板显示进度用 */
export function achievementProgress(def: AchievementDef, p: Profile, ctx: AchievementContext): {
  current: number
  goal: number
  done: boolean
} {
  const done = p.achievements[def.id] !== undefined
  if (def.stat) {
    return { current: Math.min(def.goal, statValue(p, def)), goal: def.goal, done }
  }
  let current = 0
  switch (def.condition) {
    case 'tower40': current = Math.min(40, ctx.maxY); break
    case 'biomes3': current = [BIOME_GRASS, BIOME_SAND, BIOME_STONE].filter((b) => (ctx.biomeMask & b) !== 0).length; break
    case 'streak50': current = Math.min(50, ctx.streak); break
    case 'hotbarFull': current = ctx.inv.filter((n) => n > 0).length; break
    case 'nightMine10': current = Math.min(10, ctx.nightMined); break
    case 'swim10': current = Math.min(10, Math.floor(ctx.swimSeconds)); break
    default: current = 0
  }
  const goal = def.condition === 'tower40' ? 40 : def.condition === 'streak50' ? 50
    : def.condition === 'nightMine10' ? 10 : def.condition === 'swim10' ? 10
      : def.condition === 'hotbarFull' ? 9 : 3
  return { current, goal, done }
}

/**
 * 检查一遍,把新满足的成就解锁进 profile。
 * 直接改 profile(游戏里每帧都可能调),返回这次新解锁的定义列表给界面弹提示。
 */
export function checkAchievements(p: Profile, ctx: AchievementContext, now: number): AchievementDef[] {
  const unlocked: AchievementDef[] = []
  for (const def of ACHIEVEMENTS) {
    if (p.achievements[def.id] !== undefined) continue
    if (!met(def, p, ctx)) continue
    if (unlock(p, def.id, now)) unlocked.push(def)
  }
  return unlocked
}
