// 战场的画法:canvas 2D。背景(草地、三条土路、树、塔座)按尺寸和主题预先画在一张离屏画布上,
// 每帧只贴一次;单位、塔、弹道、粒子按插值画在上面。暗色主题把背景压成傍晚的颜色,单位不压。
//
// 画面上的坐标:战场 9×14 格放在 area 里(等比、居中),一格 s 个 CSS 像素;画布铺满整个对局界面,
// 上下的界面浮在画布上,战场外面接着铺草地。
import { art, draw, drawFx, frame } from './assets'
import { Ev } from './battle'
import {
  BASE_Y, CardDef, FIELD_H, FIELD_W, LANE_X, MID_Y, Side, TOWER_Y, Theme, ZONE, card,
} from './data'
import { Battle, DT, Tower, Unit, statsOf } from './field'
import { Fx } from './fx'

export interface Area { x: number; y: number; w: number; h: number }

interface Vis {
  /** 走过的路(算蹦跳的节奏) */
  walk: number
  lx: number
  ly: number
  hitAt: number
  swingAt: number
  sx: number
  sy: number
  /** 上次冒灰的时间 */
  puffAt: number
}

interface Ghost { card: string; side: Side; x: number; y: number; air: boolean; at: number }

export interface Preview {
  card: CardDef
  x: number
  y: number
  ok: boolean
  /** 法术的范围 */
  r: number
}

const TEAM = ['#3E9BFF', '#FF5B4D']
const TEAM_DARK = ['#1C5FAF', '#A8261B']
const easeBack = (t: number) => {
  const c = 1.7
  return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2)
}

/** 确定性的小哈希(背景里树放哪儿):同一关每次打开都长一样 */
function h01(a: number, b: number, c = 0): number {
  let x = (a * 374761393 + b * 668265263 + c * 1274126177) | 0
  x = Math.imul(x ^ (x >>> 13), 1274126177)
  return ((x ^ (x >>> 16)) >>> 0) / 4294967296
}

export class Renderer {
  readonly g: CanvasRenderingContext2D
  cssW = 1
  cssH = 1
  dpr = 1
  s = 40
  ox = 0
  oy = 0
  theme: Theme = 'meadow'
  closed: number[] = []
  dark = false
  private bg: HTMLCanvasElement | null = null
  private vis = new Map<number, Vis>()
  private ghosts: Ghost[] = []
  fx = new Fx()
  private shakeT = 0
  private shakeK = 0
  /** 画面时钟(秒) */
  now = 0
  preview: Preview | null = null
  /** 拖牌时显示可以出兵的半场 */
  showZone = false
  /** 击倒返还能量的光点要飞去的位置(CSS 像素,画布坐标) */
  orbTarget: { x: number; y: number } | null = null
  private orbs: Array<{ x0: number; y0: number; t: number }> = []
  /** 塔挨打时抖一下:塔 id → 时间 */
  private towerHit = new Map<number, number>()

  constructor(readonly canvas: HTMLCanvasElement) {
    this.g = canvas.getContext('2d') as CanvasRenderingContext2D
  }

  /** 画布大小(CSS 像素)和战场放在哪儿 */
  layout(cssW: number, cssH: number, area: Area): void {
    this.dpr = Math.min(2.5, window.devicePixelRatio || 1)
    this.cssW = cssW
    this.cssH = cssH
    this.canvas.width = Math.round(cssW * this.dpr)
    this.canvas.height = Math.round(cssH * this.dpr)
    this.s = Math.min(area.w / FIELD_W, area.h / FIELD_H)
    this.ox = area.x + (area.w - FIELD_W * this.s) / 2
    this.oy = area.y + (area.h - FIELD_H * this.s) / 2
    this.bg = null
  }

  setScene(theme: Theme, closed: number[], dark: boolean): void {
    if (theme === this.theme && dark === this.dark && closed.join() === this.closed.join() && this.bg) return
    this.theme = theme
    this.closed = closed.slice()
    this.dark = dark
    this.bg = null
  }

  reset(): void {
    this.vis.clear()
    this.ghosts = []
    this.fx = new Fx()
    this.orbs = []
    this.towerHit.clear()
    this.preview = null
    this.shakeT = 0
  }

  /** 画布上的点 → 战场的格 */
  toWorld(cx: number, cy: number): { x: number; y: number } {
    return { x: (cx - this.ox) / this.s, y: (cy - this.oy) / this.s }
  }

  toScreen(x: number, y: number): { x: number; y: number } {
    return { x: this.ox + x * this.s, y: this.oy + y * this.s }
  }

  shake(k: number, t = 0.3): void {
    this.shakeK = Math.max(this.shakeK * (this.shakeT > 0 ? 1 : 0), k)
    this.shakeT = Math.max(this.shakeT, t)
  }

  // ---------------------------------------------------------------- 背景

