// 画战场:整张地图一屏放下,全部用 Canvas 2D 程序化绘制(没有一张图片素材)。
//
// 只有玩家看得见(LOS + 视距)的守卫才画出来;失去视线后留 1 秒「最后已知位置」的虚影。
// 地图是静态的,预渲染成一张离屏画布缓存起来,只有换尺寸/换主题才重画,每帧只画人和特效。

import { TILE, Vec, WORLD_H, WORLD_W, dist, lineOfSight, siteCenter } from './map'
import {
  BOMB_TIME, GuardState, PLAYER_RADIUS, PLAYER_VIEW_RANGE, PlayerState, Round,
} from './match'

import { DEFAULT_PALETTE, Palette, buildMapLayer, mapLayerKey } from './paint'

export { readPalette } from './paint'
export type { Palette } from './paint'

export interface DrawOptions {
  /** 鼠标在世界坐标里的位置(桌面准星);触屏是 null */
  mouse: Vec | null
  /** 触屏时的瞄准角:从玩家身上拉一条虚线,代替看不见的鼠标 */
  aimAngle: number | null
  /** 系统开了「减少动态效果」:不震屏、不画烟 */
  reduced: boolean
  /** 现在的时间(毫秒),做呼吸/闪烁动画用 */
  now: number
}

export class Renderer {
  private readonly ctx: CanvasRenderingContext2D
  private palette: Palette = DEFAULT_PALETTE
  private width = 0
  private height = 0
  private dpr = 1
  private shake = 0
  private lastNow = 0
  /** 静态地图预渲染(2 倍分辨率,缩放时不糊) */
  private layer: HTMLCanvasElement | null = null
  private layerKey = ''
  /** 上次看见每个守卫的位置和时间(渲染层自己的小状态,不进存档) */
  private readonly ghosts = new Map<number, { pos: Vec; at: number }>()
  /** 已经画过「装备掉落」标记的守卫 */
  private readonly dead = new Map<number, Vec>()
  /** 每个角色上一帧的位置:拿来算走路摆动(纯画面,不参与判定) */
  private readonly motion = new Map<string, { x: number; y: number; phase: number }>()

  constructor(private readonly canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('这个浏览器没有 Canvas 2D,玩不了')
    this.ctx = ctx
  }

  resize(): void {
    const w = this.canvas.clientWidth || window.innerWidth
    const h = this.canvas.clientHeight || window.innerHeight
    const dpr = Math.min(2.5, window.devicePixelRatio || 1)
    if (w === this.width && h === this.height && dpr === this.dpr) return
    this.width = w
    this.height = h
    this.dpr = dpr
    this.canvas.width = Math.max(1, Math.round(w * dpr))
    this.canvas.height = Math.max(1, Math.round(h * dpr))
  }

  setPalette(palette: Palette): void {
    this.palette = palette
    this.layerKey = '' // 换主题:下一帧重画底图
  }

  /** 屏幕震一下(开火、爆炸、挨打)。减少动态效果时由 draw 忽略 */
  addShake(amount: number): void {
    this.shake = Math.min(9, this.shake + amount)
  }

  /** 新回合/重开时清掉虚影和掉落标记 */
  reset(): void {
    this.ghosts.clear()
    this.dead.clear()
    this.shake = 0
  }

  /** 视口坐标 → 世界坐标(鼠标瞄准用) */
  worldAt(clientX: number, clientY: number): Vec {
    const rect = this.canvas.getBoundingClientRect()
    const scale = Math.min(rect.width / WORLD_W, rect.height / WORLD_H)
    const ox = (rect.width - WORLD_W * scale) / 2
    const oy = (rect.height - WORLD_H * scale) / 2
    return { x: (clientX - rect.left - ox) / scale, y: (clientY - rect.top - oy) / scale }
  }

