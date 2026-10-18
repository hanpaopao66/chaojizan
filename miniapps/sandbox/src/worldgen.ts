// 世界生成:用种子生成一座 128×128、48 格高的海岛。纯函数,没有 DOM。
//
// 形状:离岛心越远越低,边缘沉到海面以下;再叠几层噪声让海岸线不规则,
// 内陆低处是草原、近水是沙滩、高处是石丘;草地上随机长树(树干 + 树冠)。
// 世界最底下两层是基岩,永远挖不动 —— 这样无论怎么挖都不会掉出世界。
import { rand } from '../../shared/src/rand'
import { AIR, BEDROCK, DIRT, GRASS, LEAVES, LOG, SAND, STONE, WATER } from './blocks'
import { detailNoise, smoothstep, terrainNoise } from './noise'

/** 世界宽(x 方向,格) */
export const W = 128
/** 世界深(z 方向,格) */
export const D = 128
/** 世界高(y 方向,格)。最上面留够空间种树、搭塔 */
export const H = 48
/** 海平面:y < SEA_LEVEL 的格子才可能装水,水面在这个高度 */
export const SEA_LEVEL = 10

/** 列编号(只看 x/z) */
export const colIndex = (x: number, z: number): number => x + W * z
/** 体素编号:y 层之间差 W*D */
export const voxelIndex = (x: number, y: number, z: number): number => x + W * (z + D * y)

export interface Spawn {
  x: number
  y: number
  z: number
}

export interface GeneratedWorld {
  blocks: Uint8Array
  /** 脚下位置(方块顶面 = spawn.y) */
  spawn: Spawn
  /** 出生时朝哪看(弧度,yaw) */
  yaw: number
  /** 每列的地形高度(实心方块数),渲染和树用 */
  heights: Uint8Array
}

const clamp = (v: number, lo: number, hi: number): number => (v < lo ? lo : v > hi ? hi : v)

/** 单列的地形高度(实心方块数)。地形生成和测试都用这个函数,保证一致。 */
export function terrainHeight(seed: number, x: number, z: number): number {
  const terrain = terrainNoise(seed)
  const detail = detailNoise(seed)
  return heightOf(terrain, detail, x, z)
}

function heightOf(terrain: ReturnType<typeof terrainNoise>, detail: ReturnType<typeof detailNoise>,
  x: number, z: number): number {
  const cx = (W - 1) / 2
  const cz = (D - 1) / 2
  // 椭圆形的岛,横向略宽:归一化距离 1 附近就是海岸
  const dx = (x - cx) / 60
  const dz = (z - cz) / 64
  const big = terrain(x, z)
  // 噪声扰动海岸线,避免出现一个正圆
  const edge = Math.sqrt(dx * dx + dz * dz) + (big - 0.5) * 0.55
  const land = 1 - smoothstep(0.45, 1.02, edge)
  const roll = detail(x, z)
  // 海岸切得陡一点:沙滩窄、内陆高,草原面积才够走
  let h = SEA_LEVEL - 6 + land * 11 + land * land * (big * 9 + roll * 5)
  // 内陆的石丘:只在内陆、且细节噪声够高的地方隆起
  const ridge = Math.max(0, detail(x + 37, z + 17) - 0.54)
  h += ridge * 24 * smoothstep(0.55, 0.95, land)
  return clamp(Math.round(h), 2, H - 12)
}

/** 某列地表方块用哪种:水下和岸边是沙,高山上是石头,其余是草 */
function surfaceBlock(h: number, rock: number): number {
  if (h <= SEA_LEVEL + 1) return SAND
  if (h >= 21 && rock > 0.45) return STONE
  return GRASS
}

/**
 * 出生朝向:先朝着岛心看(能看到岛,不是一睁眼一片海);这个方向近处被树/石头挡住的话,
 * 左右各转 45° 找一个不挡视线、又能看到岛里的方向。眼睛在脚底上方一格。
 */
