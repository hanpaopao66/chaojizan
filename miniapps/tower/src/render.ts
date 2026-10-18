// Canvas 2D 渲染:静态地图层(缓存到离屏 canvas)+ 每帧的塔/虫/塔位/大西瓜/弹道/粒子/飘字。
// 只读引擎状态,不修改它;亮暗和减少动态由 main.ts 传进来。
import { TILE, WORLD_H, WORLD_W, enemyDef, towerDef, towerStats } from './data'
import { drawSlot, drawTower, paletteFor, type Pal } from './art'
import { drawEnemy, drawWatermelon, type MelonMood } from './art-life'
import { enemyPos, slotPos } from './targeting'
import type { GameEvent, GameState, LevelDef, Theme, Vec } from './types'

interface Ring {
  x: number
  y: number
  r0: number
  r1: number
  life: number
  max: number
  color: string
  width: number
}

interface Beam {
  points: Vec[]
  life: number
  max: number
  color: string
  width: number
}

interface FloatText {
  x: number
  y: number
  text: string
  life: number
  max: number
  color: string
  size: number
}

interface Spark {
  x: number
  y: number
  vx: number
  vy: number
  life: number
  max: number
  size: number
  color: string
}

export interface DrawOpts {
  now: number
  dt: number
  reduced: boolean
  selectedSlot: number
  selectedTower: number
  highlightSlot: number
  hoverSlot: number
}

/** 每帧最多留这么多粒子和飘字(打群架时不掉帧) */
const MAX_SPARKS = 90
const MAX_TEXTS = 26
const MAX_RINGS = 24
const MAX_BEAMS = 18

export class Renderer {
  private readonly ctx: CanvasRenderingContext2D
  private dpr = 1
  private cssW = 0
  private cssH = 0
  private scale = 1
  private layer: HTMLCanvasElement | null = null
  private layerKey = ''
  private theme: Theme = 'garden'
  private dark = false
  private level: LevelDef | null = null
  private pal: Pal = paletteFor('garden', false)
  private rings: Ring[] = []
  private beams: Beam[] = []
  private texts: FloatText[] = []
  private sparks: Spark[] = []
  private shake = 0
  private hurtAt = -1e9
  private lastNow = 0

  constructor(private readonly canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('浏览器不支持 Canvas 2D')
    this.ctx = ctx
  }

  /** 窗口大小变了:重算 canvas 的 CSS 尺寸(保持 9:14)和像素密度 */
  resize(wrapW: number, wrapH: number, dpr: number): void {
    const scale = Math.max(0.2, Math.min(wrapW / WORLD_W, wrapH / WORLD_H))
    this.cssW = Math.fround(WORLD_W * scale)
    this.cssH = Math.fround(WORLD_H * scale)
    this.scale = scale
    this.dpr = Math.min(3, Math.max(1, dpr))
    this.canvas.style.width = `${this.cssW}px`
    this.canvas.style.height = `${this.cssH}px`
    this.canvas.width = Math.round(this.cssW * this.dpr)
    this.canvas.height = Math.round(this.cssH * this.dpr)
  }

  /** 屏幕(CSS 像素,相对 canvas) → 世界坐标 */
  toWorld(px: number, py: number): Vec {
    return { x: px / this.scale, y: py / this.scale }
  }

  /** 世界坐标 → CSS 像素的比例 */
  scaleOf(): number {
    return this.scale
  }

  /** 切关卡 / 切主题时调用:重建静态层并清空粒子 */
  setScene(level: LevelDef, theme: Theme, dark: boolean): void {
    const changed = this.level?.id !== level.id || this.theme !== theme || this.dark !== dark
    this.level = level
    this.theme = theme
    this.dark = dark
    this.pal = paletteFor(theme, dark)
    if (changed) {
      this.layer = null
      this.layerKey = ''
    }
    this.clearFx()
  }

  clearFx(): void {
    this.rings = []
    this.beams = []
    this.texts = []
    this.sparks = []
    this.shake = 0
    this.hurtAt = -1e9
  }

