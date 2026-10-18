// 方块碎屑粒子:挖 / 破方块时飞几颗小方块,给挖掘一点「打中了」的反馈。
// 纯函数(生成/更新)+ 一个画到 2D 上下文的函数;粒子数量很少,不影响 60fps。
import { BLOCKS } from './blocks'

export interface Particle {
  x: number
  y: number
  z: number
  vx: number
  vy: number
  vz: number
  /** 剩余寿命(秒) */
  life: number
  /** 初始寿命,用来算淡出 */
  maxLife: number
  /** 屏幕上的大小(世界单位,约 0.04–0.09) */
  size: number
  r: number
  g: number
  b: number
}

/** 最多同时存在多少粒子(超过就丢老的,保证性能) */
export const MAX_PARTICLES = 96
const GRAVITY = 16
const LIFE_MIN = 0.35
const LIFE_MAX = 0.7
const SIZE_MIN = 0.035
const SIZE_MAX = 0.085

/** 确定性哈希,避免 Math.random 让画面/测试不可复现 */
function hash(a: number, b: number): number {
  let h = Math.imul(a + 1, 374761393) + Math.imul(b + 1, 668265263)
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296
}

/**
 * 挖碎一块方块时生成碎屑。x/y/z 是方块中心附近;seed 传一个自增值即可,
 * 同一帧内不同粒子的方向由 seed + i 决定。
 */
export function spawnBreakParticles(x: number, y: number, z: number, blockId: number, seed: number): Particle[] {
  const def = BLOCKS[blockId]
  const base = def ? def.dust : ([128, 128, 128] as const)
  const out: Particle[] = []
  const count = 7
  for (let i = 0; i < count; i++) {
    const a = hash(seed, i * 3) * Math.PI * 2
    const b = hash(seed, i * 3 + 1)
    const c = hash(seed, i * 3 + 2)
    const speed = 1.2 + b * 1.6
    out.push({
      x: x + (hash(seed, i + 97) - 0.5) * 0.6,
      y: y + (hash(seed, i + 131) - 0.3) * 0.6,
      z: z + (hash(seed, i + 173) - 0.5) * 0.6,
      vx: Math.cos(a) * speed,
      vy: 1.2 + c * 1.8,
      vz: Math.sin(a) * speed,
      life: LIFE_MIN + hash(seed, i + 211) * (LIFE_MAX - LIFE_MIN),
      maxLife: LIFE_MAX,
      size: SIZE_MIN + hash(seed, i + 251) * (SIZE_MAX - SIZE_MIN),
      r: Math.max(0, Math.min(255, base[0] + (hash(seed, i + 283) - 0.5) * 40)),
      g: Math.max(0, Math.min(255, base[1] + (hash(seed, i + 307) - 0.5) * 40)),
      b: Math.max(0, Math.min(255, base[2] + (hash(seed, i + 331) - 0.5) * 40)),
    })
  }
  return out
}

/** 更新粒子:重力 + 寿命;返回还活着的粒子(会原地改 list 里的对象,减少分配) */
export function updateParticles(list: Particle[], dt: number): Particle[] {
  if (!list.length) return list
  if (!(dt > 0)) return list
  let keep = 0
  for (let i = 0; i < list.length; i++) {
    const p = list[i]
    p.life -= dt
    if (p.life <= 0) continue
    p.vy -= GRAVITY * dt
    p.x += p.vx * dt
    p.y += p.vy * dt
    p.z += p.vz * dt
    list[keep++] = p
  }
  list.length = keep
  return list
}

/** 把粒子投影到屏幕上画成小方块;投影函数由渲染器传入(和第一人称画面同一个相机) */
export function drawParticles(
  ctx: CanvasRenderingContext2D,
  list: readonly Particle[],
  project: (x: number, y: number, z: number) => [number, number, number] | null,
  scale: number,
): void {
  if (!list.length) return
  ctx.save()
  for (const p of list) {
    const proj = project(p.x, p.y, p.z)
    if (!proj) continue
    const [sx, sy, depth] = proj
    const px = Math.max(1.5, Math.min(8, (p.size * scale) / Math.max(0.4, depth)))
    const alpha = Math.max(0, Math.min(1, p.life / p.maxLife))
    ctx.globalAlpha = 0.35 + alpha * 0.6
    ctx.fillStyle = `rgb(${p.r | 0}, ${p.g | 0}, ${p.b | 0})`
    ctx.fillRect(sx - px / 2, sy - px / 2, px, px)
  }
  ctx.restore()
}