function openYaw(blockAt: (x: number, y: number, z: number) => number, x: number, z: number, feetY: number): number {
  const center = Math.atan2((D - 1) / 2 - z, (W - 1) / 2 - x)
  const offsets = [0, 1, -1, 2, -2, 3, -3, 4]
  for (const step of offsets) {
    const a = center + (step * Math.PI) / 4
    let blocked = false
    for (let d = 1; d <= 4 && !blocked; d++) {
      const bx = Math.floor(x + Math.cos(a) * d)
      const bz = Math.floor(z + Math.sin(a) * d)
      if (blockAt(bx, feetY + 1, bz) !== AIR) blocked = true
    }
    if (!blocked) return a
  }
  return center
}

interface SpawnChoice {
  x: number
  z: number
  h: number
}

/**
 * 选出生点(在种树之前,所以只看地形):优先低处的海岸草原,其次任意高度的草地,
 * 都要求身边 5×5 高差不超过一格;再不行就放宽。世界中心作为最后兜底。
 */
function chooseSpawn(heights: Uint8Array, blocks: Uint8Array): SpawnChoice {
  const flat = (x: number, z: number, h: number): boolean => {
    for (let dz = -2; dz <= 2; dz++) {
      for (let dx = -2; dx <= 2; dx++) {
        const dh = heights[colIndex(x + dx, z + dz)] - h
        if (dh < -1 || dh > 1) return false
      }
    }
    return true
  }
  const cx = Math.round((W - 1) / 2)
  const cz = Math.round((D - 1) / 2)
  let fallback: SpawnChoice = { x: cx, z: cz, h: Math.max(SEA_LEVEL + 3, heights[colIndex(cx, cz)]) }
  let haveFallback = false
  for (let pass = 0; pass < 4; pass++) {
    for (let r = 0; r <= 52; r++) {
      for (let dz = -r; dz <= r; dz++) {
        for (let dx = -r; dx <= r; dx++) {
          if (Math.max(Math.abs(dx), Math.abs(dz)) !== r) continue
          const x = cx + dx
          const z = cz + dz
          if (x < 2 || x >= W - 2 || z < 2 || z >= D - 2) continue
          const h = heights[colIndex(x, z)]
          if (h <= SEA_LEVEL + 2) continue
          if (!haveFallback) {
            fallback = { x, z, h }
            haveFallback = true
          }
          const grass = blocks[colIndex(x, z) + W * D * (h - 1)] === GRASS
          if (pass < 3 && !grass) continue
          if (pass === 0 && h > SEA_LEVEL + 7) continue
          if (pass <= 1 && !flat(x, z, h)) continue
          return { x, z, h }
        }
      }
    }
  }
  return fallback
}

