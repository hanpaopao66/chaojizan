// 背包:快捷栏九格各自记数量,挖方块加、放方块减。纯函数,直接改传入的数组(调用方持有)。
//
// 数量按下标和 HOTBAR 一一对应(第 1 格永远是草方块),这样存档里九个数字就够了。

import { HOTBAR, STARTER_COUNTS } from './blocks'
import { MAX_STACK } from './save'

/** 挖到的方块 → 快捷栏下标;不在快捷栏里的(比如基岩)返回 -1 */
export function slotOfBlock(id: number): number {
  return HOTBAR.indexOf(id)
}

export function newInventory(): number[] {
  return STARTER_COUNTS.slice()
}

/** 挖到一块:加进对应格子(到上限就不再加),返回有没有加进去 */
export function addBlock(inv: number[], id: number): boolean {
  const slot = slotOfBlock(id)
  if (slot < 0) return false
  if (inv[slot] >= MAX_STACK) return false
  inv[slot]++
  return true
}

/** 放一块:数量够就减一;不够返回 false(界面提示「没有这个方块了」) */
export function takeBlock(inv: number[], slot: number): boolean {
  if (slot < 0 || slot >= inv.length || inv[slot] <= 0) return false
  inv[slot]--
  return true
}

export function countOf(inv: number[], slot: number): number {
  return inv[slot] ?? 0
}

/** 全部数量之和,存档摘要用 */
export function totalBlocks(inv: number[]): number {
  let n = 0
  for (const v of inv) n += v
  return n
}
