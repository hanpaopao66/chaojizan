// Canvas 2D 第一人称体素渲染:DDA 光线投射 + 程序化纹理 + 天空/太阳/月亮 + 距离雾 + 水面半透明。
//
// 每帧流程:
// 1) 在内部低分辨率(约 40 万像素里取 9 万)缓冲里逐行铺天空色,再画太阳/月亮;
// 2) 每一列只做一次 2D DDA,记下射线经过的格子(格子里的实心/水的位图、最高点都在 World 里维护好);
// 3) 逐像素沿这一列向前走格子,在格子里找到射线遇到的第一个实心方块,从 16×16 纹理采样、按面给明暗、
//    叠雾和水色,写进缓冲;这一列里比「地形最高轮廓」还高的像素直接留天空;
// 4) 把低分辨率缓冲放大到整屏(最近邻,像素风),再在 CSS 像素空间画目标方块的白色描边。
//
// 这样躲开了逐像素做 3D DDA 的开销:一列的格子表只算一次,每个像素只做几次位运算。
import { WATER } from './blocks'
import type { RayHit } from './raycast'
import { TEX_BOTTOM, TEX_SIDE, TEX_TOP, buildTextures, type BlockTex } from './textures'
import { SUN_RADIUS, daylight, sunDirection, warmth } from './time'
import type { World } from './world'
import { D, H, SEA_LEVEL, W } from './worldgen'

/** 水平视场角(度) */
const HFOV = 78
/** 最远看多少格;更远的用雾吃掉 */
const RENDER_DIST = 46
/** 一列最多经过多少格(横向 46 格 + 斜着 1.5 倍,留足余量) */
const MAX_CELLS = 80
/** 内部缓冲目标像素数(乘以自适应画质系数) */
const TARGET_PIXELS = 96000

const FACE_TOP = 0
const FACE_BOTTOM = 1
const FACE_NEG_X = 2
const FACE_POS_X = 3
const FACE_NEG_Z = 4
const FACE_POS_Z = 5

/** 六个面的基础明暗(顶最亮、底最暗)。阳光最多再加 0.16,总亮度压在 1.06 以内,沙子才不会曝成白色 */
const FACE_SHADE: readonly number[] = [0.92, 0.4, 0.7, 0.74, 0.82, 0.78]
/** 六个面的法线 */
const FACE_NORMAL: ReadonlyArray<readonly [number, number, number]> = [
  [0, 1, 0], [0, -1, 0], [-1, 0, 0], [1, 0, 0], [0, 0, -1], [0, 0, 1],
]

type RGB = readonly [number, number, number]

const clamp = (v: number, lo: number, hi: number): number => (v < lo ? lo : v > hi ? hi : v)
const mix = (a: RGB, b: RGB, t: number): RGB => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
]
const pack = (r: number, g: number, b: number): number =>
  ((255 << 24) | ((b > 255 ? 255 : b < 0 ? 0 : b | 0) << 16) | ((g > 255 ? 255 : g < 0 ? 0 : g | 0) << 8)
    | (r > 255 ? 255 : r < 0 ? 0 : r | 0)) >>> 0

export interface Camera {
  /** 眼睛位置 */
  x: number
  y: number
  z: number
  yaw: number
  pitch: number
}

export interface RenderScene {
  cam: Camera
  /** 世界时间 0..1 */
  time: number
  /** 准星选中的方块(画描边);null = 没选中 */
  target: RayHit | null
  /** 挖掘进度 0..1(描边变暖色) */
  mining: number
}

// 天空/昼夜的颜色
const DAY_HORIZON: RGB = [196, 224, 242]
const DAY_ZENITH: RGB = [70, 132, 202]
const DAY_HAZE: RGB = [164, 192, 212]
const DAY_FOG: RGB = [176, 204, 222]
const NIGHT_HORIZON: RGB = [22, 32, 52]
const NIGHT_ZENITH: RGB = [6, 9, 20]
const NIGHT_HAZE: RGB = [16, 24, 40]
const NIGHT_FOG: RGB = [20, 28, 44]
const WARM: RGB = [255, 158, 100]
const UNDER_FOG: RGB = [24, 62, 108]
const UNDER_DEEP: RGB = [10, 34, 66]

