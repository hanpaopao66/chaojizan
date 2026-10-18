// 世界状态:生成出来的底座 + 玩家的稀疏编辑。
//
// 存档只记「和生成结果不一样」的格子(edits),所以：
// - 4000 条编辑封顶,序列化后远小于 64 KB(每条约 2–6 个字符);
// - 把一格改回生成时的样子会自动把这条编辑删掉,玩家来回挖/放不会把容量耗光;
// - 渲染要用的「每列哪些高度是实心的、水在哪儿、最高实心格」在这里增量维护,
//   光栅化时每格只要两三次位运算。
import { AIR, BEDROCK, HOTBAR, WATER, isOpaque } from './blocks'
import { D, H, W, colIndex, generateWorld, type Spawn, voxelIndex } from './worldgen'

/** 稀疏编辑上限:按最长的编码估算约 24 KB,给存档留足余量 */
export const MAX_EDITS = 4000
/** 编辑串的长度上限(序列化后写进云存储前的硬闸,和 MAX_EDITS 双保险) */
export const MAX_EDITS_TEXT = 60000

export interface BlockSource {
  /** 越界当成基岩(撞不出去)、世界上面当成空气 */
  blockAt(x: number, y: number, z: number): number
}

export type EditResult = 'ok' | 'same' | 'full' | 'bedrock' | 'outside'

const clampY = (y: number): number => (y < 0 ? 0 : y > H - 1 ? H - 1 : y)

/** 编辑表 → 紧凑字符串:按下标排序,存「和上一格的差」+「方块编号」,36 进制、逗号分隔 */
export function encodeEdits(edits: ReadonlyMap<number, number>): string {
  const keys = Array.from(edits.keys()).sort((a, b) => a - b)
  let out = ''
  let prev = 0
  for (const index of keys) {
    out += (index - prev).toString(36) + ':' + (edits.get(index) as number).toString(36) + ','
    prev = index
  }
  return out
}

/** 紧凑字符串 → 编辑对。格式不对、越界、重复、条数超限都返回 null(当作坏档) */
export function decodeEdits(text: string): Array<[number, number]> | null {
  if (typeof text !== 'string' || text.length > MAX_EDITS_TEXT) return null
  if (text === '') return []
  const tokens = text.split(',')
  if (tokens.length && tokens[tokens.length - 1] === '') tokens.pop()
  if (!tokens.length || tokens.length > MAX_EDITS) return null
  const out: Array<[number, number]> = []
  let prev = 0
  for (const token of tokens) {
    const parts = token.split(':')
    if (parts.length !== 2) return null
    if (!/^[0-9a-z]+$/.test(parts[0]) || !/^[0-9a-z]+$/.test(parts[1])) return null
    const delta = parseInt(parts[0], 36)
    const id = parseInt(parts[1], 36)
    if (!Number.isSafeInteger(delta) || !Number.isSafeInteger(id) || delta <= 0 || id < 0 || id > 10) return null
    const index = prev + delta
    if (index >= W * D * H) return null
    const y = Math.floor(index / (W * D))
    if (y < 2) return null
    out.push([index, id])
    prev = index
  }
  return out
}

export class World implements BlockSource {
  readonly seed: number
  readonly spawn: Spawn
  readonly yaw: number
  /** 生成出来的原始世界,用来判断一次编辑是不是改回了原样 */
  readonly base: Uint8Array
  /** 当前世界(底座 + 编辑) */
  readonly blocks: Uint8Array
  /** 玩家改过的格子:体素编号 → 方块编号(可能是 AIR:挖掉了) */
  readonly edits = new Map<number, number>()
  /** 每列 0..31 层里哪些是不透明方块 */
  readonly opaqueLo: Uint32Array
  readonly opaqueHi: Uint32Array
  /** 每列 0..31 层里哪些是水 */
  readonly waterLo: Uint32Array
  readonly waterHi: Uint32Array
  /** 每列最高的不透明方块(没有是 -1) */
  readonly top: Int8Array

