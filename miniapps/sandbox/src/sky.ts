// 天空:渐变、太阳/月亮、云、星星。纯计算(除了往 ImageData 缓冲写像素),渲染器每帧调一次。
//
// 云和星星都用固定种子的程序化贴图(64×32 的平滑随机场),按「方位角 + 仰角」取样:
// 转头时云跟着动、抬头能看到云层和星空;不加载任何图片。
import { PALETTE, VIEW } from './data'
import { daylight, sunDirection, warmth } from './time'

export type RGB = readonly [number, number, number]

export interface SkyColors {
  day: number
  warm: number
  under: boolean
  horizon: RGB
  zenith: RGB
  haze: RGB
  fog: RGB
  ambient: RGB
  water: RGB
}

const clamp = (v: number, lo: number, hi: number): number => (v < lo ? lo : v > hi ? hi : v)
const mix = (a: RGB, b: RGB, t: number): RGB => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
]
const pack = (r: number, g: number, b: number): number =>
  ((255 << 24) | ((b > 255 ? 255 : b < 0 ? 0 : b | 0) << 16) | ((g > 255 ? 255 : g < 0 ? 0 : g | 0) << 8)
    | (r > 255 ? 255 : r < 0 ? 0 : r | 0)) >>> 0

/** 这一帧的天空颜色(昼夜过渡 + 日出日落暖色 + 水下) */
export function computeSky(time: number, under: boolean): SkyColors {
  const day = daylight(time)
  const warm = warmth(time) * (1 - day * 0.55)
  const horizon = under ? PALETTE.UNDER_DEEP : mix(mix(PALETTE.NIGHT_HORIZON, PALETTE.DAY_HORIZON, day), PALETTE.WARM, warm * 0.62)
  const zenith = under ? PALETTE.UNDER_DEEP : mix(mix(PALETTE.NIGHT_ZENITH, PALETTE.DAY_ZENITH, day), PALETTE.WARM_ZENITH, warm * 0.22)
  const haze = under ? PALETTE.UNDER_FOG : mix(mix(PALETTE.NIGHT_HAZE, PALETTE.DAY_HAZE, day), PALETTE.WARM, warm * 0.3)
  const fog = under ? PALETTE.UNDER_FOG : mix(mix(PALETTE.NIGHT_FOG, PALETTE.DAY_FOG, day), PALETTE.WARM, warm * 0.28)
  const amb = mix(under ? PALETTE.WATER_UNDER_AMBIENT : PALETTE.NIGHT_AMBIENT, PALETTE.DAY_AMBIENT, under ? 0.25 : day)
  const water = under ? PALETTE.WATER_NIGHT : mix(PALETTE.WATER_NIGHT, PALETTE.WATER_DAY, day)
  return {
    day,
    warm,
    under,
    horizon,
    zenith,
    haze,
    fog,
    ambient: [
      Math.min(1.02, amb[0] * (1 + 0.04 * warm)),
      Math.min(1.02, amb[1] * (1 + 0.01 * warm)),
      Math.min(1.02, amb[2] * (1 - 0.03 * warm)),
    ],
    water,
  }
}

// ---------------------------------------------------------------- 程序化贴图

/** 固定种子的平滑随机场,给云用 */
export function makeCloudTexture(): Float32Array {
  const w = VIEW.CLOUD_W
  const h = VIEW.CLOUD_H
  const out = new Float32Array(w * h)
  // 先用稀疏的随机格点,再做两遍可分离平滑,得到软软的云团
  let seed = 0x9e3779b9
  const rand = (): number => {
    seed = (seed + 0x6d2b79f5) >>> 0
    let t = seed
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  type F32 = Float32Array<ArrayBuffer>
  const grid: F32 = new Float32Array(w * h)
  for (let i = 0; i < grid.length; i++) grid[i] = rand()
  const blur = (src: F32): F32 => {
    const dst: F32 = new Float32Array(src.length)
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        let sum = 0
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) sum += src[((y + dy + h) % h) * w + ((x + dx + w) % w)]
        }
        dst[y * w + x] = sum / 9
      }
    }
    return dst
  }
  let cur: F32 = grid
  for (let i = 0; i < 3; i++) cur = blur(cur)
  // 归一化到 0..1
  let lo = Infinity
  let hi = -Infinity
  for (const v of cur) {
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  const span = hi - lo || 1
  for (let i = 0; i < out.length; i++) out[i] = (cur[i] - lo) / span
  return out
}