  draw(round: Round, opts: DrawOptions): void {
    const key = mapLayerKey(round.map, this.palette)
    if (key !== this.layerKey) {
      this.layer = buildMapLayer(round.map, this.palette)
      this.layerKey = key
    }
    const ctx = this.ctx
    const dt = Math.min(0.1, Math.max(0, (opts.now - this.lastNow) / 1000))
    this.lastNow = opts.now
    this.shake = this.shake <= 0.05 ? 0 : Math.max(0, this.shake * Math.max(0, 1 - dt * 6) - dt * 2)

    const scale = Math.min(this.width / WORLD_W, this.height / WORLD_H)
    const ox = (this.width - WORLD_W * scale) / 2
    const oy = (this.height - WORLD_H * scale) / 2
    const shakeX = opts.reduced || this.shake <= 0.05
      ? 0
      : Math.sin(opts.now * 0.09) * this.shake + (Math.random() - 0.5) * this.shake
    const shakeY = opts.reduced || this.shake <= 0.05
      ? 0
      : Math.cos(opts.now * 0.11) * this.shake + (Math.random() - 0.5) * this.shake

    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0)
    ctx.fillStyle = this.palette.bg
    ctx.fillRect(0, 0, this.width, this.height)

    ctx.save()
    ctx.translate(ox + shakeX, oy + shakeY)
    ctx.scale(scale, scale)
    if (this.layer) ctx.drawImage(this.layer, 0, 0, WORLD_W, WORLD_H)
    this.drawSites(round, opts)
    this.drawBomb(round, opts)
    this.drawGuards(round, opts, dt)
    this.drawPlayer(round, dt, opts.reduced)
    this.drawAimLine(round, opts)
    this.drawDeadMarks(round)
    this.drawFx(round, opts)
    this.drawAim(opts)
    ctx.restore()