  constructor(seed: number) {
    const g = generateWorld(seed)
    this.seed = seed >>> 0
    this.spawn = g.spawn
    this.yaw = g.yaw
    this.base = g.blocks
    this.blocks = g.blocks.slice()
    const cols = W * D
    this.opaqueLo = new Uint32Array(cols)
    this.opaqueHi = new Uint32Array(cols)
    this.waterLo = new Uint32Array(cols)
    this.waterHi = new Uint32Array(cols)
    this.top = new Int8Array(cols)
    for (let z = 0; z < D; z++) {
      for (let x = 0; x < W; x++) this.refreshColumn(x, z)
    }
  }

  get editCount(): number {
    return this.edits.size
  }

  blockAt(x: number, y: number, z: number): number {
    if (x < 0 || x >= W || z < 0 || z >= D || y < 0) return BEDROCK
    if (y >= H) return AIR
    return this.blocks[x + W * (z + D * y)]
  }

  /** 渲染/射线用:这一格可靠不透明方块挡住视线 */
  isOpaqueAt(x: number, y: number, z: number): boolean {
    return isOpaque(this.blockAt(x, y, z))
  }

  topAt(x: number, z: number): number {
    if (x < 0 || x >= W || z < 0 || z >= D) return -1
    return this.top[colIndex(x, z)]
  }

  /**
   * 改一格。返回结果给界面决定提示什么:
   * 'ok' 改成功 / 'same' 没变化 / 'full' 编辑数到顶 / 'bedrock' 挖不动 / 'outside' 越界
   */
  setBlock(x: number, y: number, z: number, id: number): EditResult {
    if (x < 0 || x >= W || z < 0 || z >= D || y < 0 || y >= H) return 'outside'
    if (y <= 1) return 'bedrock'
    const index = voxelIndex(x, y, z)
    const base = this.base[index]
    const had = this.edits.has(index)
    if (id === base) {
      if (!had) return 'same'
      this.edits.delete(index)
      this.blocks[index] = base
      this.refreshColumn(x, z)
      return 'ok'
    }
    if (had && this.edits.get(index) === id) return 'same'
    if (!had && this.edits.size >= MAX_EDITS) return 'full'
    this.edits.set(index, id)
    this.blocks[index] = id
    this.refreshColumn(x, z)
    return 'ok'
  }

  /** 重新算一列的位图 / 最高格(编辑后调用) */
  refreshColumn(x: number, z: number): void {
    const col = colIndex(x, z)
    let oLo = 0
    let oHi = 0
    let wLo = 0
    let wHi = 0
    let top = -1
    for (let y = 0; y < H; y++) {
      const id = this.blocks[col + W * D * y]
      if (id === AIR) continue
      if (id === WATER) {
        if (y < 32) wLo |= 1 << y
        else wHi |= 1 << (y - 32)
      } else {
        if (y < 32) oLo |= 1 << y
        else oHi |= 1 << (y - 32)
        top = y
      }
    }
    this.opaqueLo[col] = oLo
    this.opaqueHi[col] = oHi
    this.waterLo[col] = wLo
    this.waterHi[col] = wHi
    this.top[col] = top
  }

  serializeEdits(): string {
    return encodeEdits(this.edits)
  }

  /** 读档时灌入编辑;格式不对返回 false,调用方把存档当成坏档 */
  loadEdits(text: string): boolean {
    const pairs = decodeEdits(text)
    if (!pairs) return false
    this.edits.clear()
    this.blocks.set(this.base)
    for (const [index, id] of pairs) this.edits.set(index, id)
    for (const [index, id] of this.edits) this.blocks[index] = id
    for (let z = 0; z < D; z++) {
      for (let x = 0; x < W; x++) this.refreshColumn(x, z)
    }
    return true
  }

  /** 找到一个可以站的地面高度(从 fromY 往下找),给掉出世界后重生用 */
  groundBelow(x: number, z: number, fromY: number): number {
    const gx = Math.max(0, Math.min(W - 1, Math.floor(x)))
    const gz = Math.max(0, Math.min(D - 1, Math.floor(z)))
    const start = clampY(Math.floor(fromY))
    for (let y = start; y >= 0; y--) {
      if (isOpaque(this.blockAt(gx, y, gz))) return y + 1
    }
    // 这一列被挖穿了:回出生点的地面
    return Math.floor(this.spawn.y)
  }
}

/** 快捷栏里有哪些方块(界面和测试共用) */
export const HOTBAR_IDS: readonly number[] = HOTBAR
