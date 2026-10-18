// 程序化方块纹理:全部用代码画 16×16 的纹素,没有任何图片文件、没有外部素材。
//
// 每个方块三个面(顶/侧/底),每个面 3 个变体(草叶疏密、石头裂纹、沙子波纹、木板纹理都不同),
// 渲染时按方块坐标选一个变体,大片同种方块就不会像壁纸一样重复。
// 纹素存成 Uint32Array(小端 0xAABBGGRR);布局是 [变体][y][x],每个变体 256 个。
// 图案用固定 salt 的整数哈希生成:每次运行、每台设备都长得一样,但不需要存图。
import { BEDROCK, BRICK, DIRT, GLASS, GRASS, LEAVES, LOG, PLANKS, SAND, STONE, WATER } from './blocks'

export const TEX = 16
/** 每个面有几个变体(渲染时按方块坐标选) */
export const TEX_VARIANTS = 3
const TEXEL_PER_VARIANT = TEX * TEX
/** 纹理面:0 顶、1 侧、2 底 */
export const TEX_TOP = 0
export const TEX_SIDE = 1
export const TEX_BOTTOM = 2

/** 一个面的纹理:3 个变体拼在一起,长度 = 3 × 16 × 16 */
export type FaceTex = Uint32Array
export type BlockTex = [FaceTex, FaceTex, FaceTex]

/** 取纹素:变体号会被折到 0..2,坐标越界会被夹住 */
export function sampleFace(tex: FaceTex, variant: number, tx: number, ty: number): number {
  const v = variant % TEX_VARIANTS
  const x = tx < 0 ? 0 : tx > TEX - 1 ? TEX - 1 : tx
  const y = ty < 0 ? 0 : ty > TEX - 1 ? TEX - 1 : ty
  return tex[v * TEXEL_PER_VARIANT + y * TEX + x]
}

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
  const out = new Uint32Array(TEXEL_PER_VARIANT)
  for (let y = 0; y < TEX; y++) {
    for (let x = 0; x < TEX; x++) out[y * TEX + x] = pack(fn(x, y))
  }
  return out
}

/** 同一张图案生成 3 个带不同 salt 的变体 */
function variants(make: (salt: number) => Uint32Array): FaceTex {
  const out = new Uint32Array(TEXEL_PER_VARIANT * TEX_VARIANTS)
  for (let v = 0; v < TEX_VARIANTS; v++) out.set(make(13 + v * 997), v * TEXEL_PER_VARIANT)
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
    if (hash(x >> 1, y >> 1, salt + 7) > 0.86) return [base[0] - 34, base[1] - 34, base[2] - 34]
    if (hash(x, y, salt + 23) > 0.95) return [base[0] + 18, base[1] + 18, base[2] + 20]
    return base
  })
}

function dirtTex(salt: number): Uint32Array {
  return paint((x, y) => {
    const base = pick(DIRT_BROWN, x, y, salt)
    // 小石子和草根
    if (hash(x, y, salt + 11) > 0.93) return [base[0] + 24, base[1] + 20, base[2] + 14]
    if (hash(x, y, salt + 19) < 0.05) return [base[0] - 26, base[1] - 20, base[2] - 12]
    return base
  })
}

function grassTop(salt: number): Uint32Array {
  return paint((x, y) => {
    const base = pick(GRASS_GREEN, x, y, salt)
    // 深色草丛 + 零星的小花
    if (hash(x >> 1, y >> 1, salt + 3) > 0.82) return [base[0] - 26, base[1] - 22, base[2] - 12]
    if (hash(x, y, salt + 29) > 0.985) return [222, 210, 96]
    return base
  })
}

function grassSide(salt: number): Uint32Array {
  const top = grassTop(salt + 5)
  const dirt = dirtTex(salt + 9)
  const out = new Uint32Array(TEXEL_PER_VARIANT)
  for (let y = 0; y < TEX; y++) {
    for (let x = 0; x < TEX; x++) {
      // 上沿 3–5 格是草,参差不齐地压到泥土上
      const edge = 3 + (hash(x, 0, salt + 55) > 0.5 ? 1 : 0) + (hash(x, 1, salt + 57) > 0.6 ? 1 : 0)
      out[y * TEX + x] = y < edge ? top[y * TEX + x] : dirt[y * TEX + x]
    }
  }
  return out
}