  private buildBg(): void {
    const W = Math.round(this.cssW * this.dpr)
    const H = Math.round(this.cssH * this.dpr)
    const c = document.createElement('canvas')
    c.width = W
    c.height = H
    const g = c.getContext('2d') as CanvasRenderingContext2D
    g.scale(this.dpr, this.dpr)
    const s = this.s
    const { ox, oy } = this
    const world = art.world
    const th = this.theme
    // 1. 草地:按战场的格对齐铺
    const i0 = Math.floor(-ox / s) - 1
    const j0 = Math.floor(-oy / s) - 1
    const i1 = Math.ceil((this.cssW - ox) / s) + 1
    const j1 = Math.ceil((this.cssH - oy) / s) + 1
    for (let j = j0; j < j1; j++) {
      for (let i = i0; i < i1; i++) {
        const key = `grass-${th}-${h01(i, j) < 0.62 ? 0 : 1}`
        const f = frame(world, key)
        if (f && world) g.drawImage(world.img, f[0], f[1], f[2], f[3], ox + i * s - 0.5, oy + j * s - 0.5, s + 1, s + 1)
      }
    }
    // 2. 土路:先描一圈深色的边,再用土的纹理填
    const lanes = [0, 1, 2].filter((l) => this.closed.indexOf(l) < 0)
    const path = (gg: CanvasRenderingContext2D) => {
      gg.beginPath()
      for (const l of lanes) {
        const x = ox + LANE_X[l] * s
        gg.moveTo(x, oy + TOWER_Y[1] * s)
        gg.lineTo(x, oy + TOWER_Y[0] * s)
        for (const side of [0, 1] as Side[]) {
          gg.moveTo(x, oy + TOWER_Y[side] * s)
          gg.lineTo(ox + LANE_X[1] * s, oy + BASE_Y[side] * s)
        }
      }
    }
    const plazas = (gg: CanvasRenderingContext2D, extra: number) => {
      for (const side of [0, 1] as Side[]) {
        gg.moveTo(ox + LANE_X[1] * s + (1.25 + extra) * s, oy + BASE_Y[side] * s)
        gg.arc(ox + LANE_X[1] * s, oy + BASE_Y[side] * s, (1.25 + extra) * s, 0, Math.PI * 2)
        for (const l of lanes) {
          gg.moveTo(ox + LANE_X[l] * s + (0.78 + extra) * s, oy + TOWER_Y[side] * s)
          gg.arc(ox + LANE_X[l] * s, oy + TOWER_Y[side] * s, (0.78 + extra) * s, 0, Math.PI * 2)
        }
      }
    }
    const laneW = 1.12 * s
    const edge = { meadow: '#9a6a3e', swamp: '#5e4630', snow: '#8fa3b8', jungle: '#6b4a2e', highland: '#a07a48' }[th]
    const mask = document.createElement('canvas')
    mask.width = W
    mask.height = H
    const m = mask.getContext('2d') as CanvasRenderingContext2D
    m.scale(this.dpr, this.dpr)
    m.lineCap = 'round'
    m.lineJoin = 'round'
    // 边
    m.strokeStyle = edge
    m.fillStyle = edge
    m.lineWidth = laneW + 0.16 * s
    path(m)
    m.stroke()
    m.beginPath()
    plazas(m, 0.08)
    m.fill()
    g.drawImage(mask, 0, 0, W, H, 0, 0, this.cssW, this.cssH)
    // 土:画一遍路的形状当遮罩,再把土的纹理铺进去
    m.setTransform(1, 0, 0, 1, 0, 0)
    m.clearRect(0, 0, W, H)
    m.scale(this.dpr, this.dpr)
    m.strokeStyle = '#000'
    m.fillStyle = '#000'
    m.lineWidth = laneW
    path(m)
    m.stroke()
    m.beginPath()
    plazas(m, 0)
    m.fill()
    m.globalCompositeOperation = 'source-in'
    const df = frame(world, `dirt-${th}`)
    if (df && world) {
      for (let j = j0; j < j1; j++) {
        for (let i = i0; i < i1; i++) m.drawImage(world.img, df[0], df[1], df[2], df[3], ox + i * s - 0.5, oy + j * s - 0.5, s + 1, s + 1)
      }
    }
    m.globalCompositeOperation = 'source-over'
    g.drawImage(mask, 0, 0, W, H, 0, 0, this.cssW, this.cssH)
    // 路中间一道浅浅的车辙
    g.save()
    g.globalAlpha = 0.1
    g.strokeStyle = '#fff'
    g.lineWidth = laneW * 0.35
    g.lineCap = 'round'
    g.lineJoin = 'round'
    path(g)
    g.stroke()
    g.restore()
    // 3. 中线:一排小灌木(路口空着)
    const bushes = th === 'snow' ? ['bush-snow-1'] : th === 'highland' ? ['bush-3', 'bush-1'] : th === 'swamp' || th === 'jungle' ? ['bush-5', 'bush-1'] : ['bush-1', 'bush-3', 'bush-5']
    for (let x = 0.3; x < FIELD_W; x += 0.55) {
      if (lanes.some((l) => Math.abs(x - LANE_X[l]) < 0.8)) continue
      draw(g, world, bushes[Math.floor(h01(Math.round(x * 10), 7) * bushes.length)], ox + x * s, oy + (MID_Y + 0.12) * s, s * 0.42)
    }
    // 4. 封掉的路:一堆灌木和木桶把路口堵上
    for (const l of this.closed) {
      for (const side of [0, 1] as Side[]) {
        const y = side === 0 ? 9.5 : 4.5
        draw(g, world, th === 'snow' ? 'bush-snow-0' : 'bush-4', ox + (LANE_X[l] - 0.35) * s, oy + y * s, s * 0.8)
        draw(g, world, 'barrel', ox + (LANE_X[l] + 0.35) * s, oy + (y + 0.1) * s, s * 0.42)
        draw(g, world, th === 'snow' ? 'bush-snow-1' : 'bush-2', ox + LANE_X[l] * s, oy + (y + 0.35) * s, s * 0.6)
      }
    }
    // 5. 装饰:两边一排树,路和路之间的空地上偶尔一棵小树或一个池塘
    const tree = th === 'snow' ? 'snow' : th === 'highland' ? 'orange' : th === 'swamp' || th === 'jungle' ? 'dark' : 'green'
    const items: Array<[string, number, number, number]> = []
    for (let y = -0.4; y < FIELD_H + 1.5; y += 1.05) {
      for (const [x, k] of [[-0.15, 0], [FIELD_W + 0.15, 1]] as const) {
        const jx = x + (h01(Math.round(y * 10), k) - 0.5) * 0.35
        const big = h01(Math.round(y * 10), k, 3) < 0.55
        items.push([`tree-${tree === 'green' && h01(Math.round(y * 10), k, 9) < 0.25 ? 'dark' : tree}-${big ? 0 : 1}`, jx, y + 0.5, big ? 1.1 : 0.85])
      }
    }
    // 宽屏:战场两边露出来的草地上也随手种些树和灌木(按格子哈希,位置固定)
    for (let j = j0; j < j1; j++) {
      for (let i = i0; i < i1; i++) {
        if (i >= -1 && i <= FIELD_W) continue
        const r = h01(i, j, 5)
        const jx = i + 0.2 + h01(i, j, 6) * 0.6
        const jy = j + 0.3 + h01(i, j, 7) * 0.5
        if (r < 0.2) items.push([`tree-${h01(i, j, 8) < 0.3 && tree === 'green' ? 'dark' : tree}-${r < 0.1 ? 0 : 1}`, jx, jy + 0.5, r < 0.1 ? 1.1 : 0.85])
        else if (r < 0.3) items.push([bushes[Math.floor(h01(i, j, 9) * bushes.length)], jx, jy, 0.6])
      }
    }
    // 空地上的点缀(不压路、不压塔)
    const gaps = [(LANE_X[0] + LANE_X[1]) / 2, (LANE_X[1] + LANE_X[2]) / 2]
    const spots: Array<[number, number]> = [[gaps[0], 4.9], [gaps[1], 9.1], [gaps[0], 10.2], [gaps[1], 3.8]]
    spots.forEach(([x, y], k) => {
      const r = h01(k, 11)
      if ((th === 'swamp' || th === 'snow') && k < 2) items.push([th === 'snow' ? 'pond-ice' : 'pond', x, y + 0.55, 1.25])
      else if (r < 0.5) items.push([`tree-${tree}-1`, x, y + 0.4, 0.62])
      else items.push([bushes[k % bushes.length], x, y + 0.2, 0.6])
    })
    if (th === 'meadow' || th === 'highland') {
      items.push(['crate', 0.95, 13.55, 0.45], ['barrel', 8.1, 13.5, 0.4], ['barrel', 0.9, 0.55, 0.4], ['crate', 8.05, 0.6, 0.45])
    }
    items.sort((a, b) => a[2] - b[2])
    for (const [key, x, y, w] of items) {
      if (key.startsWith('pond')) {
        draw(g, world, key, ox + x * s, oy + (y - 0.55) * s, s * w)
        continue
      }
      g.globalAlpha = 0.18
      g.fillStyle = '#000'
      g.beginPath()
      g.ellipse(ox + x * s, oy + y * s, w * s * 0.38, w * s * 0.14, 0, 0, Math.PI * 2)
      g.fill()
      g.globalAlpha = 1
      draw(g, world, key, ox + x * s, oy + y * s, s * w * (key.startsWith('tree') ? 0.62 : 1))
    }
    // 6. 暗色:压成傍晚;四周一圈暗角
    if (this.dark) {
      g.globalCompositeOperation = 'multiply'
      g.fillStyle = '#7d8ab0'
      g.fillRect(0, 0, this.cssW, this.cssH)
      g.globalCompositeOperation = 'source-over'
    }
    const vg = g.createRadialGradient(this.cssW / 2, this.cssH / 2, Math.min(this.cssW, this.cssH) * 0.45,
      this.cssW / 2, this.cssH / 2, Math.max(this.cssW, this.cssH) * 0.75)
    vg.addColorStop(0, 'rgba(0,0,0,0)')
    vg.addColorStop(1, this.dark ? 'rgba(0,0,10,0.35)' : 'rgba(40,30,10,0.16)')
    g.fillStyle = vg
    g.fillRect(0, 0, this.cssW, this.cssH)
    this.bg = c
  }

