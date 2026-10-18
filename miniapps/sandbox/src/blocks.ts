// 方块的种类和属性。纯数据 + 纯函数,界面、世界生成、存档都用这里的编号。
//
// 编号写进存档(稀疏编辑列表里每格记一个字节),所以**不要改已有的编号**;
// 新方块只能往后加,旧存档才不会读错。

export const AIR = 0
export const GRASS = 1
export const DIRT = 2
export const STONE = 3
export const SAND = 4
export const WATER = 5
export const LOG = 6
export const LEAVES = 7
export const PLANKS = 8
export const GLASS = 9
export const BRICK = 10
/** 世界最底下两层,挖不动,保证不会掉出世界 */
export const BEDROCK = 11

export interface BlockDef {
  id: number
  /** 界面和提示里显示的名字 */
  name: string
  /** 有没有碰撞(水没有:可以走进去游泳) */
  solid: boolean
  /** 挖穿需要按住多少秒(空手);Infinity = 挖不动 */
  hardness: number
  /** 能不能被射线选中、挖掉 */
  targetable: boolean
}

const def = (id: number, name: string, solid: boolean, hardness: number): BlockDef =>
  ({ id, name, solid, hardness, targetable: hardness !== Infinity })

/** 按编号索引;0 号是空气。BEDROCK 硬度 Infinity 所以选不中、挖不动。 */
export const BLOCKS: readonly BlockDef[] = [
  def(AIR, '空气', false, Infinity),
  def(GRASS, '草方块', true, 0.4),
  def(DIRT, '泥土', true, 0.4),
  def(STONE, '石头', true, 0.9),
  def(SAND, '沙子', true, 0.35),
  def(WATER, '水', false, Infinity),
  def(LOG, '木头', true, 0.8),
  def(LEAVES, '树叶', true, 0.15),
  def(PLANKS, '木板', true, 0.6),
  def(GLASS, '玻璃', true, 0.25),
  def(BRICK, '砖', true, 1.0),
  def(BEDROCK, '基岩', true, Infinity),
]

/** 快捷栏里的九种方块(正好 1–9 九个数字键) */
export const HOTBAR: readonly number[] = [GRASS, DIRT, STONE, SAND, LOG, LEAVES, PLANKS, GLASS, BRICK]

/** 关卡里挖到的基础物资:新世界送一点,不然一开始只能挖、没法搭 */
export const STARTER_COUNTS: readonly number[] = [10, 10, 10, 10, 10, 10, 10, 10, 10]

export const blockName = (id: number): string => BLOCKS[id]?.name ?? '方块'

export const isSolid = (id: number): boolean => BLOCKS[id]?.solid === true

/** 不透明:能挡住视线、能被射线选中(水不算,玻璃算) */
export const isOpaque = (id: number): boolean => isSolid(id) && id !== WATER

/** 挖掘时间:水里的方块慢一点,空手最慢;返回秒 */
export function breakTime(id: number, inWater: boolean): number {
  const h = BLOCKS[id]?.hardness ?? Infinity
  if (!Number.isFinite(h)) return Infinity
  return h * (inWater ? 1.35 : 1)
}

/** 1–9 的键码 → 快捷栏下标;不是数字键返回 -1 */
export function hotbarIndexFromKey(key: string): number {
  if (key.length !== 1) return -1
  const n = key.charCodeAt(0) - 48
  return n >= 1 && n <= 9 ? n - 1 : -1
}