/** 生成整个世界。同一个 seed 永远返回同一份方块(测试里有确定性用例)。 */
export function generateWorld(seed: number): GeneratedWorld {
  const s = seed >>> 0
  const terrain = terrainNoise(s)
  const detail = detailNoise(s)
  const blocks = new Uint8Array(W * D * H)
  const heights = new Uint8Array(W * D)

  for (let z = 0; z < D; z++) {
    for (let x = 0; x < W; x++) {
      const h = heightOf(terrain, detail, x, z)
      const col = colIndex(x, z)
      heights[col] = h
      const surface = surfaceBlock(h, detail(x + 91, z + 13))
      const sandy = h <= SEA_LEVEL + 2
      for (let y = 0; y < H; y++) {
        let id = AIR
        if (y <= 1) id = BEDROCK
        else if (y < h) {
          if (y === h - 1) id = surface
          else if (y >= h - 3) id = sandy ? SAND : DIRT
          else id = STONE
        } else if (y < SEA_LEVEL) {
          id = WATER
        }
        if (id !== AIR) blocks[col + W * D * y] = id
      }
    }
  }

  // 出生点在树林种下之前就定好:脚下一片平缓的草地
  const spot = chooseSpawn(heights, blocks)
  const sx = spot.x
  const sz = spot.z
  const sy = spot.h

  // 种树。用一条独立的随机流,顺序固定(x 从小到大、z 从小到大),同种子结果一致。
  // 出生点周围一圈不种树:一睁眼先看到开阔的地方,而不是贴着脸的树干。
  let rnd = (s ^ 0x1234567) >>> 0
  const taken = new Uint8Array(W * D)
  const plant = (x: number, y: number, z: number, id: number): void => {
    if (x < 0 || x >= W || z < 0 || z >= D || y < 0 || y >= H) return
    const i = x + W * (z + D * y)
    if (blocks[i] === AIR) blocks[i] = id
  }
  for (let z = 1; z < D - 1; z++) {
    for (let x = 1; x < W - 1; x++) {
      const ddx = x - sx
      const ddz = z - sz
      if (ddx * ddx + ddz * ddz <= 18) continue
      const col = colIndex(x, z)
      if (taken[col]) continue
      const h = heights[col]
      if (h <= SEA_LEVEL + 2) continue
      if (blocks[col + W * D * (h - 1)] !== GRASS) continue
      // 坡太陡的地方不长树
      const slope = Math.abs(heights[colIndex(x + 1, z)] - h) + Math.abs(heights[colIndex(x - 1, z)] - h)
        + Math.abs(heights[colIndex(x, z + 1)] - h) + Math.abs(heights[colIndex(x, z - 1)] - h)
      if (slope > 3) continue
      let r: number
      ;[r, rnd] = rand(rnd)
      if (r > 0.05) continue
      let trunk: number
      ;[r, rnd] = rand(rnd)
      trunk = 4 + Math.floor(r * 3)
      // 占住 2 格半径,树和树之间不会挤在一起
      for (let dz2 = -2; dz2 <= 2; dz2++) {
        for (let dx2 = -2; dx2 <= 2; dx2++) {
          const tx = x + dx2
          const tz = z + dz2
          if (tx >= 0 && tx < W && tz >= 0 && tz < D) taken[colIndex(tx, tz)] = 1
        }
      }
      const top = h + trunk - 1
      for (let y = h; y <= top && y < H; y++) plant(x, y, z, LOG)
      // 树冠:下面两层半径 1,上面三层半径 2,四角随机削掉
      for (let ly = top - 2; ly <= top + 1; ly++) {
        const radius = ly >= top ? 2 : 1
        for (let dz2 = -radius; dz2 <= radius; dz2++) {
          for (let dx2 = -radius; dx2 <= radius; dx2++) {
            if (dx2 === 0 && dz2 === 0 && ly <= top) continue
            if (radius === 2 && Math.abs(dx2) === 2 && Math.abs(dz2) === 2) {
              let corner: number
              ;[corner, rnd] = rand(rnd)
              if (corner < 0.55) continue
            }
            plant(x + dx2, ly, z + dz2, LEAVES)
          }
        }
      }
    }
  }

  const blockAt = (bx: number, by: number, bz: number): number => {
    if (bx < 0 || bx >= W || bz < 0 || bz >= D || by < 0 || by >= H) return BEDROCK
    return blocks[bx + W * (bz + D * by)]
  }
  // 出生朝向:朝岛心看;近处被地形挡住就左右转一点
  const yaw = openYaw(blockAt, sx, sz, sy)
  return { blocks, spawn: { x: sx + 0.5, y: sy, z: sz + 0.5 }, yaw, heights }
}

/** 换种子重开时给新世界用的种子;只在新世界界面调 */
export function parseSeed(text: string): number | null {
  const t = text.trim()
  if (!t) return null
  // 允许纯数字(0..2^32-1),也允许一位字母数字串按 36 进制解释,方便分享
  if (/^\d+$/.test(t)) {
    const n = Number(t)
    if (!Number.isSafeInteger(n) || n < 0 || n > 0xffffffff) return null
    return n >>> 0
  }
  if (/^[0-9a-z]{1,7}$/i.test(t)) {
    const n = parseInt(t, 36)
    return Number.isSafeInteger(n) && n >= 0 ? n >>> 0 : null
  }
  return null
}

/** 种子的展示形式:十进制,方便抄下来给朋友 */
export function seedText(seed: number): string {
  return String(seed >>> 0)
}