  // ---------------------------------------------------------------- 事件 → 动画

  onEvents(evs: Ev[], b: Battle): void {
    for (const e of evs) {
      switch (e.e) {
        case 'play': {
          const c = card(e.card)
          if (c.kind !== 'spell') {
            this.fx.ring(e.x, e.y, 0.7, e.side === 0 ? 'blue' : 'red', 0.35, 0.8)
            this.fx.dust(e.x, e.y + 0.1, 5)
          }
          break
        }
        case 'swing': {
          const u = b.units.find((x) => x.id === e.id)
          const t = b.units.find((x) => x.id === e.to) || b.towers.find((x) => x.id === e.to)
          if (u && t) {
            const v = this.visOf(u)
            v.swingAt = this.now
            const d = Math.hypot(t.x - u.x, t.y - u.y) || 1
            v.sx = (t.x - u.x) / d
            v.sy = (t.y - u.y) / d
          }
          break
        }
        case 'hit': {
          if (e.tower) {
            this.towerHit.set(e.id, this.now)
            if (e.dmg >= 60) this.fx.dust(e.x, e.y + 0.2, 2, 'smoke')
          } else {
            const u = b.units.find((x) => x.id === e.id)
            if (u) this.visOf(u).hitAt = this.now
            if (e.dmg >= 20) this.fx.sparks(e.x, e.y, u && u.air ? 0.9 : 0.35, 'gold', e.dmg >= 150 ? 5 : 2)
          }
          break
        }
        case 'die':
          this.ghosts.push({ card: e.card, side: e.side, x: e.x, y: e.y, air: e.air, at: this.now })
          this.fx.poof(e.x, e.y, Math.max(0.35, statsOf(e.card).radius * 1.3), e.air)
          break
        case 'tower': {
          const big = e.lane === -1
          this.fx.boom(e.x, e.y - 0.3, big ? 1.6 : 1.1)
          this.shake(big ? 9 : 6, big ? 0.6 : 0.45)
          break
        }
        case 'spell':
          if (e.card === 'fire') {
            this.fx.boom(e.x, e.y, e.r * 0.8)
            this.fx.ring(e.x, e.y, e.r, 'orange', 0.4)
            this.shake(4, 0.25)
          } else if (e.card === 'freeze') {
            this.fx.ring(e.x, e.y, e.r, 'cyan', 0.5)
            this.fx.frost(e.x, e.y, e.r)
          } else if (e.card === 'heal') {
            this.fx.ring(e.x, e.y, e.r, 'green', 0.5)
            this.fx.hearts(e.x, e.y, e.r, 14)
          } else if (e.card === 'rage') {
            this.fx.ring(e.x, e.y, e.r, 'orange', 0.5)
            this.fx.rage(e.x, e.y, e.r)
          }
          break
        case 'pulse':
          this.fx.ring(e.x, e.y, e.r, e.stun ? 'gold' : 'cyan', 0.55)
          this.fx.dust(e.x, e.y + 0.3, 8, e.stun ? 'dust' : 'ice')
          this.shake(4, 0.3)
          break
        case 'refund':
          if (e.side === 0) {
            this.fx.glint(e.x, e.y)
            const p = this.toScreen(e.x, e.y)
            if (this.orbs.length < 12) this.orbs.push({ x0: p.x, y0: p.y - this.s * 0.4, t: 0 })
          }
          break
        case 'charge':
        case 'leap': {
          const u = b.units.find((x) => x.id === e.id)
          if (u) this.fx.dust(u.x, u.y + 0.1, 4)
          break
        }
        case 'spawn': {
          const u = b.units.find((x) => x.id === e.id)
          if (u) this.fx.dust(u.x, u.y, 2)
          break
        }
      }
    }
  }