/** 星星贴图:大部分是 0,少数亮点(固定种子) */
export function makeStarTexture(): Float32Array {
  const w = VIEW.CLOUD_W
  const h = VIEW.CLOUD_H
  const out = new Float32Array(w * h)
  let seed = 0x51ed270b
  const rand = (): number => {
    seed = (seed + 0x6d2b79f5) >>> 0
    let t = seed
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  for (let i = 0; i < out.length; i++) {
    out[i] = rand() > 0.955 ? 0.5 + rand() * 0.5 : 0
  }
  return out
}

// ---------------------------------------------------------------- 画到缓冲

/** 太阳/月亮:圆盘 + 外圈光晕 */
export function drawDisc(img32: Uint32Array, wi: number, hi: number, horizon: number, focal: number,
  depth: number, lateral: number, up: number, radius: number, core: RGB, glow: RGB, strength: number): void {
  if (depth < 0.08 || radius < 1) return
  const sx = wi / 2 + (focal * lateral) / depth
  const sy = horizon - (focal * up) / depth
  const glowR = radius * 3.2
  const x0 = Math.max(0, Math.floor(sx - glowR))
  const x1 = Math.min(wi - 1, Math.ceil(sx + glowR))
  const y0 = Math.max(0, Math.floor(sy - glowR))
  const y1 = Math.min(hi - 1, Math.ceil(sy + glowR))
  if (x1 < x0 || y1 < y0) return
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const dx = x + 0.5 - sx
      const dy = y + 0.5 - sy
      const d = Math.sqrt(dx * dx + dy * dy)
      if (d > glowR) continue
      const idx = y * wi + x
      let r = img32[idx] & 255
      let g = (img32[idx] >>> 8) & 255
      let b = (img32[idx] >>> 16) & 255
      if (d <= radius) {
        const edge = d > radius - 1.5 ? (radius - d) / 1.5 : 1
        r += (core[0] - r) * edge
        g += (core[1] - g) * edge
        b += (core[2] - b) * edge
      } else {
        const t = 1 - (d - radius) / (glowR - radius)
        const a = t * t * 0.5 * strength
        r += glow[0] * a
        g += glow[1] * a
        b += glow[2] * a
      }
      img32[idx] = pack(r, g, b)
    }
  }
}

/** 双线性采样 64×32 的贴图(x、y 两个方向都循环,云可以铺满整个仰角) */
function sampleTex(tex: Float32Array, u: number, v: number): number {
  const w = VIEW.CLOUD_W
  const h = VIEW.CLOUD_H
  const uu = u - Math.floor(u / w) * w
  const vv = v - Math.floor(v / h) * h
  const x0 = Math.floor(uu)
  const y0 = Math.floor(vv)
  const fx = uu - x0
  const fy = vv - y0
  const x1 = (x0 + 1) % w
  const y1 = (y0 + 1) % h
  const a = tex[y0 * w + x0] + (tex[y0 * w + x1] - tex[y0 * w + x0]) * fx
  const b = tex[y1 * w + x0] + (tex[y1 * w + x1] - tex[y1 * w + x0]) * fx
  return a + (b - a) * fy
}

/** 最近邻采样:星星要的是锐利的小点,不能双线性糊开 */
function sampleNearest(tex: Float32Array, u: number, v: number): number {
  const w = VIEW.CLOUD_W
  const h = VIEW.CLOUD_H
  const x = ((Math.floor(u) % w) + w) % w
  const y = ((Math.floor(v) % h) + h) % h
  return tex[y * w + x]
}

export interface SkyBuffers {
  cloud: Float32Array
  star: Float32Array
}

/**
 * 铺天空:逐行底色 → 太阳/月亮 → 云 → 星空。
 * colDirX/colDirZ 是每列的水平视线方向(单位向量),云按方位角取样,所以转头会动。
 */