    // 四周压暗,把注意力收在地图中间(在屏幕坐标里画,不跟着缩放)
    const g = ctx.createRadialGradient(
      this.width / 2, this.height / 2, Math.min(this.width, this.height) * 0.34,
      this.width / 2, this.height / 2, Math.max(this.width, this.height) * 0.74,
    )
    g.addColorStop(0, 'rgba(0,0,0,0)')
    g.addColorStop(1, this.palette.vignette)
    ctx.fillStyle = g
    ctx.fillRect(0, 0, this.width, this.height)
  }

  // ---------------------------------------------------------------- 静态地图

  // ---------------------------------------------------------------- 炸弹点 / 炸弹

  private drawSites(round: Round, opts: DrawOptions): void {
    for (const site of ['A', 'B'] as const) {
      const c = siteCenter(site === 'A' ? round.map.siteA : round.map.siteB)
      const pulse = 0.5 + 0.5 * Math.sin(opts.now / 600 + (site === 'A' ? 0 : 1.7))
      const ctx = this.ctx
      ctx.strokeStyle = site === 'A' ? this.palette.siteA2 : this.palette.siteB2
      ctx.globalAlpha = 0.32 + pulse * 0.22
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.arc(c.x, c.y, TILE * 1.7 + pulse * 8, 0, Math.PI * 2)
      ctx.stroke()
      if (round.map.theme === 'market') {
        ctx.globalAlpha = 0.14 + pulse * 0.16
        ctx.lineWidth = 1.2
        ctx.beginPath()
        ctx.arc(c.x, c.y, TILE * 2.4 + pulse * 12, 0, Math.PI * 2)
        ctx.stroke()
      }
      ctx.globalAlpha = 1
    }
  }

  private drawBomb(round: Round, opts: DrawOptions): void {
    const bomb = round.bomb
    if (bomb.state === 'planting') {
      this.drawPlantRing(round)
      return
    }
    if (!bomb.pos || (bomb.state !== 'planted' && bomb.state !== 'defused')) return
    const ctx = this.ctx
    const pos = bomb.pos
    const urgent = bomb.state === 'planted' ? 1 - Math.min(1, bomb.timer / BOMB_TIME) : 0
    const blink = 0.5 + 0.5 * Math.sin(opts.now / Math.max(120, 500 - urgent * 380))
    const radius = 13
    if (bomb.state === 'planted') {
      ctx.strokeStyle = this.palette.bomb
      ctx.globalAlpha = 0.18 + blink * 0.22
      ctx.lineWidth = 3
      ctx.beginPath()
      ctx.arc(pos.x, pos.y, radius + 10 + blink * 9, 0, Math.PI * 2)
      ctx.stroke()
      ctx.globalAlpha = 1
    }
    // 炸弹本体:方盒子 + 闪的灯
    ctx.fillStyle = this.palette.shadow
    ctx.beginPath()
    ctx.ellipse(pos.x, pos.y + 7, radius * 0.95, radius * 0.45, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = this.palette.bomb
    ctx.strokeStyle = this.palette.bombInk
    ctx.lineWidth = 2
    this.roundRect(ctx, pos.x - radius, pos.y - radius + 2, radius * 2, radius * 1.7, 4)
    ctx.fill()
    ctx.stroke()
    ctx.fillStyle = bomb.state === 'planted' && blink > 0.45 ? '#FFF3C4' : this.palette.bombInk
    ctx.beginPath()
    ctx.arc(pos.x + 5, pos.y - 2, 3, 0, Math.PI * 2)
    ctx.fill()
    // 拆除进度:炸弹外围一圈弧
    if (bomb.state === 'planted' && bomb.defuse > 0.001) {
      ctx.strokeStyle = this.palette.tracerGuard
      ctx.lineWidth = 3.5
      ctx.beginPath()
      ctx.arc(pos.x, pos.y, radius + 8, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * bomb.defuse)
      ctx.stroke()
    }
    if (bomb.state === 'defused') {
      ctx.strokeStyle = this.palette.tracerPlayer
      ctx.lineWidth = 4
      ctx.beginPath()
      ctx.moveTo(pos.x - 8, pos.y - 8)
      ctx.lineTo(pos.x + 8, pos.y + 8)
      ctx.moveTo(pos.x + 8, pos.y - 8)
      ctx.lineTo(pos.x - 8, pos.y + 8)
      ctx.stroke()
    }
  }

  /** 安放进度:在玩家脚下画一圈慢慢合拢的弧 */
  private drawPlantRing(round: Round): void {
    const p = round.player
    const ctx = this.ctx
    ctx.strokeStyle = this.palette.tracerPlayer
    ctx.lineWidth = 3
    ctx.beginPath()
    ctx.arc(p.pos.x, p.pos.y, PLAYER_RADIUS + 10, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * round.bomb.plant)
    ctx.stroke()
  }

  /**
   * 走路摆动:按这一帧移动的距离推进相位,原地站着就慢慢归零。
   * 只改画面(身体上下/左右晃一点),碰撞和命中都不受影响。
   */
  private walkBob(key: string, pos: Vec, dt: number): number {
    const last = this.motion.get(key)
    const prev = last ? last.phase : 0
    let phase = prev
    let speed = 0
    if (last) {
      const moved = Math.hypot(pos.x - last.x, pos.y - last.y)
      speed = dt > 0 ? moved / dt : 0
      phase += moved / 14
    }
    this.motion.set(key, { x: pos.x, y: pos.y, phase })
    if (speed < 8) return 0
    return Math.sin(phase * Math.PI) * 1.7
  }

  // ---------------------------------------------------------------- 守卫

  private drawGuards(round: Round, opts: DrawOptions, dt: number): void {
    const visibleIds = new Set<number>()
    for (const guard of round.guards) {
      if (!guard.alive) continue
      const visible = dist(round.player.pos, guard.pos) <= PLAYER_VIEW_RANGE
        && lineOfSight(round.map, round.player.pos, guard.pos)
      if (visible) {
        visibleIds.add(guard.id)
        this.ghosts.set(guard.id, { pos: { ...guard.pos }, at: opts.now })
        this.drawGuard(guard, dt, opts.reduced)
      }
    }
    // 刚失去视线的「最后已知位置」:1 秒内淡出
    for (const guard of round.guards) {
      if (!guard.alive || visibleIds.has(guard.id)) continue
      const ghost = this.ghosts.get(guard.id)
      if (!ghost) continue
      const age = opts.now - ghost.at
      if (age > 1000) continue
      const alpha = Math.max(0, 1 - age / 1000)
      const ctx = this.ctx
      ctx.save()
      ctx.globalAlpha = alpha * 0.8
      ctx.strokeStyle = this.palette.ghost
      ctx.setLineDash([4, 4])
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.arc(ghost.pos.x, ghost.pos.y, 14, 0, Math.PI * 2)
      ctx.stroke()
      ctx.setLineDash([])
      ctx.fillStyle = this.palette.ghost
      ctx.font = 'bold 15px system-ui, sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText('?', ghost.pos.x, ghost.pos.y + 1)
      ctx.restore()
    }
  }

  private drawGuard(guard: GuardState, dt: number, reducedMotion: boolean): void {
    const ctx = this.ctx
    const p = this.palette
    const pos = guard.pos
    const bob = dt > 0 && !reducedMotion ? this.walkBob(`guard:${guard.id}`, pos, dt) : 0
    ctx.fillStyle = p.shadow
    ctx.beginPath()
    ctx.ellipse(pos.x, pos.y + 6, 12, 5, 0, 0, Math.PI * 2)
    ctx.fill()
    // 身体:菱形 → 和玩家的圆区分开(不看颜色也分得清敌我)
    ctx.save()
    ctx.translate(pos.x, pos.y + bob * 0.7)
    ctx.rotate(guard.angle + bob * 0.02)
    ctx.fillStyle = guard.hitFlash > 0 ? '#FFFFFF' : p.guard
    ctx.strokeStyle = p.guardInk
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(14, 0)
    ctx.lineTo(0, 10)
    ctx.lineTo(-11, 0)
    ctx.lineTo(0, -10)
    ctx.closePath()
    ctx.fill()
    ctx.stroke()
    // 枪管
    ctx.strokeStyle = p.guardInk
    ctx.lineWidth = 4
    ctx.beginPath()
    ctx.moveTo(4, 0)
    ctx.lineTo(21, 0)
    ctx.stroke()
    ctx.restore()
    // 头顶小三角:一眼看出这是敌人
    ctx.fillStyle = p.guard
    ctx.beginPath()
    ctx.moveTo(pos.x, pos.y - 19 + bob * 0.7)
    ctx.lineTo(pos.x + 6, pos.y - 11 + bob * 0.7)
    ctx.lineTo(pos.x - 6, pos.y - 11 + bob * 0.7)
    ctx.closePath()
    ctx.fill()
    // 受伤后显示一条很短的血条
    if (guard.hp < 100) {
      const w = 26
      const frac = Math.max(0, guard.hp / 100)
      ctx.fillStyle = 'rgba(0,0,0,.55)'
      ctx.fillRect(pos.x - w / 2, pos.y + 17, w, 4)
      ctx.fillStyle = p.guard
      ctx.fillRect(pos.x - w / 2, pos.y + 17, w * frac, 4)
    }
  }

  private drawDeadMarks(round: Round): void {
    const ctx = this.ctx
    const p = this.palette
    for (const guard of round.guards) {
      if (guard.alive) {
        this.dead.delete(guard.id)
        continue
      }
      if (!this.dead.has(guard.id)) this.dead.set(guard.id, { ...guard.pos })
      const pos = this.dead.get(guard.id)!
      ctx.save()
      ctx.globalAlpha = 0.45
      ctx.strokeStyle = p.ghost
      ctx.lineWidth = 2.5
      ctx.beginPath()
      ctx.arc(pos.x, pos.y, 10, 0, Math.PI * 2)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(pos.x - 6, pos.y - 6)
      ctx.lineTo(pos.x + 6, pos.y + 6)
      ctx.moveTo(pos.x + 6, pos.y - 6)
      ctx.lineTo(pos.x - 6, pos.y + 6)
      ctx.stroke()
      ctx.restore()
    }
  }

  // ---------------------------------------------------------------- 玩家与准星

  private drawPlayer(round: Round, dt: number, reducedMotion: boolean): void {
    const ctx = this.ctx
    const p = this.palette
    const player: PlayerState = round.player
    const pos = player.pos
    if (!player.alive) {
      // 玩家阵亡:一个静默的标记,不做血腥表现
      ctx.save()
      ctx.globalAlpha = 0.7
      ctx.strokeStyle = p.player
      ctx.lineWidth = 3
      ctx.beginPath()
      ctx.arc(pos.x, pos.y, 11, 0, Math.PI * 2)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(pos.x - 6, pos.y - 6)
      ctx.lineTo(pos.x + 6, pos.y + 6)
      ctx.moveTo(pos.x + 6, pos.y - 6)
      ctx.lineTo(pos.x - 6, pos.y + 6)
      ctx.stroke()
      ctx.restore()
      return
    }
    const bob = dt > 0 && !reducedMotion ? this.walkBob('player', pos, dt) : 0
    ctx.fillStyle = p.shadow
    ctx.beginPath()
    ctx.ellipse(pos.x, pos.y + 6, 12, 5, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.save()
    ctx.translate(pos.x, pos.y + bob * 0.65)
    ctx.rotate(player.angle + bob * 0.025)
    ctx.fillStyle = player.hitFlash > 0 ? '#FFFFFF' : p.player
    ctx.strokeStyle = p.playerInk
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.arc(0, 0, 11, 0, Math.PI * 2)
    ctx.fill()
    ctx.stroke()
    // 朝向:枪管 + 箭头
    ctx.strokeStyle = p.playerInk
    ctx.lineWidth = 4
    ctx.beginPath()
    ctx.moveTo(4, 0)
    ctx.lineTo(22, 0)
    ctx.stroke()
    ctx.fillStyle = p.playerInk
    ctx.beginPath()
    ctx.moveTo(23, 0)
    ctx.lineTo(16, -4)
    ctx.lineTo(16, 4)
    ctx.closePath()
    ctx.fill()
    ctx.restore()
    // 头顶箭头标记
    ctx.fillStyle = p.player
    ctx.beginPath()
    ctx.moveTo(pos.x, pos.y - 20 + bob * 0.65)
    ctx.lineTo(pos.x + 5, pos.y - 28 + bob * 0.65)
    ctx.lineTo(pos.x - 5, pos.y - 28 + bob * 0.65)
    ctx.closePath()
    ctx.fill()
  }

  /** 触屏:从玩家身上沿瞄准方向画一条虚线,并画一个小十字,手指挡住准星时也知道朝哪 */
  private drawAimLine(round: Round, opts: DrawOptions): void {
    if (opts.aimAngle === null || !round.player.alive) return
    const ctx = this.ctx
    const p = this.palette
    const pos = round.player.pos
    const angle = opts.aimAngle
    const len = 110
    ctx.save()
    ctx.globalAlpha = 0.5
    ctx.strokeStyle = p.tracerPlayer
    ctx.lineWidth = 2
    ctx.setLineDash([6, 6])
    ctx.beginPath()
    ctx.moveTo(pos.x + Math.cos(angle) * 20, pos.y + Math.sin(angle) * 20)
    ctx.lineTo(pos.x + Math.cos(angle) * len, pos.y + Math.sin(angle) * len)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.beginPath()
    ctx.arc(pos.x + Math.cos(angle) * len, pos.y + Math.sin(angle) * len, 5, 0, Math.PI * 2)
    ctx.stroke()
    ctx.restore()
  }

  private drawAim(opts: DrawOptions): void {
    if (!opts.mouse) return
    const ctx = this.ctx
    const p = this.palette
    const { x, y } = opts.mouse
    ctx.save()
    ctx.strokeStyle = p.tracerPlayer
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.arc(x, y, 9, 0, Math.PI * 2)
    ctx.moveTo(x - 15, y)
    ctx.lineTo(x - 5, y)
    ctx.moveTo(x + 5, y)
    ctx.lineTo(x + 15, y)
    ctx.moveTo(x, y - 15)
    ctx.lineTo(x, y - 5)
    ctx.moveTo(x, y + 5)
    ctx.lineTo(x, y + 15)
    ctx.stroke()
    ctx.fillStyle = p.tracerPlayer
    ctx.beginPath()
    ctx.arc(x, y, 1.8, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
  }

  // ---------------------------------------------------------------- 特效

  private drawFx(round: Round, opts: DrawOptions): void {
    const ctx = this.ctx
    const p = this.palette
    // 曳光:一道带辉光的短亮线,两头淡
    for (const tracer of round.tracers) {
      const alpha = Math.max(0, tracer.life / tracer.max)
      const grad = ctx.createLinearGradient(tracer.from.x, tracer.from.y, tracer.to.x, tracer.to.y)
      grad.addColorStop(0, 'rgba(255,255,255,0)')
      grad.addColorStop(0.25, tracer.team === 'player' ? p.tracerPlayer : p.tracerGuard)
      grad.addColorStop(1, 'rgba(255,255,255,0.1)')
      ctx.globalAlpha = alpha
      ctx.strokeStyle = grad
      ctx.lineWidth = 2.6
      ctx.beginPath()
      ctx.moveTo(tracer.from.x, tracer.from.y)
      ctx.lineTo(tracer.to.x, tracer.to.y)
      ctx.stroke()
    }
    ctx.globalAlpha = 1
    for (const fx of round.fx) {
      const alpha = Math.max(0, fx.life / fx.max)
      if (fx.kind === 'flash') {
        // 枪口火光:外圈辉光 + 内侧星形
        ctx.save()
        ctx.globalAlpha = alpha
        ctx.translate(fx.pos.x, fx.pos.y)
        const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, 30)
        glow.addColorStop(0, 'rgba(255,240,190,.95)')
        glow.addColorStop(0.4, 'rgba(255,200,90,.55)')
        glow.addColorStop(1, 'rgba(255,170,60,0)')
        ctx.fillStyle = glow
        ctx.beginPath()
        ctx.arc(0, 0, 30, 0, Math.PI * 2)
        ctx.fill()
        ctx.rotate(fx.angle)
        ctx.fillStyle = '#FFF6D0'
        ctx.beginPath()
        ctx.moveTo(0, 0)
        ctx.lineTo(14, -4)
        ctx.lineTo(22, 0)
        ctx.lineTo(14, 4)
        ctx.closePath()
        ctx.fill()
        ctx.restore()
      } else if (fx.kind === 'spark') {
        // 命中火花:一小段沿速度方向的亮线
        ctx.globalAlpha = alpha
        ctx.strokeStyle = fx.team === 'player' ? p.tracerPlayer : p.tracerGuard
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.moveTo(fx.pos.x, fx.pos.y)
        ctx.lineTo(fx.pos.x - fx.vel.x * 0.025, fx.pos.y - fx.vel.y * 0.025)
        ctx.stroke()
      } else if (fx.kind === 'shell' && !opts.reduced) {
        // 弹壳:落地前转着的小铜块
        ctx.save()
        ctx.globalAlpha = alpha
        ctx.translate(fx.pos.x, fx.pos.y)
        ctx.rotate(fx.angle + (1 - alpha) * 6)
        ctx.fillStyle = '#E8B45A'
        ctx.fillRect(-2.4, -1.1, 4.8, 2.2)
        ctx.restore()
      } else if (fx.kind === 'smoke' && !opts.reduced) {
        ctx.globalAlpha = alpha * 0.2
        ctx.fillStyle = p.ghost
        ctx.beginPath()
        ctx.arc(fx.pos.x, fx.pos.y, 3 + (1 - alpha) * 10, 0, Math.PI * 2)
        ctx.fill()
      }
    }
    ctx.globalAlpha = 1
  }

  /** 圆角矩形(老 WebView 没有 ctx.roundRect,自己画) */
  private roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
    const radius = Math.min(r, w / 2, h / 2)
    ctx.beginPath()
    ctx.moveTo(x + radius, y)
    ctx.lineTo(x + w - radius, y)
    ctx.arcTo(x + w, y, x + w, y + radius, radius)
    ctx.lineTo(x + w, y + h - radius)
    ctx.arcTo(x + w, y + h, x + w - radius, y + h, radius)
    ctx.lineTo(x + radius, y + h)
    ctx.arcTo(x, y + h, x, y + h - radius, radius)
    ctx.lineTo(x, y + radius)
    ctx.arcTo(x, y, x + radius, y, radius)
    ctx.closePath()
  }
}