  private visOf(u: Unit): Vis {
    let v = this.vis.get(u.id)
    if (!v) {
      v = { walk: (u.id % 7) * 0.4, lx: u.x, ly: u.y, hitAt: -9, swingAt: -9, sx: 0, sy: 0, puffAt: 0 }
      this.vis.set(u.id, v)
    }
    return v
  }

  // ---------------------------------------------------------------- 每一帧

  frame(b: Battle | null, alpha: number, dt: number): void {
    this.now += dt
    this.fx.update(dt)
    const g = this.g
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0)
    if (!this.bg && art.world) this.buildBg()
    let dx = 0
    let dy = 0
    if (this.shakeT > 0) {
      this.shakeT -= dt
      const k = this.shakeK * Math.max(0, Math.min(1, this.shakeT / 0.3))
      dx = (Math.random() - 0.5) * 2 * k
      dy = (Math.random() - 0.5) * 2 * k
    }
    if (this.bg) g.drawImage(this.bg, 0, 0, this.bg.width, this.bg.height, dx, dy, this.cssW, this.cssH)
    else {
      g.fillStyle = this.dark ? '#26301f' : '#8cc43a'
      g.fillRect(0, 0, this.cssW, this.cssH)
    }
    if (!b) return
    g.translate(dx, dy)
    const s = this.s
    const { ox, oy } = this
    const X = (x: number) => ox + x * s
    const Y = (y: number) => oy + y * s

    if (this.showZone) this.drawZone(b)
    this.fx.drawDecals(g, s, ox, oy)

    // 插值后的位置
    const pos = new Map<number, [number, number]>()
    for (const u of b.units) pos.set(u.id, [u.px + (u.x - u.px) * alpha, u.py + (u.y - u.py) * alpha])

    // 地上一层:影子、队伍色的圈、奶牛的光环
    for (const u of b.units) {
      const [x, y] = pos.get(u.id)!
      const st = statsOf(u.card)
      const d = st.radius * 2 * s
      g.fillStyle = 'rgba(0,0,0,0.22)'
      g.beginPath()
      g.ellipse(X(x), Y(y) + d * 0.08, d * (u.air ? 0.32 : 0.42), d * (u.air ? 0.12 : 0.16), 0, 0, Math.PI * 2)
      g.fill()
      if (!u.building) {
        g.strokeStyle = TEAM[u.side]
        g.lineWidth = Math.max(1.5, s * 0.055)
        g.globalAlpha = 0.9
        g.beginPath()
        g.ellipse(X(x), Y(y) + d * 0.08, d * 0.48, d * 0.19, 0, 0, Math.PI * 2)
        g.stroke()
        g.globalAlpha = 1
      }
      if (st.heal) {
        g.globalAlpha = 0.14 + 0.06 * Math.sin(this.now * 4)
        g.fillStyle = '#7fe08a'
        g.beginPath()
        g.ellipse(X(x), Y(y), 2.2 * s, 2.2 * s * 0.8, 0, 0, Math.PI * 2)
        g.fill()
        g.globalAlpha = 1
      }
    }

