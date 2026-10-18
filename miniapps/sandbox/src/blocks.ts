// 方块编号和属性在 data.ts;这里只放查询和派生的小函数(纯函数,没有 DOM)。
//
// 编号写进存档(稀疏编辑列表里每格记一个字节),所以**不要改已有的编号**;
// 新方块只能往后加,旧存档才不会读错。
import { BLOCKS, FEEL, WATER } from './data'
import type { Material } from './data'

export {
  AIR, BEDROCK, BLOCKS, BRICK, DIRT, GLASS, GRASS, HOTBAR, LEAVES, LOG, PLANKS, SAND, STARTER_COUNTS, STONE,
  WATER,
} from './data'
export type { BlockDef, Material } from './data'

/** 界面和提示里显示的名字 */
export const blockName = (id: number): string => BLOCKS[id]?.name ?? '方块'

/** 音效/粒子用的材质 */
export const blockMaterial = (id: number): Material => BLOCKS[id]?.material ?? 'stone'

export const isSolid = (id: number): boolean => BLOCKS[id]?.solid === true

/** 不透明:能挡住视线、能被射线选中(水不算,玻璃算) */
export const isOpaque = (id: number): boolean => isSolid(id) && id !== WATER

/** 能不能挖(基岩硬度 Infinity,不能) */
export const isTargetable = (id: number): boolean => Number.isFinite(BLOCKS[id]?.hardness)

/** 挖掘时间:水里的方块慢一点;返回秒 */
export function breakTime(id: number, inWater: boolean): number {
  const h = BLOCKS[id]?.hardness ?? Infinity
  if (!Number.isFinite(h)) return Infinity
  return h * (inWater ? FEEL.MINE_WATER_FACTOR : 1)
}

/** 1–9 的键码 → 快捷栏下标;不是数字键返回 -1 */
export function hotbarIndexFromKey(key: string): number {
  if (key.length !== 1) return -1
  const n = key.charCodeAt(0) - 48
  return n >= 1 && n <= 9 ? n - 1 : -1
}