export class Renderer {
  private readonly ctx: CanvasRenderingContext2D
  private readonly small: HTMLCanvasElement
  private readonly sctx: CanvasRenderingContext2D
  private readonly textures: BlockTex[]
  private cssW = 0
  private cssH = 0
  private dpr = 1
  private wi = 0
  private hi = 0
  private focal = 0
  private quality = 1
  private img: ImageData | null = null
  private img32 = new Uint32Array(0)
  private skyRow = new Uint32Array(0)
  // 每列 DDA 的结果缓冲(固定长度,复用以避免每帧分配)
  private colN = new Int32Array(0)
  private t0 = new Float32Array(MAX_CELLS)
  private t1 = new Float32Array(MAX_CELLS)
  private cx = new Int32Array(MAX_CELLS)
  private cz = new Int32Array(MAX_CELLS)
  private axis = new Int8Array(MAX_CELLS)
  // 每帧算一次的调色板
  private ambR = 1
  private ambG = 1
  private ambB = 1
  private fogR = 176
  private fogG = 204
  private fogB = 222
  private waterR = 40
  private waterG = 94
  private waterB = 150
  private faceLight = new Float32Array(6)

  constructor(private readonly canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('浏览器不支持 Canvas 2D')
    this.ctx = ctx
    this.small = document.createElement('canvas')
    const sctx = this.small.getContext('2d')
    if (!sctx) throw new Error('浏览器不支持 Canvas 2D')
    this.sctx = sctx
    this.textures = buildTextures()
  }

  /** 自适应画质:帧率跟不上时把内部渲染分辨率降一档 */
  setQuality(q: number): void {
    const next = clamp(q, 0.45, 1)
    if (Math.abs(next - this.quality) < 0.01) return
    this.quality = next
    this.prepareInternal()
  }

  get internalWidth(): number {
    return this.wi
  }

  /** 视口/DPR 变了就重建缓冲。返回有没有重建 */
  resize(): boolean {
    const rect = this.canvas.getBoundingClientRect()
    const cssW = Math.max(160, Math.round(rect.width))
    const cssH = Math.max(100, Math.round(rect.height))
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    if (cssW === this.cssW && cssH === this.cssH && dpr === this.dpr) return false
    this.cssW = cssW
    this.cssH = cssH
    this.dpr = dpr
    this.canvas.width = Math.round(cssW * dpr)
    this.canvas.height = Math.round(cssH * dpr)
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    this.ctx.imageSmoothingEnabled = false
    this.prepareInternal()
    return true
  }

  private prepareInternal(): void {
    const aspect = this.cssW / this.cssH
    let wi = Math.round(Math.sqrt(TARGET_PIXELS * this.quality * aspect))
    wi = clamp(Math.min(wi, this.cssW, 640), 200, 640)
    const hi = Math.max(120, Math.round(wi / aspect))
    if (wi === this.wi && hi === this.hi) return
    this.wi = wi
    this.hi = hi
    this.small.width = wi
    this.small.height = hi
    this.img = new ImageData(wi, hi)
    this.img32 = new Uint32Array(this.img.data.buffer)
    this.skyRow = new Uint32Array(hi)
    this.colN = new Int32Array(wi)
    this.focal = wi / 2 / Math.tan((HFOV * Math.PI) / 360)
  }