    // 按 y 排序画:塔、建筑、地面单位、倒下的
    type Item = { y: number; draw: () => void }
    const items: Item[] = []
    for (const t of b.towers) items.push({ y: t.y + 0.4, draw: () => this.drawTower(t) })
    for (const u of b.units) {
      if (u.air) continue
      const p = pos.get(u.id)!
      items.push({ y: p[1], draw: () => this.drawUnit(b, u, p[0], p[1], alpha) })
    }
    items.sort((a, c) => a.y - c.y)
    for (const it of items) it.draw()
    this.drawGhosts(false)

    // 弹道
    for (const sh of b.shots) {
      const x = sh.px + (sh.x - sh.px) * alpha
      const y = sh.py + (sh.y - sh.py) * alpha
      const lift = sh.kind === 'arrow' ? 0.55 : 0.4
      if (sh.kind === 'arrow') {
        const a = Math.atan2(sh.ty - sh.y, sh.tx - sh.x)
        g.save()
        g.translate(X(x), Y(y - lift))
        g.rotate(a)
        g.strokeStyle = '#6b4a2b'
        g.lineWidth = Math.max(1.5, s * 0.045)
        g.beginPath()
        g.moveTo(-s * 0.26, 0)
        g.lineTo(s * 0.12, 0)
        g.stroke()
        g.fillStyle = '#d9dde3'
        g.beginPath()
        g.moveTo(s * 0.2, 0)
        g.lineTo(s * 0.08, -s * 0.06)
        g.lineTo(s * 0.08, s * 0.06)
        g.fill()
        g.restore()
      } else if (sh.kind === 'bolt') {
        const a = Math.atan2(sh.ty - sh.y, sh.tx - sh.x)
        g.save()
        g.translate(X(x), Y(y - lift))
        g.rotate(a)
        const grd = g.createLinearGradient(-s * 0.6, 0, s * 0.15, 0)
        grd.addColorStop(0, 'rgba(255,240,180,0)')
        grd.addColorStop(1, 'rgba(255,250,220,0.95)')
        g.fillStyle = grd
        g.fillRect(-s * 0.6, -s * 0.04, s * 0.75, s * 0.08)
        g.restore()
      } else {
        const col = sh.side === 0 ? '#bfe3ff' : '#ffd0c4'
        g.fillStyle = 'rgba(0,0,0,0.18)'
        g.beginPath()
        g.ellipse(X(x), Y(y) + s * 0.05, s * 0.08, s * 0.035, 0, 0, Math.PI * 2)
        g.fill()
        g.fillStyle = col
        g.strokeStyle = sh.side === 0 ? TEAM_DARK[0] : TEAM_DARK[1]
        g.lineWidth = Math.max(1, s * 0.03)
        g.beginPath()
        g.arc(X(x), Y(y - lift), s * 0.085, 0, Math.PI * 2)
        g.fill()
        g.stroke()
        g.fillStyle = 'rgba(255,255,255,0.8)'
        g.beginPath()
        g.arc(X(x) - s * 0.03, Y(y - lift) - s * 0.03, s * 0.03, 0, Math.PI * 2)
        g.fill()
      }
    }

    // 天上的
    for (const u of b.units) {
      if (!u.air) continue
      const p = pos.get(u.id)!
      this.drawUnit(b, u, p[0], p[1], alpha)
    }
    this.drawGhosts(true)
    this.fx.draw(g, s, ox, oy)

