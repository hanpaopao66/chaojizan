// 粒子:只管好看,不进对局状态、不进存档。坐标按战场的「格」算(跟着画面缩放和震屏走)。
// 随机数用 Math.random —— 粒子怎么飞不影响胜负,也不用复现。
import { FxColor, drawFx, drawFxRaw } from './assets'

export interface Particle {
  key: string
  /** null = 原色(爆炸那几张) */
  color: FxColor | null
  x: number
  y: number
  vx: number
  vy: number
  /** 往上飘的速度(格/秒),画的时候从 y 减掉的高度 */
  z: number
  vz: number
  size: number
  grow: number
  life: number
  age: number
  alpha: number
  fade: 'out' | 'inout'
  drag: number
  gravity: number
  spin: number
  rot: number
}

export interface Decal { key: string; color: FxColor; x: number; y: number; size: number; life: number; age: number; alpha: number }

const R = Math.random
const rr = (a: number, b: number) => a + R() * (b - a)

export class Fx {
  parts: Particle[] = []
  decals: Decal[] = []

  add(p: Partial<Particle> & { key: string; x: number; y: number }): void {
    if (this.parts.length > 420) return
    this.parts.push({
      color: 'white', vx: 0, vy: 0, z: 0, vz: 0, size: 0.4, grow: 0, life: 0.6, age: 0, alpha: 1, fade: 'out',
      drag: 0, gravity: 0, spin: 0, rot: 0, ...p,
    })
  }

  decal(key: string, color: FxColor, x: number, y: number, size: number, life = 8, alpha = 0.5): void {
    if (this.decals.length > 24) this.decals.shift()
    this.decals.push({ key, color, x, y, size, life, age: 0, alpha })
  }

  update(dt: number): void {
    const keep: Particle[] = []
    for (const p of this.parts) {
      p.age += dt
      if (p.age >= p.life) continue
      const k = Math.max(0, 1 - p.drag * dt)
      p.vx *= k
      p.vy *= k
      p.vz -= p.gravity * dt
      p.x += p.vx * dt
      p.y += p.vy * dt
      p.z = Math.max(p.gravity ? 0 : -9, p.z + p.vz * dt)
      p.size = Math.max(0, p.size + p.grow * dt)
      p.rot += p.spin * dt
      keep.push(p)
    }
    this.parts = keep
    this.decals = this.decals.filter((d) => (d.age += dt) < d.life)
  }

  /** 画地上的印子(焦痕)。s 是一格多少像素,(ox, oy) 是战场左上角 */
  drawDecals(g: CanvasRenderingContext2D, s: number, ox: number, oy: number): void {
    for (const d of this.decals) {
      const t = d.age / d.life
      g.globalAlpha = d.alpha * (t < 0.7 ? 1 : 1 - (t - 0.7) / 0.3)
      drawFx(g, d.key, d.color, ox + d.x * s, oy + d.y * s, d.size * s)
    }
    g.globalAlpha = 1
  }

  draw(g: CanvasRenderingContext2D, s: number, ox: number, oy: number): void {
    for (const p of this.parts) {
      const t = p.age / p.life
      const a = p.fade === 'out' ? 1 - t : t < 0.25 ? t / 0.25 : 1 - (t - 0.25) / 0.75
      g.globalAlpha = Math.max(0, Math.min(1, a * p.alpha))
      const x = ox + p.x * s
      const y = oy + (p.y - p.z) * s
      if (p.rot) {
        g.save()
        g.translate(x, y)
        g.rotate(p.rot)
        if (p.color) drawFx(g, p.key, p.color, 0, 0, p.size * s)
        else drawFxRaw(g, p.key, 0, 0, p.size * s)
        g.restore()
      } else if (p.color) drawFx(g, p.key, p.color, x, y, p.size * s)
      else drawFxRaw(g, p.key, x, y, p.size * s)
    }
    g.globalAlpha = 1
  }

  // ---------------------------------------------------------------- 常用的几种

  /** 脚下扬起的一小股土 */
  dust(x: number, y: number, n = 3, color: FxColor = 'dust'): void {
    for (let i = 0; i < n; i++) {
      this.add({ key: `puff${i % 3}`, color, x: x + rr(-0.2, 0.2), y: y + rr(-0.05, 0.1), vx: rr(-0.8, 0.8), vy: rr(-0.3, 0.2),
        vz: rr(0.2, 0.6), size: rr(0.25, 0.4), grow: 0.5, life: rr(0.35, 0.55), alpha: 0.7, drag: 3 })
    }
  }

