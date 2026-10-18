// Canvas 2D 第一人称体素渲染:DDA 光线投射 + 程序化纹理(3 个变体)+ 天空/云/星 + 距离雾 +
// 水面波纹反光 + 挖掘裂纹 + 目标描边 + 碎屑粒子。
//
// 每帧流程:
// 1) 计算每列的朝向 → sky.ts 铺天空(渐变、太阳/月亮、云、星星);
// 2) 每一列只做一次 2D DDA,记下射线经过的格子(实心/水的位图、最高点都在 World 里维护好);
// 3) 逐像素沿这一列向前走格子,找到第一个实心方块,从 16×16×3 变体的纹理采样、按面给明暗、
//    叠雾和水面,写进缓冲;比「地形最高轮廓」还高的像素直接留天空;
// 4) 低分辨率缓冲放大到整屏(最近邻,像素风),再在 CSS 像素空间画目标描边和碎屑粒子。
//
// 这样躲开了逐像素做 3D DDA 的开销:一列的格子表只算一次,每个像素只做几次位运算。
import { WATER } from './blocks'
import {
  FACE_BOTTOM, FACE_NEG_X, FACE_NEG_Z, FACE_NORMAL, FACE_POS_X, FACE_POS_Z, FACE_SHADE, FACE_TOP,
  LIGHT_MAX, SUN_FACE_GAIN, VIEW,
} from './data'
import { drawParticles, type Particle } from './particles'
import type { RayHit } from './raycast'
import {
  computeSky, fillSky, makeCloudTexture, makeStarTexture, type SkyBuffers,
} from './sky'
import { buildCrackTextures, buildTextures, sampleFace, TEX_BOTTOM, TEX_SIDE, TEX_TOP, TEX_VARIANTS, type BlockTex } from './textures'
import { sunDirection } from './time'
import type { World } from './world'
import { D, H, SEA_LEVEL, W } from './worldgen'

/** 六个面的基础明暗之外,太阳方向最多再加多少亮度 */
const MAX_CELLS = VIEW.MAX_CELLS

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
  /** 准星选中的方块(画描边和裂纹);null = 没选中 */
  target: RayHit | null
  /** 挖掘进度 0..1 */
  mining: number
  /** 碎屑粒子 */
  particles: readonly Particle[]
}

const clamp = (v: number, lo: number, hi: number): number => (v < lo ? lo : v > hi ? hi : v)
const mix = (a: readonly number[], b: readonly number[], t: number): number[] => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
]
const pack = (r: number, g: number, b: number): number =>
  ((255 << 24) | ((b > 255 ? 255 : b < 0 ? 0 : b | 0) << 16) | ((g > 255 ? 255 : g < 0 ? 0 : g | 0) << 8)
    | (r > 255 ? 255 : r < 0 ? 0 : r | 0)) >>> 0

const TEX_W = 16

/** 目标的面 → 内部面编号 */
function faceIndexOf(face: RayHit['face']): number {
  switch (face) {
    case 'y+': return FACE_TOP
    case 'y-': return FACE_BOTTOM
    case 'x-': return FACE_NEG_X
    case 'x+': return FACE_POS_X
    case 'z-': return FACE_NEG_Z
    default: return FACE_POS_Z
  }
}

/** 目标的面 → 用哪张纹理(顶/侧/底) */
function texFaceOf(face: number): number {
  if (face === FACE_TOP) return TEX_TOP
  if (face === FACE_BOTTOM) return TEX_BOTTOM
  return TEX_SIDE
}

