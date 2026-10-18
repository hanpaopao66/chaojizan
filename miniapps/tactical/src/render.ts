// 画战场:整张地图一屏放下,全部用 Canvas 2D 程序化绘制(没有一张图片素材)。
//
// 只有玩家看得见(LOS + 视距)的守卫才画出来;失去视线后留 1 秒「最后已知位置」的虚影。
// 地图是静态的,预渲染成一张离屏画布缓存起来,只有换尺寸/换主题才重画,每帧只画人和特效。

import {
  CRATE, FLOOR, GameMap, TILE, Vec, WALL, WORLD_H, WORLD_W, dist, lineOfSight, siteCenter, tileAt,
} from './map'
import {
  BOMB_TIME, GuardState, PLAYER_RADIUS, PLAYER_VIEW_RANGE, PlayerState, Round,
} from './match'

/** 画布用的一套颜色,来自 style.css 里的 --tac-* 变量(亮暗各一套) */
export interface Palette {
  bg: string
  floor: string
  floorAlt: string
  grid: string
  wall: string
  wallTop: string
  wallEdge: string
  crate: string
  crateTop: string
  crateEdge: string
  siteA: string
  siteA2: string
  siteB: string
  siteB2: string
  siteInk: string
  player: string
  playerInk: string
  guard: string
  guardInk: string
  bomb: string
  bombInk: string
  ghost: string
  mapInk: string
  tracerPlayer: string
  tracerGuard: string
  shadow: string
  vignette: string
}