function logSide(salt: number): Uint32Array {
  return paint((x, y) => {
    // 竖着的树皮纹路:每一列有自己的明暗
    const stripe = hash(x, 0, salt + 61)
    const base = stripe > 0.72 ? LOG_BARK[2] : stripe < 0.28 ? LOG_BARK[3] : LOG_BARK[0]
    if (hash(x * 3, y, salt + 62) > 0.9) return LOG_BARK[1]
    if (hash(x, y, salt + 63) > 0.96) return [base[0] + 20, base[1] + 16, base[2] + 10]
    return base
  })
}

function logTop(salt: number): Uint32Array {
  return paint((x, y) => {
    const dx = x - 7.5
    const dy = y - 7.5
    const d = Math.sqrt(dx * dx + dy * dy)
    // 同心圆年轮 + 一点噪声
    const ring = Math.floor(d * 1.15 + hash(x, y, salt + 71) * 0.6) % 2
    if (d > 7.1) return LOG_BARK[1]
    if (d < 1.2) return LOG_RING[3]
    return ring === 0 ? LOG_RING[0] : LOG_RING[1]
  })
}

function leavesTex(salt: number): Uint32Array {
  return paint((x, y) => {
    const h = hash(x, y, salt + 81)
    // 少量深洞,让树冠看起来有层次
    if (h < 0.13) return [40, 78, 30]
    if (h > 0.9) return [124, 188, 88]
    if (hash(x >> 1, y >> 1, salt + 83) > 0.86) return [52, 100, 34]
    return pick(LEAF_GREEN, x, y, salt + 82)
  })
}

function planksTex(salt: number): Uint32Array {
  return paint((x, y) => {
    const board = y >> 2
    const inBoard = y & 3
    // 板缝
    if (inBoard === 3) return [116, 82, 46]
    const base = PLANK[(board + (x >> 3) + salt) & 3]
    // 木纹:横向的细线 + 偶尔一个木节
    if (inBoard === 0 && hash(x, board, salt + 91) > 0.6) return [base[0] - 18, base[1] - 14, base[2] - 10]
    if (hash(x >> 1, y, salt + 92) > 0.94) return [base[0] + 16, base[1] + 14, base[2] + 8]
    if (hash(x, y, salt + 93) > 0.985) return [base[0] - 30, base[1] - 22, base[2] - 12]
    return base
  })
}

function glassTex(salt: number): Uint32Array {
  return paint((x, y) => {
    // 边框 + 一条斜向反光
    if (x === 0 || y === 0 || x === TEX - 1 || y === TEX - 1) return [226, 244, 248]
    if (x === 1 || y === 1 || x === TEX - 2 || y === TEX - 2) return [140, 190, 204]
    if ((x + y) % 9 === 0 || (x + y) % 9 === 1) return [222, 246, 250]
    if (hash(x, y, salt + 101) > 0.9) return [204, 240, 246]
    return pick(GLASS_BLUE, x, y, salt + 101)
  })
}

function brickTex(salt: number): Uint32Array {
  return paint((x, y) => {
    const row = y >> 2
    const rowIn = y & 3
    if (rowIn === 3) return pick(BRICK_MORTAR, x, y, salt + 111)
    const offset = (row & 1) * 4
    const bx = (x + offset) & 7
    if (bx === 7) return pick(BRICK_MORTAR, x, y, salt + 112)
    const base = pick(BRICK_RED, x, y, salt + 113)
    if (hash(x, y, salt + 114) > 0.92) return [base[0] + 18, base[1] + 12, base[2] + 8]
    return base
  })
}

function bedrockTex(salt: number): Uint32Array {
  return paint((x, y) => {
    const base = pick(BEDROCK_GREY, x, y, salt + 121)
    if (hash(x >> 1, y >> 1, salt + 122) > 0.8) return [base[0] + 20, base[1] + 20, base[2] + 24]
    return base
  })
}

function waterTex(salt: number): Uint32Array {
  return paint((x, y) => pick([[52, 104, 168], [46, 96, 158], [58, 114, 178]], x, y, salt + 131))
}

const blank = (): Uint32Array => new Uint32Array(TEXEL_PER_VARIANT)