  /** 一组引擎事件 → 粒子和飘字 */
  fx(events: readonly GameEvent[], state: GameState): void {
    const level = this.level
    if (!level) return
    for (const e of events) {
      switch (e.e) {
        case 'shot':
          this.beams.push({ points: [e.from, e.to], life: 0.12, max: 0.12, color: beamColor(e.kind), width: 2 })
          break
        case 'chain':
          this.beams.push({ points: e.points, life: 0.22, max: 0.22, color: '#FFE07A', width: 2.4 })
          break
        case 'boom':
          this.rings.push({ x: e.pos.x, y: e.pos.y, r0: 4, r1: e.radius, life: 0.35, max: 0.35, color: '#FFB26A', width: 3 })
          this.burst(e.pos, 8, '#FFB26A')
          break
        case 'hit':
          this.texts.push({ x: e.pos.x, y: e.pos.y - 14, text: `-${fmt(e.amount)}`, life: 0.6, max: 0.6,
            color: e.armor ? '#D8E0E8' : '#FFE9A8', size: 12 })
          break
        case 'kill':
          this.rings.push({ x: e.pos.x, y: e.pos.y, r0: 2, r1: 16, life: 0.26, max: 0.26, color: '#FFF0B8', width: 2 })
          this.burst(e.pos, 5, '#FFE9A8')
          break
        case 'leak':
          this.shake = Math.min(8, this.shake + 4)
          this.hurtAt = this.lastNow
          this.texts.push({ x: level.world.target.x, y: level.world.target.y - 40, text: `-${e.amount}`, life: 0.9, max: 0.9,
            color: '#FF8A6A', size: 18 })
          break
        case 'gold':
          this.texts.push({ x: e.pos.x, y: e.pos.y - 24, text: `+${e.amount}`, life: 0.9, max: 0.9, color: '#F2D06A', size: 13 })
          break
        case 'freeze':
          this.rings.push({ x: e.pos.x, y: e.pos.y, r0: 2, r1: 20, life: 0.3, max: 0.3, color: '#BFE9FF', width: 2 })
          break
        case 'poison':
          this.burst(e.pos, 2, '#9ED46A')
          break
        case 'burn':
          this.burst(e.pos, 2, '#FFB24A')
          break
        case 'split':
          this.burst(e.pos, 4, '#BC8062')
          break
        case 'cloud':
          this.rings.push({ x: e.pos.x, y: e.pos.y, r0: 4, r1: e.radius, life: 0.6, max: 0.6, color: '#9ED46A', width: 2.4 })
          break
        case 'build': {
          const level2 = this.level
          if (level2) {
            const p = slotPos(level2, e.slot)
            this.rings.push({ x: p.x, y: p.y, r0: 3, r1: 24, life: 0.32, max: 0.32, color: '#F2D06A', width: 2.4 })
            this.burst(p, 4, '#C9A24A')
          }
          break
        }
        case 'upgrade': {
          const level2 = this.level
          const tower = state.towers.find((t) => t.id === e.id)
          if (level2 && tower) {
            const p = slotPos(level2, tower.slot)
            this.rings.push({ x: p.x, y: p.y, r0: 6, r1: 30, life: 0.4, max: 0.4, color: '#FFE07A', width: 3 })
          }
          break
        }
        case 'sell':
          break
        default:
          break
      }
    }
    this.trim()
  }