  render(world: World, scene: RenderScene): void {
    if (!this.img) this.resize()
    const img = this.img
    if (!img || !this.wi || !this.hi) return
    const { cam, time } = scene
    const wi = this.wi
    const hi = this.hi
    const focal = this.focal
    const img32 = this.img32
    const eyeX = cam.x
    const eyeY = cam.y
    const eyeZ = cam.z
    const cosYaw = Math.cos(cam.yaw)
    const sinYaw = Math.sin(cam.yaw)
    const fwdX = cosYaw
    const fwdZ = sinYaw
    const rightX = -sinYaw
    const rightZ = cosYaw
    const tanPitch = Math.tan(cam.pitch)
    const horizon = hi / 2 + focal * tanPitch

    // ---- 昼夜调色板
    const day = daylight(time)
    const warm = warmth(time) * (1 - day * 0.55)
    const under = world.blockAt(Math.floor(eyeX), Math.floor(eyeY), Math.floor(eyeZ)) === WATER
    const horizonCol = under ? UNDER_DEEP : mix(mix(NIGHT_HORIZON, DAY_HORIZON, day), WARM, warm * 0.62)
    const zenithCol = under ? UNDER_DEEP : mix(mix(NIGHT_ZENITH, DAY_ZENITH, day), [120, 96, 150], warm * 0.22)
    const hazeCol = under ? UNDER_FOG : mix(mix(NIGHT_HAZE, DAY_HAZE, day), WARM, warm * 0.3)
    const fogCol = under ? UNDER_FOG : mix(mix(NIGHT_FOG, DAY_FOG, day), WARM, warm * 0.28)
    const amb = mix(under ? [0.62, 0.8, 0.95] : [0.42, 0.47, 0.6], [1, 1, 1], under ? 0.25 : day)
    this.ambR = Math.min(1.02, amb[0] * (1 + 0.04 * warm))
    this.ambG = Math.min(1.02, amb[1] * (1 + 0.01 * warm))
    this.ambB = Math.min(1.02, amb[2] * (1 - 0.03 * warm))
    this.fogR = fogCol[0]
    this.fogG = fogCol[1]
    this.fogB = fogCol[2]
    const waterCol = mix([10, 24, 52], [40, 94, 150], day)
    this.waterR = waterCol[0]
    this.waterG = waterCol[1]
    this.waterB = waterCol[2]

    // ---- 天空逐行颜色(每行只算一次)
    const skyRow = this.skyRow
    for (let y = 0; y < hi; y++) {
      const k = (horizon - (y + 0.5)) / focal
      let c: RGB
      if (under) {
        c = mix(UNDER_DEEP, UNDER_FOG, clamp(0.5 - k * 0.8, 0, 1))
      } else if (k >= 0) {
        const a = Math.atan(k) / (Math.PI / 2)
        const f = Math.pow(a, 0.72)
        c = mix(horizonCol, zenithCol, f)
        if (warm > 0.03) c = mix(c, WARM, warm * 0.3 * (1 - f))
      } else {
        const a = Math.atan(-k) / (Math.PI / 2)
        c = mix(horizonCol, hazeCol, clamp(a * 2.4, 0, 1))
      }
      skyRow[y] = pack(c[0], c[1], c[2])
    }
    for (let y = 0; y < hi; y++) img32.fill(skyRow[y], y * wi, (y + 1) * wi)

    // ---- 太阳和月亮(先画进缓冲,地形会盖住它们)
    if (!under) {
      const sun = sunDirection(time)
      const sx = sun.x * fwdX + sun.z * fwdZ
      const sl = sun.x * rightX + sun.z * rightZ
      this.drawDisc(img32, wi, hi, horizon, focal, sx, sl, sun.y, focal * SUN_RADIUS,
        mix([255, 232, 170], [255, 250, 235], day), [255, 196, 120], clamp(day + warm, 0, 1))
      const moon: RGB = [-sun.x, -sun.y, -sun.z]
      this.drawDisc(img32, wi, hi, horizon, focal, moon[0] * fwdX + moon[2] * fwdZ,
        moon[0] * rightX + moon[2] * rightZ, moon[1], focal * SUN_RADIUS * 0.72,
        [226, 233, 246], [170, 196, 236], clamp(1 - day + 0.15, 0, 1))
    }

    // ---- 光照:每个面的明暗 + 太阳方向的额外亮度
    const sunDir = sunDirection(time)
    for (let f = 0; f < 6; f++) {
      const n = FACE_NORMAL[f]
      const dot = n[0] * sunDir.x + n[1] * sunDir.y + n[2] * sunDir.z
      const light = FACE_SHADE[f] + (dot > 0 ? dot * 0.16 * day : 0)
      this.faceLight[f] = light > 1.06 ? 1.06 : light
    }

    // ---- 逐列:一次 2D DDA 得到格子表 + 地形轮廓线
    const colN = this.colN
    const t0 = this.t0
    const t1 = this.t1
    const cxA = this.cx
    const czA = this.cz
    const axisA = this.axis
    const fogStart = under ? 1.5 : RENDER_DIST * 0.62
    const fogEnd = under ? 15 : RENDER_DIST * 1.05
    const fogK = 1 / (fogEnd - fogStart)
    const ambR = this.ambR
    const ambG = this.ambG
    const ambB = this.ambB
    const faceLight = this.faceLight
    const waterR = this.waterR
    const waterG = this.waterG
    const waterB = this.waterB
    const textures = this.textures
    const layer = W * D

    for (let x = 0; x < wi; x++) {
      const px = (x + 0.5 - wi / 2) / focal
      let dx = fwdX + rightX * px
      let dz = fwdZ + rightZ * px
      const invLen = 1 / Math.sqrt(dx * dx + dz * dz)
      dx *= invLen
      dz *= invLen
      const stx = dx > 0 ? 1 : -1
      const stz = dz > 0 ? 1 : -1
      let ix = Math.floor(eyeX)
      let iz = Math.floor(eyeZ)
      if (ix < 0) ix = 0
      else if (ix >= W) ix = W - 1
      if (iz < 0) iz = 0
      else if (iz >= D) iz = D - 1
      const tDeltaX = dx === 0 ? Infinity : Math.abs(1 / dx)
      const tDeltaZ = dz === 0 ? Infinity : Math.abs(1 / dz)
      let tMaxX = dx === 0 ? Infinity : (dx > 0 ? ix + 1 - eyeX : eyeX - ix) / Math.abs(dx)
      let tMaxZ = dz === 0 ? Infinity : (dz > 0 ? iz + 1 - eyeZ : eyeZ - iz) / Math.abs(dz)
      if (tMaxX < 0) tMaxX = 0
      if (tMaxZ < 0) tMaxZ = 0
      let t = 0
      let axis = 0
      let n = 0
      let skyline = hi + 2
      while (n < MAX_CELLS) {
        let tNext = tMaxX < tMaxZ ? tMaxX : tMaxZ
        if (!(tNext < RENDER_DIST)) tNext = RENDER_DIST
        t0[n] = t
        t1[n] = tNext
        cxA[n] = ix
        czA[n] = iz
        axisA[n] = axis
        // 地形轮廓:这一列最高实心格(有水时算水面)投影到屏幕上沿
        const col = ix + iz * W
        const topY = world.top[col]
        let surf = topY + 1
        if (surf < SEA_LEVEL && (world.waterLo[col] | world.waterHi[col]) !== 0) surf = SEA_LEVEL
        if (n === 0 && surf < eyeY) surf = Math.floor(eyeY) + 1
        if (surf > 0) {
          const projY = horizon - (focal * (surf - eyeY)) / (t > 0.05 ? t : 0.05)
          if (projY < skyline) skyline = projY
        }
        n++
        if (tNext >= RENDER_DIST) break
        t = tNext
        if (tMaxX < tMaxZ) {
          ix += stx
          tMaxX += tDeltaX
          axis = 1
        } else {
          iz += stz
          tMaxZ += tDeltaZ
          axis = 2
        }
        if (ix < 0 || ix >= W || iz < 0 || iz >= D) break
      }
      colN[x] = n
      if (!n) continue

      // ---- 逐像素:沿这一列的格子表找到第一个挡住视线的方块
      const startY = clamp(Math.floor(skyline) - 1, 0, hi)
      for (let y = startY; y < hi; y++) {
        const k = (horizon - (y + 0.5)) / focal
        let r = 0
        let g = 0
        let b = 0
        let tHit = RENDER_DIST
        let found = false
        for (let c = 0; c < n; c++) {
          const tA = t0[c]
          const tB = t1[c]
          const ya = eyeY + k * tA
          const yb = eyeY + k * tB
          let loY = Math.floor(ya < yb ? ya : yb)
          let hiY = Math.floor(ya < yb ? yb : ya)
          if (hiY < 0 || loY >= H) {
            // 射线已经走出世界的高度范围:往上走的后面只会更高,直接停
            if (k > 0) break
            continue
          }
          if (loY < 0) loY = 0
          if (hiY > H - 1) hiY = H - 1
          // 这个高度范围对应的两个 32 位掩码
          let mLo = 0
          let mHi = 0
          if (loY < 32) {
            mLo = 0xffffffff << loY
            if (hiY < 31) mLo &= 0xffffffff >>> (31 - hiY)
          }
          if (hiY >= 32) {
            mHi = 0xffffffff >>> (31 - (hiY - 32))
            if (loY > 32) mHi &= 0xffffffff << (loY - 32)
          }
          const col = cxA[c] + czA[c] * W
          const omLo = world.opaqueLo[col] & mLo
          const omHi = world.opaqueHi[col] & mHi
          if (!(omLo | omHi)) continue
          // 第一个不透明方块:往下取最高位、往上取最低位
          let hitY = -1
          let th = 0
          let face = FACE_TOP
          const axisFace = axisA[c] === 1
            ? (stx > 0 ? FACE_NEG_X : FACE_POS_X)
            : (stz > 0 ? FACE_NEG_Z : FACE_POS_Z)
          if (k < -1e-6) {
            if (omHi) hitY = 32 + (31 - Math.clz32(omHi))
            else hitY = 31 - Math.clz32(omLo)
            if (ya > hitY + 1) {
              face = FACE_TOP
              th = (hitY + 1 - eyeY) / k
            } else {
              face = axisA[c] ? axisFace : FACE_TOP
              th = tA
            }
          } else if (k > 1e-6) {
            if (omLo) hitY = 31 - Math.clz32(omLo & -omLo)
            else hitY = 32 + (31 - Math.clz32(omHi & -omHi))
            if (ya < hitY) {
              face = FACE_BOTTOM
              th = (hitY - eyeY) / k
            } else {
              face = axisA[c] ? axisFace : FACE_BOTTOM
              th = tA
            }
          } else {
            const fy = clamp(Math.floor(eyeY), 0, H - 1)
            const bit = fy < 32 ? 1 << fy : 1 << (fy - 32)
            const has = fy < 32 ? omLo & bit : omHi & bit
            if (!has) continue
            hitY = fy
            face = axisA[c] ? axisFace : FACE_TOP
            th = tA
          }
          if (hitY < 0 || hitY >= H) continue
          if (th < 0) th = 0
          tHit = th
          const hx = eyeX + dx * th
          const hz = eyeZ + dz * th
          const hy = eyeY + k * th
          let u: number
          let v: number
          if (face === FACE_TOP) {
            u = hx - Math.floor(hx)
            v = hz - Math.floor(hz)
          } else if (face === FACE_BOTTOM) {
            u = hx - Math.floor(hx)
            v = 1 - (hz - Math.floor(hz))
          } else if (face === FACE_NEG_X || face === FACE_POS_X) {
            u = hz - Math.floor(hz)
            v = 1 - (hy - Math.floor(hy))
          } else {
            u = hx - Math.floor(hx)
            v = 1 - (hy - Math.floor(hy))
          }
          const bid = world.blocks[col + layer * hitY]
          const tex = textures[bid][face === FACE_TOP ? TEX_TOP : face === FACE_BOTTOM ? TEX_BOTTOM : TEX_SIDE]
          const tx = clamp((u * 16) | 0, 0, 15)
          const ty = clamp((v * 16) | 0, 0, 15)
          const texel = tex[(ty << 4) + tx]
          const light = faceLight[face]
          r = (texel & 255) * light * ambR
          g = ((texel >>> 8) & 255) * light * ambG
          b = ((texel >>> 16) & 255) * light * ambB
          // 距离雾
          const fog = (tHit - fogStart) * fogK
          if (fog > 0) {
            const ff = fog > 1 ? 1 : fog
            r += (this.fogR - r) * ff
            g += (this.fogG - g) * ff
            b += (this.fogB - b) * ff
          }
          found = true
          break
        }
        if (!found) {
          // 什么都没打到:用这一行本来的天空/海雾色
          const base = img32[y * wi + x]
          r = base & 255
          g = (base >>> 8) & 255
          b = (base >>> 16) & 255
          tHit = RENDER_DIST
        }
        // ---- 水面:眼睛在海面之上、射线向下穿过海平面时,把水面当成一层半透明的平面,
        //      底下的东西(沙子、深海雾)按距离和水深透出来。
        if (!under && k < -1e-6) {
          const tSea = (SEA_LEVEL - eyeY) / k
          if (tSea > 0.2 && tSea < tHit && tSea < RENDER_DIST + 4) {
            const wx = eyeX + dx * tSea
            const wz = eyeZ + dz * tSea
            // 轻微波光:让大水面有细节,不是一块死色
            const sparkle = Math.sin(wx * 1.9 + time * 1.6) * Math.sin(wz * 1.5 - time * 1.2)
            const fogSea = clamp((tSea - fogStart) * fogK, 0, 1)
            const wr = waterR + (this.fogR - waterR) * fogSea
            const wg = waterG + (this.fogG - waterG) * fogSea
            const wb = waterB + (this.fogB - waterB) * fogSea
            const depth = tHit - tSea
            let alpha = 0.46 + 0.2 * Math.min(1, depth / 14) + sparkle * 0.06
            if (alpha < 0.3) alpha = 0.3
            else if (alpha > 0.82) alpha = 0.82
            r += (wr - r) * alpha
            g += (wg - g) * alpha
            b += (wb - b) * alpha
          }
        }
        img32[y * wi + x] = pack(r, g, b)
      }
    }

    // ---- 放大到整屏
    this.sctx.putImageData(img, 0, 0)
    const ctx = this.ctx
    ctx.imageSmoothingEnabled = false
    ctx.drawImage(this.small, 0, 0, this.cssW, this.cssH)
    // ---- 目标方块的描边
    if (scene.target) this.drawTarget(ctx, scene.target, cam, focal, scene.mining)
  }