/** 建好所有方块的三面纹理(每个面 3 个变体),下标 = 方块编号 */
export function buildTextures(): BlockTex[] {
  const top = new Map<number, FaceTex>()
  const side = new Map<number, FaceTex>()
  const bottom = new Map<number, FaceTex>()

  top.set(GRASS, variants(grassTop))
  side.set(GRASS, variants(grassSide))
  bottom.set(GRASS, variants(dirtTex))
  top.set(DIRT, variants(dirtTex))
  side.set(DIRT, variants(dirtTex))
  bottom.set(DIRT, variants(dirtTex))
  top.set(STONE, variants(stoneTex))
  side.set(STONE, variants(stoneTex))
  bottom.set(STONE, variants(stoneTex))
  top.set(SAND, variants((s) => paint((x, y) => {
    // 沙滩:风纹 + 细沙粒
    if ((y + Math.floor(hash(x >> 2, 0, s) * 2)) % 5 === 0) {
      const base = pick(SAND_YELLOW, x, y, s)
      return [base[0] - 14, base[1] - 12, base[2] - 10]
    }
    return pick(SAND_YELLOW, x, y, s + 1)
  })))
  side.set(SAND, variants((s) => paint((x, y) => pick(SAND_YELLOW, x, y, s + 51))))
  bottom.set(SAND, variants((s) => paint((x, y) => pick(SAND_YELLOW, x, y, s + 52))))
  top.set(LOG, variants(logTop))
  side.set(LOG, variants(logSide))
  bottom.set(LOG, variants(logTop))
  top.set(LEAVES, variants(leavesTex))
  side.set(LEAVES, variants(leavesTex))
  bottom.set(LEAVES, variants(leavesTex))
  top.set(PLANKS, variants(planksTex))
  side.set(PLANKS, variants(planksTex))
  bottom.set(PLANKS, variants(planksTex))
  top.set(GLASS, variants(glassTex))
  side.set(GLASS, variants(glassTex))
  bottom.set(GLASS, variants(glassTex))
  top.set(BRICK, variants(brickTex))
  side.set(BRICK, variants(brickTex))
  bottom.set(BRICK, variants(brickTex))
  bottom.set(BEDROCK, variants(bedrockTex))
  top.set(BEDROCK, variants(bedrockTex))
  side.set(BEDROCK, variants(bedrockTex))

  const out: BlockTex[] = []
  const water = variants(waterTex)
  for (let id = 0; id <= BEDROCK; id++) {
    const t = top.get(id) ?? (id === WATER ? water : blank())
    const s = side.get(id) ?? (id === WATER ? water : t)
    const b = bottom.get(id) ?? t
    out.push([t, s, b])
  }
  return out
}

/** 挖到一半的裂纹:4 个阶段,值 0..255 表示该纹素压暗多少(渲染时用来盖在方块面上) */
export function buildCrackTextures(): Uint8Array[] {
  const out: Uint8Array[] = []
  let seed = 0x2545f491
  const rand = (): number => {
    seed = (seed + 0x6d2b79f5) >>> 0
    let t = seed
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  // 先随机出 24 条小裂纹(起点 + 折线),4 个阶段逐步显示更多
  const paths: Array<Array<[number, number]>> = []
  for (let i = 0; i < 24; i++) {
    let x = Math.floor(rand() * TEX)
    let y = Math.floor(rand() * TEX)
    const path: Array<[number, number]> = [[x, y]]
    for (let step = 0; step < 5; step++) {
      const dir = Math.floor(rand() * 4)
      if (dir === 0) x++
      else if (dir === 1) x--
      else if (dir === 2) y++
      else y--
      x = Math.max(0, Math.min(TEX - 1, x))
      y = Math.max(0, Math.min(TEX - 1, y))
      path.push([x, y])
    }
    paths.push(path)
  }
  const perStage = Math.ceil(paths.length / 4)
  for (let stage = 0; stage < 4; stage++) {
    const img = new Uint8Array(TEXEL_PER_VARIANT)
    const shown = Math.min(paths.length, perStage * (stage + 1))
    for (let p = 0; p < shown; p++) {
      for (const [x, y] of paths[p]) {
        // 裂纹中心深、边缘浅一点
        img[y * TEX + x] = Math.max(img[y * TEX + x], 190 + Math.floor(rand() * 60))
        if (x + 1 < TEX && rand() > 0.5) img[y * TEX + x + 1] = Math.max(img[y * TEX + x + 1], 140)
      }
    }
    out.push(img)
  }
  return out
}