  /** 被击倒:一团白烟加几颗小星星 */
  poof(x: number, y: number, size: number, air: boolean): void {
    const z = air ? 0.7 : 0.3
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2 + rr(-0.3, 0.3)
      this.add({ key: `puff${i % 3}`, color: 'white', x: x + Math.cos(a) * 0.12, y, z, vx: Math.cos(a) * rr(0.8, 1.5),
        vy: Math.sin(a) * rr(0.4, 0.9), vz: rr(0.2, 0.8), size: size * rr(0.5, 0.75), grow: size * 0.8, life: rr(0.4, 0.6),
        alpha: 0.9, drag: 4 })
    }
    for (let i = 0; i < 3; i++) {
      this.add({ key: 'twinkle', color: 'gold', x, y, z: z + 0.2, vx: rr(-1.4, 1.4), vy: rr(-0.6, 0.3), vz: rr(1, 2),
        size: rr(0.18, 0.28), life: rr(0.45, 0.7), gravity: 3, spin: rr(-6, 6), drag: 1.5 })
    }
  }

  /** 挨打:几点火星 */
  sparks(x: number, y: number, z: number, color: FxColor = 'gold', n = 3): void {
    for (let i = 0; i < n; i++) {
      this.add({ key: 'star', color, x, y, z, vx: rr(-1.6, 1.6), vy: rr(-1, 0.6), vz: rr(0.5, 1.6), size: rr(0.14, 0.24),
        life: rr(0.18, 0.3), drag: 5 })
    }
  }

  /** 圆环扩散(法术、落地、Boss 发作) */
  ring(x: number, y: number, r: number, color: FxColor, life = 0.45, alpha = 0.9): void {
    this.add({ key: 'ring', color, x, y, size: r * 0.4, grow: (r * 2 - r * 0.4) / life, life, alpha })
  }

  /** 爆炸:火团 + 烟 + 碎土 + 焦痕 */
  boom(x: number, y: number, r: number): void {
    for (let i = 0; i < 5; i++) {
      this.add({ key: `boom${i % 3}`, color: null, x: x + rr(-0.3, 0.3) * r, y: y + rr(-0.2, 0.2) * r, z: rr(0, 0.3),
        size: r * rr(0.7, 1.1), grow: r * 1.2, life: rr(0.35, 0.55), rot: rr(0, 6), spin: rr(-2, 2) })
    }
    for (let i = 0; i < 6; i++) {
      this.add({ key: 'smoke', color: 'smoke', x: x + rr(-0.4, 0.4) * r, y: y + rr(-0.3, 0.3) * r, z: 0.2, vz: rr(0.4, 1),
        vx: rr(-0.5, 0.5), size: r * rr(0.6, 0.9), grow: r * 0.8, life: rr(0.8, 1.3), alpha: 0.55, fade: 'inout', drag: 1 })
    }
    for (let i = 0; i < 8; i++) {
      const a = R() * Math.PI * 2
      this.add({ key: 'dirt', color: 'dark', x, y, z: 0.2, vx: Math.cos(a) * rr(1.5, 3) * r, vy: Math.sin(a) * rr(0.8, 1.8) * r,
        vz: rr(1.5, 3), size: rr(0.15, 0.3), life: rr(0.5, 0.8), gravity: 7, drag: 1, spin: rr(-8, 8) })
    }
    this.decal('scorch', 'dark', x, y, r * 1.6, 9, 0.45)
  }

  /** 冰冻:雪花往外散 */
  frost(x: number, y: number, r: number): void {
    for (let i = 0; i < 14; i++) {
      const a = R() * Math.PI * 2
      const d = R() * r
      this.add({ key: i % 2 ? 'star' : 'twinkle', color: 'ice', x: x + Math.cos(a) * d, y: y + Math.sin(a) * d * 0.8, z: rr(0.1, 0.8),
        vz: rr(-0.3, 0.3), size: rr(0.2, 0.36), life: rr(0.6, 1.1), spin: rr(-3, 3), fade: 'inout' })
    }
    this.add({ key: 'glow', color: 'cyan', x, y, size: r * 1.6, grow: r * 0.6, life: 0.5, alpha: 0.5 })
  }

  /** 回血:往上冒的小心和亮点 */
  hearts(x: number, y: number, r: number, n = 10): void {
    for (let i = 0; i < n; i++) {
      const a = R() * Math.PI * 2
      const d = R() * r
      this.add({ key: i % 3 ? 'twinkle' : 'heart', color: i % 3 ? 'heal' : 'green', x: x + Math.cos(a) * d,
        y: y + Math.sin(a) * d * 0.8, z: rr(0, 0.4), vz: rr(0.8, 1.5), size: rr(0.18, 0.3), life: rr(0.6, 1), fade: 'inout' })
    }
  }

  /** 鼓舞:橙色的旋风和火星 */
  rage(x: number, y: number, r: number): void {
    for (let i = 0; i < 8; i++) {
      const a = R() * Math.PI * 2
      const d = R() * r
      this.add({ key: i % 2 ? 'twirl' : 'spark', color: i % 2 ? 'orange' : 'gold', x: x + Math.cos(a) * d,
        y: y + Math.sin(a) * d * 0.8, z: rr(0, 0.4), vz: rr(0.4, 1), size: rr(0.3, 0.5), life: rr(0.5, 0.8), spin: rr(-6, 6) })
    }
  }

  /** 击倒返还能量:从这里冒一个青色的光点(界面再让它飞去能量条) */
  glint(x: number, y: number): void {
    this.add({ key: 'glow', color: 'teal', x, y, z: 0.5, vz: 1.2, size: 0.5, grow: -0.3, life: 0.4 })
  }
}
