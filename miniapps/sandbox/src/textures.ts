// 程序化方块纹理:全部用代码画 16×16 的纹素,没有任何图片文件、没有外部素材。
//
// 每个方块三个面(顶/侧/底),存成 Uint32Array(小端 0xAABBGGRR),渲染时直接按像素取。
// 图案用固定 salt 的整数哈希生成:每次运行、每台设备都长得一样,但不需要存图。
import { AIR, BEDROCK, BRICK, DIRT, GLASS, GRASS, LEAVES, LOG, PLANKS, SAND, STONE, WATER } from './blocks'

export const TEX = 16
/** 纹理面:0 顶、1 侧、2 底 */
export const TEX_TOP = 0
export const TEX_SIDE = 1
export const TEX_BOTTOM = 2

export type BlockTex = [Uint32Array, Uint32Array, Uint32Array]

type RGB = readonly [number, number, number]

const pack = (c: RGB): number => ((255 << 24) | (c[2] << 16) | (c[1] << 8) | c[0]) >>> 0

/** 整数哈希 → [0,1);salt 区分不同图案 */
function hash(x: number, y: number, salt: number): number {
  let h = Math.imul(x + 1, 374761393) + Math.imul(y + 1, 668265263) + Math.imul(salt + 1, 1442695041)
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296
}

const pick = (variants: readonly RGB[], x: number, y: number, salt: number): RGB =>
  variants[Math.floor(hash(x, y, salt) * variants.length)]

function paint(fn: (x: number, y: number) => RGB): Uint32Array {
  const out = new Uint32Array(TEX * TEX)
  for (let y = 0; y < TEX; y++) {
    for (let x = 0; x < TEX; x++) out[y * TEX + x] = pack(fn(x, y))
  }
  return out
}

// ---------------------------------------------------------------- 各个方块的画法

const GRASS_GREEN: readonly RGB[] = [[95, 168, 60], [86, 156, 53], [106, 180, 68], [79, 146, 48], [116, 190, 74]]
const DIRT_BROWN: readonly RGB[] = [[138, 96, 56], [128, 88, 50], [150, 108, 64], [116, 78, 44], [158, 116, 72]]
const STONE_GREY: readonly RGB[] = [[138, 138, 143], [128, 128, 133], [148, 148, 152], [120, 120, 125], [156, 156, 160]]
const SAND_YELLOW: readonly RGB[] = [[232, 216, 160], [222, 204, 146], [240, 226, 176], [212, 194, 136], [246, 234, 188]]
const LOG_BARK: readonly RGB[] = [[110, 75, 42], [96, 64, 34], [124, 86, 50], [86, 56, 30]]
const LOG_RING: readonly RGB[] = [[201, 164, 104], [176, 138, 80], [216, 184, 126], [158, 122, 70]]
const LEAF_GREEN: readonly RGB[] = [[76, 138, 52], [64, 120, 42], [92, 158, 64], [54, 104, 36], [106, 170, 74]]
const PLANK: readonly RGB[] = [[185, 139, 84], [170, 126, 74], [198, 154, 96], [158, 116, 68]]
const GLASS_BLUE: readonly RGB[] = [[176, 224, 232], [162, 212, 224], [196, 236, 242], [150, 200, 216]]
const BRICK_RED: readonly RGB[] = [[164, 72, 58], [148, 60, 48], [180, 88, 70], [128, 50, 40]]
const BRICK_MORTAR: readonly RGB[] = [[214, 204, 188], [202, 192, 176], [224, 216, 202]]
const BEDROCK_GREY: readonly RGB[] = [[74, 74, 82], [58, 58, 66], [92, 92, 100], [44, 44, 52], [110, 110, 118]]

function stoneTex(salt: number): Uint32Array {
  return paint((x, y) => {
    const base = pick(STONE_GREY, x, y, salt)
    // 稀疏的裂缝:低频哈希挑几个格子压暗
    if (hash(x >> 1, y >> 1, salt + 7) > 0.86) {
      return [base[0] - 34, base[1] - 34, base[2] - 34]
    }
    return base
  })
}

function dirtTex(salt: number): Uint32Array {
  return paint((x, y) => {
    const base = pick(DIRT_BROWN, x, y, salt)
    // 小石子
    if (hash(x, y, salt + 11) > 0.93) return [base[0] + 24, base[1] + 20, base[2] + 14]
    return base
  })
}

function grassTop(salt: number): Uint32Array {
  return paint((x, y) => {
    const base = pick(GRASS_GREEN, x, y, salt)
    // 一两撮深色的草丛
    if (hash(x >> 1, y >> 1, salt + 3) > 0.82) return [base[0] - 26, base[1] - 22, base[2] - 12]
    return base
  })
}

function grassSide(): Uint32Array {
  const top = grassTop(21)
  const dirt = dirtTex(31)
  const out = new Uint32Array(TEX * TEX)
  for (let y = 0; y < TEX; y++) {
    for (let x = 0; x < TEX; x++) {
      // 上沿 3–4 格是草,参差不齐地压到泥土上
      const edge = 3 + (hash(x, 0, 55) > 0.5 ? 1 : 0)
      out[y * TEX + x] = y < edge ? top[y * TEX + x] : dirt[y * TEX + x]
    }
  }
  return out
}