const FALLBACK: Palette = {
  bg: '#141A21', floor: '#2C333D', floorAlt: '#273039', grid: '#343D48',
  wall: '#4C5665', wallTop: '#636F81', wallEdge: '#1B2129',
  crate: '#7C5837', crateTop: '#966C43', crateEdge: '#4A301A',
  siteA: '#B98A3E', siteA2: '#9A7130', siteB: '#4F7FA0', siteB2: '#3E6885', siteInk: '#F2E8D0',
  player: '#4FC3F7', playerInk: '#08222E', guard: '#FF7A55', guardInk: '#2A0F08',
  bomb: '#FF5A4D', bombInk: '#2A0B08', ghost: '#CFD8E3', mapInk: '#E8DFC8',
  tracerPlayer: '#9BE1FF', tracerGuard: '#FFB598', shadow: 'rgba(0, 0, 0, .35)',
  vignette: 'rgba(6, 10, 14, .55)',
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** 从 CSS 变量读一套画布配色。主题切换后重新读一次(和界面文字一起换亮暗) */
export function readPalette(): Palette {
  return {
    bg: cssVar('--tac-bg', FALLBACK.bg),
    floor: cssVar('--tac-floor', FALLBACK.floor),
    floorAlt: cssVar('--tac-floor-alt', FALLBACK.floorAlt),
    grid: cssVar('--tac-grid', FALLBACK.grid),
    wall: cssVar('--tac-wall', FALLBACK.wall),
    wallTop: cssVar('--tac-wall-top', FALLBACK.wallTop),
    wallEdge: cssVar('--tac-wall-edge', FALLBACK.wallEdge),
    crate: cssVar('--tac-crate', FALLBACK.crate),
    crateTop: cssVar('--tac-crate-top', FALLBACK.crateTop),
    crateEdge: cssVar('--tac-crate-edge', FALLBACK.crateEdge),
    siteA: cssVar('--tac-site-a', FALLBACK.siteA),
    siteA2: cssVar('--tac-site-a-2', FALLBACK.siteA2),
    siteB: cssVar('--tac-site-b', FALLBACK.siteB),
    siteB2: cssVar('--tac-site-b-2', FALLBACK.siteB2),
    siteInk: cssVar('--tac-site-ink', FALLBACK.siteInk),
    player: cssVar('--tac-player', FALLBACK.player),
    playerInk: cssVar('--tac-player-ink', FALLBACK.playerInk),
    guard: cssVar('--tac-guard', FALLBACK.guard),
    guardInk: cssVar('--tac-guard-ink', FALLBACK.guardInk),
    bomb: cssVar('--tac-bomb', FALLBACK.bomb),
    bombInk: cssVar('--tac-bomb-ink', FALLBACK.bombInk),
    ghost: cssVar('--tac-ghost', FALLBACK.ghost),
    mapInk: cssVar('--tac-map-ink', FALLBACK.mapInk),
    tracerPlayer: cssVar('--tac-tracer-player', FALLBACK.tracerPlayer),
    tracerGuard: cssVar('--tac-tracer-guard', FALLBACK.tracerGuard),
    shadow: cssVar('--tac-shadow', FALLBACK.shadow),
    vignette: cssVar('--tac-vignette', FALLBACK.vignette),
  }
}

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
  private palette: Palette = FALLBACK
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
    const key = `${this.palette.floor}|${this.palette.wall}|${this.palette.siteA}|${this.palette.siteB}|${round.map.tiles.length}`
    if (key !== this.layerKey) this.buildLayer(round.map)
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
    this.drawGuards(round, opts)
    this.drawPlayer(round)
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

  private buildLayer(map: GameMap): void {
    if (!this.layer) this.layer = document.createElement('canvas')
    const ratio = 2
    this.layer.width = WORLD_W * ratio
    this.layer.height = WORLD_H * ratio
    const ctx = this.layer.getContext('2d')
    if (!ctx) return
    this.layerKey = `${this.palette.floor}|${this.palette.wall}|${this.palette.siteA}|${this.palette.siteB}|${map.tiles.length}`
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    const p = this.palette

    // 地面:两三种深浅交错,像水泥地
    for (let row = 0; row < WORLD_H / TILE; row++) {
      for (let col = 0; col < WORLD_W / TILE; col++) {
        ctx.fillStyle = (col * 7 + row * 13) % 3 === 0 ? p.floorAlt : p.floor
        ctx.fillRect(col * TILE, row * TILE, TILE, TILE)
      }
    }
    // 砖缝
    ctx.strokeStyle = p.grid
    ctx.globalAlpha = 0.45
    ctx.lineWidth = 1
    ctx.beginPath()
    for (let x = 0; x <= WORLD_W; x += TILE) {
      ctx.moveTo(x + 0.5, 0)
      ctx.lineTo(x + 0.5, WORLD_H)
    }
    for (let y = 0; y <= WORLD_H; y += TILE) {
      ctx.moveTo(0, y + 0.5)
      ctx.lineTo(WORLD_W, y + 0.5)
    }
    ctx.stroke()
    ctx.globalAlpha = 1

    this.paintSite(ctx, map.siteA, p.siteA, p.siteA2, 'A')
    this.paintSite(ctx, map.siteB, p.siteB, p.siteB2, 'B')

    // 墙和箱子
    for (let row = 0; row < WORLD_H / TILE; row++) {
      for (let col = 0; col < WORLD_W / TILE; col++) {
        const tile = tileAt(map, col, row)
        if (tile === FLOOR) continue
        const x = col * TILE
        const y = row * TILE
        ctx.fillStyle = p.shadow
        ctx.fillRect(x + 2, y + 4, TILE, TILE)
        if (tile === WALL) {
          ctx.fillStyle = p.wall
          ctx.fillRect(x, y, TILE, TILE)
          ctx.fillStyle = p.wallTop
          ctx.fillRect(x, y, TILE, 5)
          ctx.strokeStyle = p.wallEdge
          ctx.lineWidth = 1
          ctx.strokeRect(x + 0.5, y + 0.5, TILE - 1, TILE - 1)
        } else if (tile === CRATE) {
          ctx.fillStyle = p.crate
          ctx.fillRect(x + 2, y + 2, TILE - 4, TILE - 4)
          ctx.fillStyle = p.crateTop
          ctx.fillRect(x + 2, y + 2, TILE - 4, 5)
          ctx.strokeStyle = p.crateEdge
          ctx.lineWidth = 1.5
          ctx.strokeRect(x + 2.5, y + 2.5, TILE - 5, TILE - 5)
          ctx.beginPath()
          ctx.moveTo(x + 4, y + TILE - 6)
          ctx.lineTo(x + TILE - 6, y + 5)
          ctx.stroke()
        }
      }
    }
    // 地图最外圈压一道深色边
    ctx.strokeStyle = p.wallEdge
    ctx.lineWidth = 6
    ctx.strokeRect(3, 3, WORLD_W - 6, WORLD_H - 6)
  }

  private paintSite(
    ctx: CanvasRenderingContext2D,
    rect: { x0: number; y0: number; x1: number; y1: number },
    base: string,
    alt: string,
    letter: string,
  ): void {
    const x = rect.x0 * TILE
    const y = rect.y0 * TILE
    const w = (rect.x1 - rect.x0 + 1) * TILE
    const h = (rect.y1 - rect.y0 + 1) * TILE
    const p = this.palette
    ctx.save()
    ctx.fillStyle = base
    ctx.globalAlpha = 0.5
    ctx.fillRect(x, y, w, h)
    ctx.globalAlpha = 0.9
    ctx.strokeStyle = alt
    ctx.lineWidth = 3
    ctx.strokeRect(x + 2, y + 2, w - 4, h - 4)
    // 斜纹
    ctx.globalAlpha = 0.22
    ctx.beginPath()
    for (let k = -h; k < w; k += 18) {
      ctx.moveTo(x + k, y + h)
      ctx.lineTo(x + k + h, y)
    }
    ctx.stroke()
    ctx.globalAlpha = 1
    ctx.fillStyle = p.siteInk
    ctx.font = 'bold 58px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(letter, x + w / 2, y + h / 2)
    ctx.restore()
  }

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

  // ---------------------------------------------------------------- 守卫

  private drawGuards(round: Round, opts: DrawOptions): void {
    const visibleIds = new Set<number>()
    for (const guard of round.guards) {
      if (!guard.alive) continue
      const visible = dist(round.player.pos, guard.pos) <= PLAYER_VIEW_RANGE
        && lineOfSight(round.map, round.player.pos, guard.pos)
      if (visible) {
        visibleIds.add(guard.id)
        this.ghosts.set(guard.id, { pos: { ...guard.pos }, at: opts.now })
        this.drawGuard(guard)
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

  private drawGuard(guard: GuardState): void {
    const ctx = this.ctx
    const p = this.palette
    const pos = guard.pos
    ctx.fillStyle = p.shadow
    ctx.beginPath()
    ctx.ellipse(pos.x, pos.y + 6, 12, 5, 0, 0, Math.PI * 2)
    ctx.fill()
    // 身体:菱形 → 和玩家的圆区分开(不看颜色也分得清敌我)
    ctx.save()
    ctx.translate(pos.x, pos.y)
    ctx.rotate(guard.angle)
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
    ctx.moveTo(pos.x, pos.y - 19)
    ctx.lineTo(pos.x + 6, pos.y - 11)
    ctx.lineTo(pos.x - 6, pos.y - 11)
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

  private drawPlayer(round: Round): void {
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
    ctx.fillStyle = p.shadow
    ctx.beginPath()
    ctx.ellipse(pos.x, pos.y + 6, 12, 5, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.save()
    ctx.translate(pos.x, pos.y)
    ctx.rotate(player.angle)
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
    ctx.moveTo(pos.x, pos.y - 20)
    ctx.lineTo(pos.x + 5, pos.y - 28)
    ctx.lineTo(pos.x - 5, pos.y - 28)
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
    for (const tracer of round.tracers) {
      const alpha = Math.max(0, tracer.life / tracer.max)
      ctx.strokeStyle = tracer.team === 'player' ? p.tracerPlayer : p.tracerGuard
      ctx.globalAlpha = alpha * 0.9
      ctx.lineWidth = 2.2
      ctx.beginPath()
      ctx.moveTo(tracer.from.x, tracer.from.y)
      ctx.lineTo(tracer.to.x, tracer.to.y)
      ctx.stroke()
    }
    ctx.globalAlpha = 1
    for (const fx of round.fx) {
      const alpha = Math.max(0, fx.life / fx.max)
      if (fx.kind === 'flash') {
        ctx.save()
        ctx.globalAlpha = alpha
        ctx.translate(fx.pos.x, fx.pos.y)
        ctx.rotate(fx.angle)
        ctx.fillStyle = '#FFE9A8'
        ctx.beginPath()
        ctx.moveTo(0, 0)
        ctx.lineTo(11, -5)
        ctx.lineTo(16, 0)
        ctx.lineTo(11, 5)
        ctx.closePath()
        ctx.fill()
        ctx.restore()
      } else if (fx.kind === 'spark') {
        ctx.globalAlpha = alpha
        ctx.fillStyle = fx.team === 'player' ? p.tracerPlayer : p.tracerGuard
        ctx.fillRect(fx.pos.x - 1.5, fx.pos.y - 1.5, 3, 3)
      } else if (fx.kind === 'smoke' && !opts.reduced) {
        ctx.globalAlpha = alpha * 0.22
        ctx.fillStyle = p.ghost
        ctx.beginPath()
        ctx.arc(fx.pos.x, fx.pos.y, 3 + (1 - alpha) * 8, 0, Math.PI * 2)
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