export function fillSky(img32: Uint32Array, wi: number, hi: number, horizon: number, focal: number,
  colors: SkyColors, time: number, colDirX: Float32Array, colDirZ: Float32Array,
  fwdX: number, fwdZ: number, rightX: number, rightZ: number, buf: SkyBuffers): void {
  const under = colors.under
  // 1) 逐行底色
  for (let y = 0; y < hi; y++) {
    const k = (horizon - (y + 0.5)) / focal
    let c: RGB
    if (under) {
      c = mix(PALETTE.UNDER_DEEP, PALETTE.UNDER_FOG, clamp(0.5 - k * 0.8, 0, 1))
    } else if (k >= 0) {
      const a = Math.atan(k) / (Math.PI / 2)
      const f = Math.pow(a, 0.72)
      c = mix(colors.horizon, colors.zenith, f)
      if (colors.warm > 0.03) c = mix(c, PALETTE.WARM, colors.warm * 0.3 * (1 - f))
    } else {
      const a = Math.atan(-k) / (Math.PI / 2)
      c = mix(colors.horizon, colors.haze, clamp(a * 2.4, 0, 1))
    }
    img32.fill(pack(c[0], c[1], c[2]), y * wi, (y + 1) * wi)
  }
  if (under) return

  // 2) 太阳和月亮
  const sun = sunDirection(time)
  const sunDepth = sun.x * fwdX + sun.z * fwdZ
  drawDisc(img32, wi, hi, horizon, focal, sunDepth, sun.x * rightX + sun.z * rightZ, sun.y,
    focal * VIEW.SUN_RADIUS,
    mix(PALETTE.SUN_CORE, PALETTE.SUN_CORE_NOON, colors.day), PALETTE.SUN_GLOW, clamp(colors.day + colors.warm, 0, 1))
  drawDisc(img32, wi, hi, horizon, focal, -sunDepth, -sun.x * rightX - sun.z * rightZ, -sun.y,
    focal * VIEW.SUN_RADIUS * VIEW.MOON_RADIUS_FACTOR,
    PALETTE.MOON_CORE, PALETTE.MOON_GLOW, clamp(1 - colors.day + 0.15, 0, 1))

  // 3) 云 + 星星:只在水平线以上;地平线附近淡出,避免糊在远山上
  const cloudCol = mix(PALETTE.CLOUD_NIGHT, PALETTE.CLOUD_DAY, colors.day)
  const starAlpha = (1 - colors.day) * VIEW.STAR_ALPHA
  const drift = time * VIEW.CLOUD_DRIFT * 360
  // 云和星星都投到「头顶的一层平面」上:视线方向仰角越低,平面上的落点越远(贴近地平线的云被拉长),
  // 抬头看就是头顶的云团;这样接近垂直仰视也不会变成竖条纹。
  const skyBottom = Math.min(hi - 1, Math.floor(horizon))
  // 星星:按方位角/仰角铺在整片天上,只用最近邻采样(双线性会把点糊成大团)
  let colAz: Float32Array | null = null
  if (starAlpha > 0.02) {
    colAz = new Float32Array(wi)
    for (let x = 0; x < wi; x++) {
      colAz[x] = (Math.atan2(colDirZ[x], colDirX[x]) / (Math.PI * 2)) * VIEW.CLOUD_W * 4
    }
  }
  for (let y = 0; y <= skyBottom; y++) {
    const k = (horizon - (y + 0.5)) / focal
    if (k < 0.02) continue
    // 接近天顶时(仰角 > ~78°)云和星星会被 y-shear 投影拉得很长,淡出掉保持干净
    const sinElev = k / Math.sqrt(1 + k * k)
    const zenithFade = clamp((0.985 - sinElev) / 0.06, 0, 1)
    const fade = clamp(k * 6, 0, 1) * zenithFade
    const plane = Math.min(48, 10 / Math.max(0.06, sinElev))
    const ox = drift * 6
    const elevNorm = Math.atan(k) / (Math.PI / 2)
    const vStar = elevNorm * VIEW.CLOUD_H * 2
    for (let x = 0; x < wi; x++) {
      const dirX = colDirX[x]
      const dirZ = colDirZ[x]
      const u = dirX * plane + ox
      const v = dirZ * plane + 16
      const idx = y * wi + x
      let r = img32[idx] & 255
      let g = (img32[idx] >>> 8) & 255
      let b = (img32[idx] >>> 16) & 255
      if (colAz && starAlpha > 0.02) {
        const s = sampleNearest(buf.star, colAz[x], vStar)
        if (s > 0.4) {
          const a = Math.min(1, s) * starAlpha * fade
          r += (240 - r) * a
          g += (244 - g) * a
          b += (255 - b) * a
        }
      }
      if (fade > 0.02) {
        const n = sampleTex(buf.cloud, u, v)
        const cloud = clamp((n - 0.46) / 0.36, 0, 1)
        if (cloud > 0.01) {
          const a = cloud * VIEW.CLOUD_ALPHA * fade * (0.45 + colors.day * 0.55)
          r += (cloudCol[0] - r) * a
          g += (cloudCol[1] - g) * a
          b += (cloudCol[2] - b) * a
        }
      }
      img32[idx] = pack(r, g, b)
    }
  }
}