  private burst(pos: Vec, count: number, color: string): void {
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2 + 0.7
      const sp = 26 + (i % 3) * 18
      this.sparks.push({ x: pos.x, y: pos.y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - 20,
        life: 0.3 + (i % 4) * 0.08, max: 0.56, size: 2 + (i % 2), color })
    }
  }

  private trim(): void {
    if (this.sparks.length > MAX_SPARKS) this.sparks.splice(0, this.sparks.length - MAX_SPARKS)
    if (this.texts.length > MAX_TEXTS) this.texts.splice(0, this.texts.length - MAX_TEXTS)
    if (this.rings.length > MAX_RINGS) this.rings.splice(0, this.rings.length - MAX_RINGS)
    if (this.beams.length > MAX_BEAMS) this.beams.splice(0, this.beams.length - MAX_BEAMS)
  }

  /** 画一帧。什么都不返回;state 只读 */
  draw(state: GameState, o: DrawOpts): void {
    const level = this.level
    if (!level) return
    const ctx = this.ctx
    this.lastNow = o.now
    const dt = Math.min(0.05, Math.max(0, o.dt))
    this.stepFx(dt, o.reduced)
    const s = this.scale * this.dpr
    ctx.setTransform(s, 0, 0, s, 0, 0)
    ctx.clearRect(0, 0, WORLD_W, WORLD_H)
    const shakeX = o.reduced || this.shake <= 0.05 ? 0 : (Math.sin(o.now / 22) * this.shake) / 2
    const shakeY = o.reduced || this.shake <= 0.05 ? 0 : (Math.cos(o.now / 27) * this.shake) / 2
    if (this.shake > 0) this.shake = Math.max(0, this.shake - dt * 26)
    ctx.save()
    ctx.translate(shakeX, shakeY)
    this.ensureLayer(level)
    if (this.layer) ctx.drawImage(this.layer, 0, 0, WORLD_W, WORLD_H)
    this.drawSites(state, o)
    this.drawMoveRange(state, o)
    const towerPos = state.towers.map((t) => ({ t, p: slotPos(level, t.slot) }))
    const enemyPositions = state.enemies.map((e) => ({ e, p: enemyPos(level, e) }))
    // 飞行虫和地面单位一起按 y 排序,靠下的后画
    const all: Array<{ y: number; draw: () => void }> = []
    for (const { t, p } of towerPos) {
      all.push({ y: p.y, draw: () => this.drawTowerAt(t, p, o.now) })
    }
    for (const { e, p } of enemyPositions) {
      all.push({ y: p.y + (e.kind === 'moth' || e.kind === 'wasp' ? 1000 : 0), draw: () => this.drawEnemyAt(state, e, p, o) })
    }
    all.sort((a, b) => a.y - b.y)
    for (const item of all) item.draw()
    this.drawWatermelonAt(state, o)
    this.drawShots(state)
    this.drawFx(o)
    ctx.restore()
  }

  // ---------------------------------------------------------------- 静态层

  private ensureLayer(level: LevelDef): void {
    const key = `${level.id}:${this.theme}:${this.dark ? 1 : 0}`
    if (this.layer && this.layerKey === key) return
    this.layerKey = key
    const layer = this.layer || document.createElement('canvas')
    const res = 2
    layer.width = WORLD_W * res
    layer.height = WORLD_H * res
    const g = layer.getContext('2d')
    if (!g) return
    g.setTransform(res, 0, 0, res, 0, 0)
    const p = this.pal
    // 草地底色 + 深浅色块
    g.fillStyle = p.bg
    g.fillRect(0, 0, WORLD_W, WORLD_H)
    g.fillStyle = p.grass
    g.fillRect(0, 0, WORLD_W, WORLD_H)
    for (let r = 0; r < 14; r++) {
      for (let c = 0; c < 9; c++) {
        const h = hash(c, r)
        if (h % 3 === 0) {
          g.fillStyle = h % 2 === 0 ? p.grassAlt : p.grassDark
          g.globalAlpha = 0.55
          g.beginPath()
          g.ellipse((c + 0.5) * TILE, (r + 0.5) * TILE, TILE * 0.62, TILE * 0.5, (h % 7) / 7, 0, Math.PI * 2)
          g.fill()
        }
      }
    }
    g.globalAlpha = 1
    // 土路:先画深色边,再画路面,最后撒碎石
    g.lineCap = 'round'
    g.lineJoin = 'round'
    for (const poly of level.world.polys) {
      g.strokeStyle = p.pathEdge
      g.lineWidth = TILE * 0.82
      g.beginPath()
      poly.forEach((pt, i) => (i === 0 ? g.moveTo(pt.x, pt.y) : g.lineTo(pt.x, pt.y)))
      g.stroke()
      g.strokeStyle = p.path
      g.lineWidth = TILE * 0.66
      g.beginPath()
      poly.forEach((pt, i) => (i === 0 ? g.moveTo(pt.x, pt.y) : g.lineTo(pt.x, pt.y)))
      g.stroke()
    }
    // 路面碎石与车辙
    const tiles = new Set<number>()
    for (const path of level.paths) {
      for (let i = 0; i < path.length; i++) {
        const a = path[i]
        const b = path[i + 1]
        const dc = b ? Math.sign(b.c - a.c) : 0
        const dr = b ? Math.sign(b.r - a.r) : 0
        let c = a.c
        let r = a.r
        tiles.add(r * 9 + c)
        while (b && (c !== b.c || r !== b.r)) {
          c += dc
          r += dr
          tiles.add(r * 9 + c)
        }
      }
    }
    for (const key2 of tiles) {
      const c = key2 % 9
      const r = Math.floor(key2 / 9)
      const n = 2 + (hash(c + 7, r + 3) % 3)
      for (let i = 0; i < n; i++) {
        const h = hash(c * 31 + i, r * 17 + i * 5)
        const x = (c + 0.5) * TILE + ((h % 100) / 100 - 0.5) * TILE * 0.5
        const y = (r + 0.5) * TILE + (((h >> 8) % 100) / 100 - 0.5) * TILE * 0.5
        g.fillStyle = p.pebble
        g.globalAlpha = 0.5 + ((h >> 16) % 40) / 100
        g.beginPath()
        g.ellipse(x, y, 1.6 + (h % 3), 1.1 + (h % 2), h % 3, 0, Math.PI * 2)
        g.fill()
      }
    }
    g.globalAlpha = 1
    // 装饰:草叶、小花、石头(不挡路)
    for (let r = 1; r < 13; r++) {
      for (let c = 0; c < 9; c++) {
        if (tiles.has(r * 9 + c)) continue
        const h = hash(c * 13 + 5, r * 29 + 11)
        if (h % 5 !== 0) continue
        const x = (c + 0.2 + ((h >> 4) % 60) / 100) * TILE
        const y = (r + 0.2 + ((h >> 10) % 60) / 100) * TILE
        if (h % 3 === 0) {
          // 草叶
          g.strokeStyle = p.grassDark
          g.lineWidth = 1.4
          for (let i = 0; i < 3; i++) {
            g.beginPath()
            g.moveTo(x + i * 2, y + 5)
            g.lineTo(x + i * 2 - 2 + (i % 2) * 4, y - 3 - (i % 2) * 3)
            g.stroke()
          }
        } else if (h % 3 === 1) {
          // 小花
          g.fillStyle = this.theme === 'nest' ? '#B8C8E8' : (h % 2 === 0 ? '#F0D8A0' : '#E8A8A0')
          for (let i = 0; i < 4; i++) {
            const a = (i / 4) * Math.PI * 2
            g.beginPath()
            g.arc(x + Math.cos(a) * 2.4, y + Math.sin(a) * 2.4, 1.8, 0, Math.PI * 2)
            g.fill()
          }
          g.fillStyle = '#C8A03C'
          g.beginPath()
          g.arc(x, y, 1.4, 0, Math.PI * 2)
          g.fill()
        } else {
          // 小石头
          g.fillStyle = p.pebble
          g.beginPath()
          g.ellipse(x, y, 3.2, 2.4, 0.4, 0, Math.PI * 2)
          g.fill()
          g.strokeStyle = p.postInk
          g.globalAlpha = 0.4
          g.lineWidth = 1
          g.stroke()
          g.globalAlpha = 1
        }
      }
    }
    // 入口标记:小土洞
    for (const start of level.world.starts) {
      g.fillStyle = 'rgba(40,32,24,0.35)'
      g.beginPath()
      g.ellipse(start.x, start.y, TILE * 0.34, TILE * 0.24, 0, 0, Math.PI * 2)
      g.fill()
    }
    // 四周压暗一点,像纸的边
    const vg = g.createLinearGradient(0, 0, 0, WORLD_H)
    vg.addColorStop(0, 'rgba(20,24,16,0.18)')
    vg.addColorStop(0.12, 'rgba(20,24,16,0)')
    vg.addColorStop(0.85, 'rgba(20,24,16,0)')
    vg.addColorStop(1, 'rgba(20,24,16,0.22)')
    g.fillStyle = vg
    g.fillRect(0, 0, WORLD_W, WORLD_H)
    this.layer = layer
  }

  // ---------------------------------------------------------------- 场地

  private drawSites(state: GameState, o: DrawOpts): void {
    const level = this.level
    if (!level) return
    for (let i = 0; i < level.slots.length; i++) {
      const tower = state.towers.find((t) => t.slot === i)
      const p = slotPos(level, i)
      drawSlot(this.ctx, this.pal, p.x, p.y, {
        empty: !tower,
        hover: o.hoverSlot === i,
        selected: o.selectedSlot === i || (tower !== undefined && o.selectedTower === tower.id),
        highlight: o.highlightSlot === i,
        now: o.now,
      })
    }
  }

  private drawTowerAt(tower: GameState['towers'][number], p: Vec, now: number): void {
    this.ctx.save()
    this.ctx.translate(p.x, p.y)
    this.ctx.scale(1.14, 1.14)
    drawTower(this.ctx, this.pal, tower, towerDef(tower.kind), now)
    this.ctx.restore()
  }

  private drawEnemyAt(state: GameState, e: GameState['enemies'][number], p: Vec, o: DrawOpts): void {
    const def = enemyDef(e.kind)
    drawEnemy(this.ctx, this.pal, e, def, p, {
      frozen: e.freezeUntil > state.time,
      poisoned: e.poisonUntil > state.time,
      burning: e.burnUntil > state.time,
      flash: e.flash > 0,
      now: o.reduced ? 0 : o.now,
      boss: def.boss === true,
    })
  }

  private drawMoveRange(state: GameState, o: DrawOpts): void {
    if (o.selectedTower <= 0) return
    const level = this.level
    if (!level) return
    const tower = state.towers.find((t) => t.id === o.selectedTower)
    if (!tower) return
    const stats = towerStats(tower.kind, tower.level)
    if (!stats.range) return
    const p = slotPos(level, tower.slot)
    const ctx = this.ctx
    ctx.save()
    ctx.fillStyle = 'rgba(240,220,140,0.10)'
    ctx.beginPath()
    ctx.arc(p.x, p.y, stats.range * TILE, 0, Math.PI * 2)
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,236,170,0.85)'
    ctx.lineWidth = 2
    ctx.setLineDash([8, 7])
    ctx.beginPath()
    ctx.arc(p.x, p.y, stats.range * TILE, 0, Math.PI * 2)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.restore()
  }

  private drawWatermelonAt(state: GameState, o: DrawOpts): void {
    const level = this.level
    if (!level) return
    const hpRatio = state.maxHp > 0 ? state.hp / state.maxHp : 0
    let mood: MelonMood = 'idle'
    if (state.over === 'win') mood = 'win'
    else if (state.over === 'lose') mood = 'lose'
    else if (hpRatio <= 0.34) mood = 'low'
    else if (o.now - this.hurtAt < 380) mood = 'hurt'
    drawWatermelon(this.ctx, this.pal, level.world.target, TILE * 1.25, mood, o.reduced ? 0 : o.now)
  }

  private drawShots(state: GameState): void {
    const ctx = this.ctx
    for (const shot of state.shots) {
      const t = shot.max > 0 ? 1 - shot.life / shot.max : 1
      const x = shot.x + (shot.tx - shot.x) * t
      const y = shot.y + (shot.ty - shot.y) * t
      if (shot.kind === 'bow') {
        const a = Math.atan2(shot.ty - shot.y, shot.tx - shot.x)
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(a)
        ctx.fillStyle = '#E8DCC8'
        ctx.fillRect(-7, -1.2, 14, 2.4)
        ctx.fillStyle = '#8A6E4B'
        ctx.beginPath()
        ctx.moveTo(8, 0)
        ctx.lineTo(3, -3)
        ctx.lineTo(3, 3)
        ctx.closePath()
        ctx.fill()
        ctx.restore()
      } else if (shot.kind === 'pepper') {
        ctx.fillStyle = '#E06A3A'
        ctx.beginPath()
        ctx.arc(x, y, 4.4, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = '#FFD08A'
        ctx.beginPath()
        ctx.arc(x - 1, y - 1, 1.6, 0, Math.PI * 2)
        ctx.fill()
      } else {
        ctx.fillStyle = '#A8CC5E'
        ctx.beginPath()
        ctx.arc(x, y, 3.4, 0, Math.PI * 2)
        ctx.fill()
      }
    }
  }

  // ---------------------------------------------------------------- 粒子

  private stepFx(dt: number, reduced: boolean): void {
    if (reduced) {
      this.rings = []
      this.beams = []
      this.sparks = []
      this.texts = this.texts.filter((t) => t.life > 0.3)
      for (const t of this.texts) t.life -= dt
      return
    }
    for (const r of this.rings) r.life -= dt
    this.rings = this.rings.filter((r) => r.life > 0)
    for (const b of this.beams) b.life -= dt
    this.beams = this.beams.filter((b) => b.life > 0)
    for (const t of this.texts) {
      t.life -= dt
      t.y -= dt * 22
    }
    this.texts = this.texts.filter((t) => t.life > 0)
    for (const s of this.sparks) {
      s.life -= dt
      s.x += s.vx * dt
      s.y += s.vy * dt
      s.vy += 90 * dt
    }
    this.sparks = this.sparks.filter((s) => s.life > 0)
  }

  private drawFx(o: DrawOpts): void {
    const ctx = this.ctx
    for (const b of this.beams) {
      const a = Math.max(0, b.life / b.max)
      if (b.points.length < 2) continue
      ctx.save()
      ctx.globalAlpha = a
      ctx.strokeStyle = b.color
      ctx.lineWidth = b.width
      ctx.lineCap = 'round'
      ctx.beginPath()
      b.points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)))
      ctx.stroke()
      ctx.restore()
    }
    for (const r of this.rings) {
      const t = 1 - Math.max(0, r.life / r.max)
      ctx.save()
      ctx.globalAlpha = (1 - t) * 0.9
      ctx.strokeStyle = r.color
      ctx.lineWidth = r.width
      ctx.beginPath()
      ctx.arc(r.x, r.y, r.r0 + (r.r1 - r.r0) * t, 0, Math.PI * 2)
      ctx.stroke()
      ctx.restore()
    }
    for (const s of this.sparks) {
      ctx.save()
      ctx.globalAlpha = Math.max(0, s.life / s.max)
      ctx.fillStyle = s.color
      ctx.beginPath()
      ctx.arc(s.x, s.y, s.size, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }
    if (!o.reduced) {
      ctx.textAlign = 'center'
      for (const t of this.texts) {
        ctx.save()
        ctx.globalAlpha = Math.min(1, Math.max(0, t.life / t.max) * 1.6)
        ctx.fillStyle = t.color
        ctx.strokeStyle = 'rgba(24,24,18,0.45)'
        ctx.lineWidth = 3
        ctx.font = `700 ${t.size}px system-ui, -apple-system, "PingFang SC", sans-serif`
        ctx.strokeText(t.text, t.x, t.y)
        ctx.fillText(t.text, t.x, t.y)
        ctx.restore()
      }
      ctx.textAlign = 'start'
      // 夜色里的萤火虫
      if (this.theme === 'nest') {
        for (let i = 0; i < 6; i++) {
          const x = (hash(i, 3) % 300) + 30 + Math.sin(o.now / 1800 + i) * 14
          const y = (hash(i, 7) % 420) + 60 + Math.cos(o.now / 2100 + i * 2) * 12
          ctx.fillStyle = `rgba(210,240,170,${0.25 + 0.2 * Math.sin(o.now / 700 + i)})`
          ctx.beginPath()
          ctx.arc(x, y, 1.8, 0, Math.PI * 2)
          ctx.fill()
        }
      }
      // 黄昏的光斑
      if (this.theme === 'orchard') {
        ctx.fillStyle = 'rgba(255,210,140,0.05)'
        ctx.beginPath()
        ctx.arc(WORLD_W * 0.2, WORLD_H * 0.15, 240, 0, Math.PI * 2)
        ctx.fill()
      }
    }
  }
}

// ---------------------------------------------------------------- 小工具

/** 确定性哈希(同一个格子每帧画出来一样,不乱抖) */
function hash(a: number, b: number): number {
  let h = (a * 374761393 + b * 668265263) | 0
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  return (h ^ (h >>> 16)) >>> 0
}

function fmt(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}

function beamColor(kind: string): string {
  switch (kind) {
    case 'frost': return '#BFE9FF'
    case 'pepper': return '#FFB26A'
    case 'vine': return '#FFE07A'
    case 'mushroom': return '#C8A0D8'
    case 'bow': return '#E8DCC8'
    default: return '#C8E08A'
  }
}

/** 世界坐标 → 相对 canvas 左上角的 CSS 像素(无障碍按钮定位用) */
export function worldToCss(renderer: Renderer, p: Vec): Vec {
  const k = renderer.scaleOf()
  return { x: p.x * k, y: p.y * k }
}

/** canvas 上的客户端坐标 → 世界坐标 */
export function clientToWorld(renderer: Renderer, canvas: HTMLCanvasElement, clientX: number, clientY: number): Vec {
  const rect = canvas.getBoundingClientRect()
  return renderer.toWorld(clientX - rect.left, clientY - rect.top)
}