  /** 把太阳/月亮画进低分辨率缓冲:圆盘 + 外圈光晕 */
  private drawDisc(img32: Uint32Array, wi: number, hi: number, horizon: number, focal: number,
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

  /** 目标方块:把可见面的轮廓投影到屏幕上,画成白色描边(挖到一半变暖色) */
  private drawTarget(ctx: CanvasRenderingContext2D, target: RayHit, cam: Camera,
    focal: number, mining: number): void {
    const s = this.cssW / this.wi
    const f = focal * s
    const hz = this.cssH / 2 + f * Math.tan(cam.pitch)
    const cosYaw = Math.cos(cam.yaw)
    const sinYaw = Math.sin(cam.yaw)
    const fwdX = cosYaw
    const fwdZ = sinYaw
    const rightX = -sinYaw
    const rightZ = cosYaw
    const project = (wx: number, wy: number, wz: number): [number, number] | null => {
      const relX = wx - cam.x
      const relY = wy - cam.y
      const relZ = wz - cam.z
      const depth = relX * fwdX + relZ * fwdZ
      if (depth < 0.25) return null
      const lateral = relX * rightX + relZ * rightZ
      return [this.cssW / 2 + (f * lateral) / depth, hz - (f * relY) / depth]
    }
    const b = target
    // 只画准星真正命中的那个面:贴着方块看时不会从视角后面拉出奇怪的斜线
    let corners: Array<[number, number, number]>
    switch (target.face) {
      case 'y+':
        corners = [[b.x, b.y + 1, b.z], [b.x + 1, b.y + 1, b.z], [b.x + 1, b.y + 1, b.z + 1], [b.x, b.y + 1, b.z + 1]]
        break
      case 'y-':
        corners = [[b.x, b.y, b.z], [b.x + 1, b.y, b.z], [b.x + 1, b.y, b.z + 1], [b.x, b.y, b.z + 1]]
        break
      case 'x+':
        corners = [[b.x + 1, b.y, b.z], [b.x + 1, b.y + 1, b.z], [b.x + 1, b.y + 1, b.z + 1], [b.x + 1, b.y, b.z + 1]]
        break
      case 'x-':
        corners = [[b.x, b.y, b.z], [b.x, b.y + 1, b.z], [b.x, b.y + 1, b.z + 1], [b.x, b.y, b.z + 1]]
        break
      case 'z+':
        corners = [[b.x, b.y, b.z + 1], [b.x + 1, b.y, b.z + 1], [b.x + 1, b.y + 1, b.z + 1], [b.x, b.y + 1, b.z + 1]]
        break
      default:
        corners = [[b.x, b.y, b.z], [b.x + 1, b.y, b.z], [b.x + 1, b.y + 1, b.z], [b.x, b.y + 1, b.z]]
        break
    }
    const pts: Array<[number, number]> = []
    for (const [wx, wy, wz] of corners) {
      const p = project(wx, wy, wz)
      if (!p) return
      if (!Number.isFinite(p[0]) || !Number.isFinite(p[1])) return
      if (Math.abs(p[0]) > 20000 || Math.abs(p[1]) > 20000) return
      pts.push(p)
    }
    const path = new Path2D()
    path.moveTo(pts[0][0], pts[0][1])
    path.lineTo(pts[1][0], pts[1][1])
    path.lineTo(pts[2][0], pts[2][1])
    path.lineTo(pts[3][0], pts[3][1])
    path.closePath()
    ctx.save()
    ctx.lineJoin = 'round'
    const warm = clamp(mining, 0, 1)
    const color = warm > 0
      ? `rgba(255, ${Math.round(230 - 90 * warm)}, ${Math.round(140 - 90 * warm)}, 0.95)`
      : 'rgba(255, 255, 255, 0.92)'
    ctx.lineWidth = 4
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)'
    ctx.stroke(path)
    ctx.lineWidth = 2
    ctx.strokeStyle = color
    ctx.stroke(path)
    ctx.restore()
  }
}