    // 血条放最上面,看得清
    for (const t of b.towers) if (t.alive) this.towerBar(t)
    for (const u of b.units) {
      const p = pos.get(u.id)!
      this.unitBar(u, p[0], p[1])
    }
    if (this.preview) this.drawPreview(this.preview)
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0)
    this.drawOrbs(dt)
    // 清理已经不在场上的单位的动画记录
    if (this.vis.size > b.units.length + 20) {
      const alive = new Set(b.units.map((u) => u.id))
      for (const id of Array.from(this.vis.keys())) if (!alive.has(id)) this.vis.delete(id)
    }
    this.ghosts = this.ghosts.filter((gh) => this.now - gh.at < 0.35)
    for (const [id, t] of this.towerHit) if (this.now - t > 0.2) this.towerHit.delete(id)
  }

  private drawZone(b: Battle): void {
    const g = this.g
    const s = this.s
    const [lo, hi] = ZONE[0]
    const p = this.preview
    if (p && p.card.kind === 'spell') return
    g.fillStyle = 'rgba(255,60,40,0.10)'
    g.fillRect(this.ox, this.oy, FIELD_W * s, lo * s)
    g.fillStyle = 'rgba(120,255,140,0.10)'
    g.fillRect(this.ox, this.oy + lo * s, FIELD_W * s, (hi - lo) * s)
    g.save()
    g.setLineDash([s * 0.2, s * 0.14])
    g.strokeStyle = 'rgba(255,255,255,0.75)'
    g.lineWidth = 2
    g.beginPath()
    g.moveTo(this.ox, this.oy + lo * s)
    g.lineTo(this.ox + FIELD_W * s, this.oy + lo * s)
    g.stroke()
    g.restore()
    // 能走的几路亮一点
    for (let l = 0; l < 3; l++) {
      if (b.cfg.closed.indexOf(l) >= 0) continue
      g.fillStyle = 'rgba(255,255,255,0.10)'
      g.fillRect(this.ox + (LANE_X[l] - 0.6) * s, this.oy + lo * s, 1.2 * s, (hi - lo) * s)
    }
  }

  private drawTower(t: Tower): void {
    const g = this.g
    const s = this.s
    const x = this.ox + t.x * s
    const y = this.oy + t.y * s
    const base = t.lane === -1
    const w = (base ? 2.15 : 1.12) * s
    if (!t.alive) {
      draw(g, art.world, `ruin-${base ? 'base' : 'tower'}-${t.side}`, x, y + s * 0.35, w * 0.95)
      if (Math.random() < 0.04) this.fx.add({ key: 'smoke', color: 'smoke', x: t.x + (Math.random() - 0.5) * 0.6, y: t.y, z: 0.4, vz: 0.6, size: 0.4, grow: 0.4, life: 1.6, alpha: 0.35, fade: 'inout' })
      return
    }
    const hitAt = this.towerHit.get(t.id)
    let jx = 0
    if (hitAt !== undefined && this.now - hitAt < 0.12) jx = (Math.random() - 0.5) * s * 0.05
    // 影子
    g.fillStyle = 'rgba(0,0,0,0.22)'
    g.beginPath()
    g.ellipse(x, y + s * 0.3, w * 0.5, w * 0.16, 0, 0, Math.PI * 2)
    g.fill()
    const h = draw(g, art.world, `${base ? 'base' : 'tower'}-${t.side}`, x + jx, y + s * 0.38, w)
    if (hitAt !== undefined && this.now - hitAt < 0.08) {
      g.globalAlpha = 0.35
      g.globalCompositeOperation = 'lighter'
      draw(g, art.world, `${base ? 'base' : 'tower'}-${t.side}`, x + jx, y + s * 0.38, w)
      g.globalCompositeOperation = 'source-over'
      g.globalAlpha = 1
    }
    // 屋顶上一面会飘的旗
    const top = y + s * 0.38 - h * 0.88
    const flags = base ? [x - w * 0.36, x + w * 0.36] : [x]
    for (const fx0 of flags) {
      const py = base ? top + h * 0.3 : top + h * 0.02
      g.strokeStyle = '#5b3b22'
      g.lineWidth = Math.max(1.5, s * 0.04)
      g.beginPath()
      g.moveTo(fx0, py)
      g.lineTo(fx0, py - s * 0.42)
      g.stroke()
      const wave = Math.sin(this.now * 5 + t.id) * s * 0.04
      g.fillStyle = TEAM[t.side]
      g.strokeStyle = TEAM_DARK[t.side]
      g.lineWidth = 1
      g.beginPath()
      g.moveTo(fx0, py - s * 0.42)
      g.quadraticCurveTo(fx0 + s * 0.16, py - s * 0.42 + wave, fx0 + s * 0.32, py - s * 0.34 + wave)
      g.quadraticCurveTo(fx0 + s * 0.16, py - s * 0.26 - wave, fx0, py - s * 0.24)
      g.closePath()
      g.fill()
      g.stroke()
    }
    if (t.frozenT > 0) this.iceBlock(x, y + s * 0.3, w * 0.9, h * 0.8)
  }

  private iceBlock(x: number, yBottom: number, w: number, h: number): void {
    const g = this.g
    g.fillStyle = 'rgba(190,235,255,0.38)'
    g.strokeStyle = 'rgba(255,255,255,0.8)'
    g.lineWidth = 1.5
    const r = Math.min(w, h) * 0.18
    const x0 = x - w / 2
    const y0 = yBottom - h
    g.beginPath()
    g.moveTo(x0 + r, y0)
    g.arcTo(x0 + w, y0, x0 + w, y0 + h, r)
    g.arcTo(x0 + w, y0 + h, x0, y0 + h, r)
    g.arcTo(x0, y0 + h, x0, y0, r)
    g.arcTo(x0, y0, x0 + w, y0, r)
    g.closePath()
    g.fill()
    g.stroke()
    g.fillStyle = 'rgba(255,255,255,0.5)'
    g.fillRect(x0 + w * 0.18, y0 + h * 0.12, w * 0.12, h * 0.5)
  }

  private drawUnit(b: Battle, u: Unit, x: number, y: number, alpha: number): void {
    const g = this.g
    const s = this.s
    const st = statsOf(u.card)
    const c = card(u.card)
    const v = this.visOf(u)
    const moved = Math.hypot(x - v.lx, y - v.ly)
    v.lx = x
    v.ly = y
    const frozen = u.frozenT > 0
    if (!frozen && u.stunT <= 0) v.walk += moved * 5.2
    const d = st.radius * 2 * s * (c.boss ? 1.18 : 1.3)
    const age = b.t - u.born + alpha * DT
    const pop = age < 0.3 ? easeBack(Math.max(0.01, age / 0.3)) : 1
    let hop = 0
    let sq = 1
    if (u.building) {
      hop = 0
    } else if (u.air) {
      hop = s * 0.55 + Math.sin(this.now * 3 + u.id) * s * 0.06
    } else if (moved > 0.0005 && !frozen) {
      const ph = Math.abs(Math.sin(v.walk))
      hop = ph * d * 0.14
      sq = 1 - (1 - ph) * 0.08
    }
    if (u.leaping) hop += d * 0.45
    if (u.charged && st.charge && moved > 0.001 && this.now - v.puffAt > 0.12) {
      v.puffAt = this.now
      this.fx.dust(x, y + 0.05, 1)
    }
    // 出手:往目标方向扑一下
    let lx = 0
    let ly = 0
    const sw = this.now - v.swingAt
    if (sw < 0.18) {
      const k = Math.sin((sw / 0.18) * Math.PI) * s * 0.18
      lx = v.sx * k
      ly = v.sy * k
    }
    const w = d * pop
    // 动物头像的锚点在正中:往上提一截,看起来是「站」在自己的影子上;建筑的锚点本来就在底边
    const cx = this.ox + x * s + lx
    const cy = this.oy + y * s + ly - hop - (u.building ? 0 : w * 0.4)
    const tilt = u.building || u.air ? 0 : Math.sin(v.walk) * 0.07
    g.save()
    g.translate(cx, cy)
    if (tilt) g.rotate(tilt)
    g.scale(1 / sq, sq)
    const key = c.art
    if (c.boss) {
      g.globalAlpha = 0.5 + 0.2 * Math.sin(this.now * 4)
      drawFx(g, 'glow', 'gold', 0, 0, w * 1.5)
      g.globalAlpha = 1
    }
    if (u.rageT > 0) {
      g.globalAlpha = 0.55
      drawFx(g, 'glow', 'fire', 0, 0, w * 1.35)
      g.globalAlpha = 1
    }
    const bw = u.building ? w * 1.15 : w
    draw(g, art.units, key, 0, 0, bw)
    // 受击闪白
    const hit = this.now - v.hitAt
    if (hit < 0.1 && art.unitsWhite) {
      g.globalAlpha = 0.75 * (1 - hit / 0.1)
      draw(g, art.units, key, 0, 0, bw, art.unitsWhite)
      g.globalAlpha = 1
    }
    if (u.poisonT > 0) {
      g.globalAlpha = 0.28
      g.globalCompositeOperation = 'source-atop'
      g.fillStyle = '#58d65a'
      g.fillRect(-w, -w, w * 2, w * 2)
      g.globalCompositeOperation = 'source-over'
      g.globalAlpha = 1
      if (Math.random() < 0.08) this.fx.add({ key: 'dot', color: 'green', x: x + (Math.random() - 0.5) * 0.3, y, z: 0.5, vz: 0.9, size: 0.12, life: 0.6 })
    }
    g.restore()
    if (frozen) this.iceBlock(this.ox + x * s, this.oy + y * s + d * 0.1, w * 1.15, w * 1.1 + hop)
    if (u.stunT > 0) {
      for (let i = 0; i < 3; i++) {
        const a = this.now * 5 + (i * Math.PI * 2) / 3
        drawFx(g, 'star', 'gold', cx + Math.cos(a) * w * 0.35, cy - w * 0.55 + Math.sin(a) * w * 0.1, s * 0.22)
      }
    }
    if (u.slowT > 0 && !frozen) {
      g.globalAlpha = 0.6
      drawFx(g, 'twirl', 'ice', cx, cy + w * 0.2, w * 0.7)
      g.globalAlpha = 1
    }
    if (u.healT > 0 && Math.random() < 0.15) this.fx.hearts(x, y, 0.3, 1)
    if (u.building && st.life && u.life > 0) {
      // 建筑剩下的时间:底下一圈细弧
      const k = u.life / st.life
      g.strokeStyle = 'rgba(255,255,255,0.85)'
      g.lineWidth = Math.max(1.5, s * 0.05)
      g.beginPath()
      g.arc(this.ox + x * s, this.oy + y * s + s * 0.3, s * 0.18, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * k)
      g.stroke()
    }
  }

  private drawGhosts(air: boolean): void {
    const g = this.g
    const s = this.s
    for (const gh of this.ghosts) {
      if (gh.air !== air) continue
      const t = (this.now - gh.at) / 0.3
      if (t >= 1) continue
      const st = statsOf(gh.card)
      const d = st.radius * 2 * s * 1.3 * (1 + t * 0.35)
      g.globalAlpha = 1 - t
      const hop = gh.air ? s * 0.55 : 0
      const lift = card(gh.card).kind === 'building' ? d * 0.1 : d * 0.4
      draw(g, art.units, card(gh.card).art, this.ox + gh.x * s, this.oy + gh.y * s - hop - lift - t * s * 0.3, d,
        art.unitsWhite || undefined)
      g.globalAlpha = 1
    }
  }

  private bar(x: number, y: number, w: number, h: number, k: number, color: string): void {
    const g = this.g
    const r = h / 2
    g.fillStyle = 'rgba(20,16,12,0.55)'
    roundRect(g, x - w / 2 - 1, y - 1, w + 2, h + 2, r + 1)
    g.fill()
    g.fillStyle = color
    if (k > 0) {
      roundRect(g, x - w / 2, y, Math.max(h, w * k), h, r)
      g.fill()
      g.fillStyle = 'rgba(255,255,255,0.35)'
      g.fillRect(x - w / 2 + r, y + 1, Math.max(0, w * k - h), Math.max(1, h * 0.3))
    }
  }

  private towerBar(t: Tower): void {
    const s = this.s
    const base = t.lane === -1
    const w = (base ? 1.5 : 0.95) * s
    const y = this.oy + t.y * s - (base ? 1.75 : 1.62) * s
    this.bar(this.ox + t.x * s, y, w, Math.max(4, s * (base ? 0.14 : 0.11)), t.hp / t.max, TEAM[t.side])
    if (t.hp < t.max) {
      const g = this.g
      g.font = `600 ${Math.max(9, s * 0.24)}px system-ui, sans-serif`
      g.textAlign = 'center'
      g.lineWidth = 3
      g.strokeStyle = 'rgba(0,0,0,0.55)'
      g.fillStyle = '#fff'
      const txt = String(Math.ceil(t.hp))
      g.strokeText(txt, this.ox + t.x * s, y - s * 0.06)
      g.fillText(txt, this.ox + t.x * s, y - s * 0.06)
    }
  }

  private unitBar(u: Unit, x: number, y: number): void {
    if (u.hp >= u.max && !card(u.card).boss) return
    const s = this.s
    const st = statsOf(u.card)
    const d = st.radius * 2 * s * 1.3
    const lift = u.air ? s * 0.55 : 0
    const yy = this.oy + y * s - d * (u.building ? 1.25 : 1.12) - lift - 4
    this.bar(this.ox + x * s, yy, Math.max(s * 0.5, d * 0.8), Math.max(3, s * 0.085), u.hp / u.max, TEAM[u.side])
  }

  private drawPreview(p: Preview): void {
    const g = this.g
    const s = this.s
    const x = this.ox + p.x * s
    const y = this.oy + p.y * s
    if (p.card.kind === 'spell') {
      g.fillStyle = p.ok ? 'rgba(255,255,255,0.16)' : 'rgba(255,80,60,0.18)'
      g.strokeStyle = p.ok ? 'rgba(255,255,255,0.9)' : 'rgba(255,90,70,0.9)'
      g.lineWidth = 2
      g.setLineDash([6, 5])
      g.beginPath()
      g.ellipse(x, y, p.r * s, p.r * s * 0.85, 0, 0, Math.PI * 2)
      g.fill()
      g.stroke()
      g.setLineDash([])
      g.globalAlpha = 0.85
      draw(g, art.units, p.card.art, x, y, s * 0.9)
      g.globalAlpha = 1
      return
    }
    const st = p.card.unit!
    const d = st.radius * 2 * s * 1.3
    g.strokeStyle = p.ok ? TEAM[0] : '#ff5a4a'
    g.lineWidth = 2.5
    g.beginPath()
    g.ellipse(x, y + d * 0.08, d * 0.5, d * 0.2, 0, 0, Math.PI * 2)
    g.stroke()
    if (st.range >= 1.5) {
      g.save()
      g.setLineDash([4, 5])
      g.strokeStyle = 'rgba(255,255,255,0.45)'
      g.lineWidth = 1.5
      g.beginPath()
      g.arc(x, y, (st.range + st.radius) * s, Math.PI * 1.05, Math.PI * 1.95)
      g.stroke()
      g.restore()
    }
    g.globalAlpha = p.ok ? 0.8 : 0.45
    const count = st.count || 1
    if (count > 1) {
      for (const [ddx, ddy] of [[-0.22, 0], [0.22, 0], [-0.22, 0.34], [0.22, 0.34]].slice(0, count)) {
        draw(g, art.units, p.card.art, x + ddx * s, y + ddy * s, d)
      }
    } else draw(g, art.units, p.card.art, x, y - (p.card.kind === 'building' ? 0 : 0), p.card.kind === 'building' ? d * 1.15 : d)
    g.globalAlpha = 1
  }

  private drawOrbs(dt: number): void {
    const tgt = this.orbTarget
    if (!tgt) {
      this.orbs = []
      return
    }
    const g = this.g
    const keep: typeof this.orbs = []
    for (const o of this.orbs) {
      o.t += dt / 0.55
      if (o.t >= 1) continue
      const t = o.t * o.t * (3 - 2 * o.t)
      const mx = (o.x0 + tgt.x) / 2 + (o.x0 < tgt.x ? -40 : 40)
      const my = Math.min(o.y0, tgt.y) - 30
      const x = (1 - t) * (1 - t) * o.x0 + 2 * (1 - t) * t * mx + t * t * tgt.x
      const y = (1 - t) * (1 - t) * o.y0 + 2 * (1 - t) * t * my + t * t * tgt.y
      g.globalAlpha = 0.9
      drawFx(g, 'glow', 'teal', x, y, 26)
      drawFx(g, 'dot', 'white', x, y, 9)
      g.globalAlpha = 1
      keep.push(o)
    }
    this.orbs = keep
  }

  /** 有光点刚飞到能量条(界面拿来让能量条跳一下) */
  orbsArriving(): number {
    return this.orbs.filter((o) => o.t > 0.9).length
  }
}

function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  const rr = Math.min(r, w / 2, h / 2)
  g.beginPath()
  g.moveTo(x + rr, y)
  g.arcTo(x + w, y, x + w, y + h, rr)
  g.arcTo(x + w, y + h, x, y + h, rr)
  g.arcTo(x, y + h, x, y, rr)
  g.arcTo(x, y, x + w, y, rr)
  g.closePath()
}
