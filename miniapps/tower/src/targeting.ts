// 索敌:算敌人位置、找「走到最前面」的那只、链电的下一个目标、溅射范围。
// 纯函数,不碰 DOM;engine.ts 每一步都从这里取位置和目标,render.ts 也从这里取位置。
import { TILE, cellCenter, enemyDef, pointAt } from './data'
import type { Enemy, LevelDef, Vec } from './types'

/** 敌人现在在世界的哪儿:地面虫沿折线走,飞行虫从入口直线飞向西瓜 */
export function enemyPos(level: LevelDef, e: Enemy): Vec {
  const start = level.world.starts[e.path] || level.world.starts[0]
  const target = level.world.target
  if (enemyDef(e.kind).flying) {
    const t = e.span <= 0 ? 1 : Math.min(1, Math.max(0, e.dist / e.span))
    return { x: start.x + (target.x - start.x) * t, y: start.y + (target.y - start.y) * t }
  }
  const poly = level.world.polys[e.path] || level.world.polys[0]
  return pointAt(poly, e.dist)
}

/** 走到多远了(0–1);索敌用「进度最靠前」,飞行虫按直线距离算 */
export function progressOf(e: Enemy): number {
  if (e.span <= 0) return 0
  return Math.min(1, Math.max(0, e.dist / e.span))
}

/** 建造位的世界坐标 */
export function slotPos(level: LevelDef, slot: number): Vec {
  const s = level.slots[slot]
  return s ? cellCenter(s) : { x: 0, y: 0 }
}

/** 塔的射程(格 → 世界像素) */
export function rangePx(tiles: number): number {
  return tiles * TILE
}

export function inRange(level: LevelDef, e: Enemy, from: Vec, radiusPx: number): boolean {
  const p = enemyPos(level, e)
  const dx = p.x - from.x
  const dy = p.y - from.y
  return dx * dx + dy * dy <= radiusPx * radiusPx
}

/**
 * 射程内「走到最前面」的敌人;一样靠前的按 id 小的优先(结果可复现)。
 * skip 里的 id 跳过(链电用)。
 */
export function pickTarget(level: LevelDef, enemies: readonly Enemy[], from: Vec, radiusPx: number,
  skip?: ReadonlySet<number>): Enemy | null {
  let best: Enemy | null = null
  let bestProgress = -1
  for (const e of enemies) {
    if (e.hp <= 0 || (skip && skip.has(e.id))) continue
    if (!inRange(level, e, from, radiusPx)) continue
    const p = progressOf(e)
    if (p > bestProgress || (p === bestProgress && best !== null && e.id < best.id)) {
      best = e
      bestProgress = p
    }
  }
  return best
}

/** 溅射:以 center 为圆心、radiusPx 内的所有活虫 */
export function enemiesInRadius(level: LevelDef, enemies: readonly Enemy[], center: Vec, radiusPx: number,
  skip?: ReadonlySet<number>): Enemy[] {
  const out: Enemy[] = []
  for (const e of enemies) {
    if (e.hp <= 0 || (skip && skip.has(e.id))) continue
    const p = enemyPos(level, e)
    const dx = p.x - center.x
    const dy = p.y - center.y
    if (dx * dx + dy * dy <= radiusPx * radiusPx) out.push(e)
  }
  out.sort((a, b) => a.id - b.id)
  return out
}

/**
 * 链电:从 first 出发,每次找上一个目标周围 radiusPx 内、还没被打过、进度最靠前的虫子。
 * 返回 [first, 下一只, …](不含第一只时调用方自己处理),最多 count 只额外目标。
 */
export function chainFrom(level: LevelDef, enemies: readonly Enemy[], first: Enemy, count: number,
  radiusPx: number): Enemy[] {
  const hit = new Set<number>([first.id])
  const out: Enemy[] = []
  let last = first
  for (let i = 0; i < count; i++) {
    const next = pickTarget(level, enemies, enemyPos(level, last), radiusPx, hit)
    if (!next) break
    out.push(next)
    hit.add(next.id)
    last = next
  }
  return out
}