function logSide(): Uint32Array {
  return paint((x, y) => {
    // 竖着的树皮纹路:每一列有自己的明暗
    const stripe = hash(x, 0, 61)
    const base = stripe > 0.72 ? LOG_BARK[2] : stripe < 0.28 ? LOG_BARK[3] : LOG_BARK[0]
    const n = hash(x * 3, y, 62)
    if (n > 0.9) return LOG_BARK[1]
    return base
  })
}

function logTop(): Uint32Array {
  return paint((x, y) => {
    const dx = x - 7.5
    const dy = y - 7.5
    const d = Math.sqrt(dx * dx + dy * dy)
    // 同心圆年轮 + 一点噪声
    const ring = Math.floor(d * 1.15 + hash(x, y, 71) * 0.6) % 2
    if (d > 7.1) return LOG_BARK[1]
    return ring === 0 ? LOG_RING[0] : LOG_RING[1]
  })
}

function leavesTex(): Uint32Array {
  return paint((x, y) => {
    const h = hash(x, y, 81)
    // 少量深洞,让树冠看起来有层次
    if (h < 0.13) return [40, 78, 30]
    if (h > 0.9) return [124, 188, 88]
    return pick(LEAF_GREEN, x, y, 82)
  })
}

function planksTex(): Uint32Array {
  return paint((x, y) => {
    const board = y >> 2
    const inBoard = y & 3
    // 板缝
    if (inBoard === 3) return [116, 82, 46]
    const base = PLANK[(board + (x >> 3)) & 3]
    // 木纹:横向的细线
    if (inBoard === 0 && hash(x, board, 91) > 0.6) return [base[0] - 18, base[1] - 14, base[2] - 10]
    if (hash(x >> 1, y, 92) > 0.94) return [base[0] + 16, base[1] + 14, base[2] + 8]
    return base
  })
}

function glassTex(): Uint32Array {
  return paint((x, y) => {
    // 边框 + 一条斜向反光
    if (x === 0 || y === 0 || x === TEX - 1 || y === TEX - 1) return [226, 244, 248]
    if (x === 1 || y === 1 || x === TEX - 2 || y === TEX - 2) return [140, 190, 204]
    if ((x + y) % 9 === 0 || (x + y) % 9 === 1) return [222, 246, 250]
    return pick(GLASS_BLUE, x, y, 101)
  })
}

function brickTex(): Uint32Array {
  return paint((x, y) => {
    const row = y >> 2
    const rowIn = y & 3
    if (rowIn === 3) return pick(BRICK_MORTAR, x, y, 111)
    const offset = (row & 1) * 4
    const bx = (x + offset) & 7
    if (bx === 7) return pick(BRICK_MORTAR, x, y, 112)
    return pick(BRICK_RED, x, y, 113)
  })
}

function bedrockTex(): Uint32Array {
  return paint((x, y) => {
    const base = pick(BEDROCK_GREY, x, y, 121)
    if (hash(x >> 1, y >> 1, 122) > 0.8) return [base[0] + 20, base[1] + 20, base[2] + 24]
    return base
  })
}

function waterTex(): Uint32Array {
  return paint((x, y) => pick([[52, 104, 168], [46, 96, 158], [58, 114, 178]], x, y, 131))
}

const BLANK = (): Uint32Array => new Uint32Array(TEX * TEX)

/** 建好所有方块的纹理表,下标 = 方块编号 */
export function buildTextures(): BlockTex[] {
  const top = new Map<number, Uint32Array>()
  const side = new Map<number, Uint32Array>()
  const bottom = new Map<number, Uint32Array>()

  top.set(GRASS, grassTop(20))
  side.set(GRASS, grassSide())
  bottom.set(GRASS, dirtTex(32))
  top.set(DIRT, dirtTex(33))
  side.set(DIRT, dirtTex(34))
  bottom.set(DIRT, dirtTex(35))
  top.set(STONE, stoneTex(40))
  side.set(STONE, stoneTex(41))
  bottom.set(STONE, stoneTex(42))
  top.set(SAND, paint((x, y) => pick(SAND_YELLOW, x, y, 50)))
  side.set(SAND, paint((x, y) => pick(SAND_YELLOW, x, y, 51)))
  bottom.set(SAND, paint((x, y) => pick(SAND_YELLOW, x, y, 52)))
  top.set(LOG, logTop())
  side.set(LOG, logSide())
  bottom.set(LOG, logTop())
  const leaf = leavesTex()
  top.set(LEAVES, leaf)
  side.set(LEAVES, leaf)
  bottom.set(LEAVES, leavesTex())
  top.set(PLANKS, planksTex())
  side.set(PLANKS, planksTex())
  bottom.set(PLANKS, planksTex())
  top.set(GLASS, glassTex())
  side.set(GLASS, glassTex())
  bottom.set(GLASS, glassTex())
  top.set(BRICK, brickTex())
  side.set(BRICK, brickTex())
  bottom.set(BRICK, brickTex())
  bottom.set(BEDROCK, bedrockTex())

  const out: BlockTex[] = []
  for (let id = 0; id <= BEDROCK; id++) {
    out.push([
      top.get(id) ?? (id === WATER ? waterTex() : BLANK()),
      side.get(id) ?? (id === WATER ? waterTex() : top.get(id) ?? BLANK()),
      bottom.get(id) ?? top.get(id) ?? BLANK(),
    ])
  }
  return out
}

export const isAirOrWater = (id: number): boolean => id === AIR || id === WATER