export class Renderer {
  private readonly ctx: CanvasRenderingContext2D
  private readonly small: HTMLCanvasElement
  private readonly sctx: CanvasRenderingContext2D
  private readonly textures: BlockTex[]
  private readonly cracks: Uint8Array[]
  private readonly skyBuf: SkyBuffers = { cloud: makeCloudTexture(), star: makeStarTexture() }
  private cssW = 0
  private cssH = 0
  private dpr = 1
  private wi = 0
  private hi = 0
  private focal = 0
  private quality = 1
  private img: ImageData | null = null
  private img32 = new Uint32Array(0)
  // 每列 DDA 的结果缓冲(固定长度,复用以避免每帧分配)
  private colN = new Int32Array(0)
  private colDirX = new Float32Array(0)
  private colDirZ = new Float32Array(0)
  private t0 = new Float32Array(MAX_CELLS)
  private t1 = new Float32Array(MAX_CELLS)
  private cx = new Int32Array(MAX_CELLS)
  private cz = new Int32Array(MAX_CELLS)
  private axis = new Int8Array(MAX_CELLS)
  // 每帧算一次的光照
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
    this.cracks = buildCrackTextures()
  }

  /** 自适应画质:帧率跟不上时把内部渲染分辨率降一档 */
  setQuality(q: number): void {
    const next = clamp(q, VIEW.QUALITY_MIN, 1)
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
    let wi = Math.round(Math.sqrt(VIEW.TARGET_PIXELS * this.quality * aspect))
    wi = clamp(Math.min(wi, this.cssW, VIEW.MAX_INTERNAL_W), VIEW.MIN_INTERNAL_W, VIEW.MAX_INTERNAL_W)
    const hi = Math.max(VIEW.MIN_INTERNAL_H, Math.round(wi / aspect))
    if (wi === this.wi && hi === this.hi) return
    this.wi = wi
    this.hi = hi
    this.small.width = wi
    this.small.height = hi
    this.img = new ImageData(wi, hi)
    this.img32 = new Uint32Array(this.img.data.buffer)
    this.colN = new Int32Array(wi)
    this.colDirX = new Float32Array(wi)
    this.colDirZ = new Float32Array(wi)
    this.focal = wi / 2 / Math.tan((VIEW.HFOV * Math.PI) / 360)
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
    const horizon = hi / 2 + focal * Math.tan(cam.pitch)
    const under = world.blockAt(Math.floor(eyeX), Math.floor(eyeY), Math.floor(eyeZ)) === WATER

    // ---- 天空(渐变 + 太阳/月亮 + 云 + 星),顺带算好这一帧的光照和雾色
    const colors = computeSky(time, under)
    for (let x = 0; x < wi; x++) {
      const px = (x + 0.5 - wi / 2) / focal
      let dx = fwdX + rightX * px
      let dz = fwdZ + rightZ * px
      const inv = 1 / Math.sqrt(dx * dx + dz * dz)
      dx *= inv
      dz *= inv
      this.colDirX[x] = dx
      this.colDirZ[x] = dz
    }
    fillSky(img32, wi, hi, horizon, focal, colors, time, this.colDirX, this.colDirZ, fwdX, fwdZ, rightX, rightZ, this.skyBuf)

    // ---- 光照:面的基础明暗 + 太阳方向的额外亮度;环境色按昼夜调
    const sun = sunDirection(time)
    for (let f = 0; f < 6; f++) {
      const n = FACE_NORMAL[f]
      const dot = n[0] * sun.x + n[1] * sun.y + n[2] * sun.z
      const light = FACE_SHADE[f] + (dot > 0 ? dot * SUN_FACE_GAIN * colors.day : 0)
      this.faceLight[f] = light > LIGHT_MAX ? LIGHT_MAX : light
    }
    const ambR = colors.ambient[0]
    const ambG = colors.ambient[1]
    const ambB = colors.ambient[2]
    const fogR = colors.fog[0]
    const fogG = colors.fog[1]
    const fogB = colors.fog[2]

    // ---- 目标方块:裂纹只画在它身上
    const target = scene.target
    const targetFace = target ? faceIndexOf(target.face) : -1
    const crackStage = target && scene.mining > 0
      ? Math.min(3, Math.floor(scene.mining * 4)) : -1
    const crackTex = crackStage >= 0 ? this.cracks[crackStage] : null

    // ---- 逐列:一次 2D DDA 得到格子表 + 地形轮廓线
    const colN = this.colN
    const t0 = this.t0
    const t1 = this.t1
    const cxA = this.cx
    const czA = this.cz
    const axisA = this.axis
    const textures = this.textures
    const faceLight = this.faceLight
    const layer = W * D
    const fogStart = under ? VIEW.UNDER_FOG_START : VIEW.RENDER_DIST * VIEW.FOG_START_RATIO
    const fogEnd = under ? VIEW.UNDER_FOG_END : VIEW.RENDER_DIST * VIEW.FOG_END_RATIO
    const fogK = 1 / (fogEnd - fogStart)
    const waterCol = colors.water
    const horizonCol = colors.horizon

    for (let x = 0; x < wi; x++) {
      const dx = this.colDirX[x]
      const dz = this.colDirZ[x]
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
        if (!(tNext < VIEW.RENDER_DIST)) tNext = VIEW.RENDER_DIST
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
        if (tNext >= VIEW.RENDER_DIST) break
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
        let tHit: number = VIEW.RENDER_DIST
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
          const texVariant = (cxA[c] * 7 + hitY * 13 + czA[c] * 23) % TEX_VARIANTS
          const tex = textures[bid][texFaceOf(face)]
          const tx = clamp((u * TEX_W) | 0, 0, TEX_W - 1)
          const ty = clamp((v * TEX_W) | 0, 0, TEX_W - 1)
          const texel = sampleFace(tex, texVariant, tx, ty)
          let tr = (texel & 255) * faceLight[face] * ambR
          let tg = ((texel >>> 8) & 255) * faceLight[face] * ambG
          let tb = ((texel >>> 16) & 255) * faceLight[face] * ambB
          // 挖掘裂纹:只盖在准星对着的那个方块的那个面上
          if (crackTex && target && targetFace === face
            && cxA[c] === target.x && czA[c] === target.z && hitY === target.y) {
            const dark = crackTex[ty * TEX_W + tx]
            if (dark > 0) {
              const f = 1 - (dark / 255) * 0.62
              tr *= f
              tg *= f
              tb *= f
            }
          }
          // 距离雾
          const fog = (tHit - fogStart) * fogK
          if (fog > 0) {
            const ff = fog > 1 ? 1 : fog
            tr += (fogR - tr) * ff
            tg += (fogG - tg) * ff
            tb += (fogB - tb) * ff
          }
          r = tr
          g = tg
          b = tb
          found = true
          break
        }
        if (!found) {
          // 什么都没打到:用这一行本来的天空/海雾色
          const base = img32[y * wi + x]
          r = base & 255
          g = (base >>> 8) & 255
          b = (base >>> 16) & 255
          tHit = VIEW.RENDER_DIST
        }
        // ---- 水面:眼睛在海面之上、射线向下穿过海平面时,把水面当成一层会反光的半透明平面。
        if (!under && k < -1e-6) {
          const tSea = (SEA_LEVEL - eyeY) / k
          if (tSea > 0.2 && tSea < tHit && tSea < VIEW.RENDER_DIST + 4) {
            const wx = eyeX + dx * tSea
            const wz = eyeZ + dz * tSea
            // 两道不同频率的波纹叠起来,不让水面像一块死玻璃
            const wave = Math.sin(wx * VIEW.WATER_WAVE_FREQ + time * VIEW.WATER_WAVE_SPEED)
              * Math.sin(wz * VIEW.WATER_WAVE_FREQ * 0.77 - time * VIEW.WATER_WAVE_SPEED * 0.8)
            const grazing = clamp(1 - -k * 1.4, 0, 1)
            const reflect = clamp(grazing * VIEW.WATER_REFLECT + wave * 0.06, 0, 0.78)
            const wm = mix(waterCol, horizonCol, reflect)
            const fogSea = clamp((tSea - fogStart) * fogK, 0, 1)
            const wr = wm[0] + (fogR - wm[0]) * fogSea
            const wg = wm[1] + (fogG - wm[1]) * fogSea
            const wb = wm[2] + (fogB - wm[2]) * fogSea
            const depth = tHit - tSea
            let alpha = VIEW.WATER_ALPHA_BASE + VIEW.WATER_ALPHA_DEPTH * Math.min(1, depth / 14) + wave * 0.04
            alpha = clamp(alpha, VIEW.WATER_ALPHA_MIN, VIEW.WATER_ALPHA_MAX)
            // 太阳在水面上的高光:太阳方向在水平面上的投影和视线越接近,越亮一点
            const glint = Math.max(0, 1 - Math.abs(wave)) * colors.day * 0.06
            r += (wr - r) * alpha + glint * 255
            g += (wg - g) * alpha + glint * 230
            b += (wb - b) * alpha + glint * 170
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
    if (scene.particles.length) {
      const f = this.focal * (this.cssW / this.wi)
      const hz = this.cssH / 2 + f * Math.tan(cam.pitch)
      const fwdX2 = fwdX
      const fwdZ2 = fwdZ
      const rightX2 = rightX
      const rightZ2 = rightZ
      const project = (wx: number, wy: number, wz: number): [number, number, number] | null => {
        const relX = wx - cam.x
        const relY = wy - cam.y
        const relZ = wz - cam.z
        const depth = relX * fwdX2 + relZ * fwdZ2
        if (depth < 0.25) return null
        const lateral = relX * rightX2 + relZ * rightZ2
        return [this.cssW / 2 + (f * lateral) / depth, hz - (f * relY) / depth, depth]
      }
      drawParticles(ctx, scene.particles, project, f)
    }
    // ---- 目标方块的描边
    if (scene.target) this.drawTarget(ctx, scene.target, cam, focal, scene.mining)
  }

  /** 目标方块:只画准星真正命中的那个面,挖到一半变暖色 */
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
    ctx.lineWidth = VIEW.OUTLINE_GLOW_WIDTH
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)'
    ctx.stroke(path)
    ctx.lineWidth = VIEW.OUTLINE_WIDTH
    ctx.strokeStyle = color
    ctx.stroke(path)
    ctx.restore()
  }
}
