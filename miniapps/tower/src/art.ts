// 全部美术都在这里:三套主题调色板,七种塔、九种虫、大西瓜和建造位的 Canvas 2D 画法。
// 只用色块、圆角矩形、曲线和程序化噪声点,没有图片;同一个 now 画出来是同一帧(不抖动)。
import { TILE, towerStats } from './data'
import type { Theme, Tower, TowerDef } from './types'

/** canvas 用的一整套颜色(由主题和亮暗决定) */
export interface Pal {
  bg: string
  grass: string
  grassAlt: string
  grassDark: string
  path: string
  pathLight: string
  pathEdge: string
  pebble: string
  post: string
  postTop: string
  postInk: string
  target: string
  targetDark: string
  targetLight: string
  leaf: string
  ink: string
  accent: string
  shadow: string
  night: boolean
}

const LIGHT: Record<Theme, Pal> = {
  garden: {
    bg: '#E7F0D2', grass: '#9CBE6E', grassAlt: '#8FB363', grassDark: '#7FA354',
    path: '#D2A96C', pathLight: '#E3C48D', pathEdge: '#AE8654', pebble: '#F3E4BC',
    post: '#B98A5C', postTop: '#E0BE8A', postInk: '#7A5836',
    target: '#4E9E4D', targetDark: '#3B7C3C', targetLight: '#7DBE63', leaf: '#6FA84C',
    ink: '#2F3A22', accent: '#C15F3C', shadow: 'rgba(46,58,34,0.20)', night: false,
  },
  orchard: {
    bg: '#F6E7C8', grass: '#C2B06A', grassAlt: '#B5A35F', grassDark: '#A59252',
    path: '#C08A56', pathLight: '#D6A371', pathEdge: '#9A6B40', pebble: '#E9CFA2',
    post: '#8E6A48', postTop: '#C7A171', postInk: '#5E4128',
    target: '#4C8E4A', targetDark: '#3A6F39', targetLight: '#7CB864', leaf: '#8A9E4A',
    ink: '#3A2F20', accent: '#B46A34', shadow: 'rgba(58,47,32,0.22)', night: false,
  },
  nest: {
    bg: '#DDE6E2', grass: '#7F9A86', grassAlt: '#748F7C', grassDark: '#688270',
    path: '#8E7A72', pathLight: '#A89289', pathEdge: '#6E5C57', pebble: '#C0B4AC',
    post: '#8A7466', postTop: '#B49B8A', postInk: '#54453E',
    target: '#4E8E58', targetDark: '#3B6F45', targetLight: '#7DBE86', leaf: '#6A9A5A',
    ink: '#1E2A2E', accent: '#4E6E8F', shadow: 'rgba(20,32,36,0.26)', night: true,
  },
}

const DARK: Record<Theme, Pal> = {
  garden: {
    bg: '#1E2418', grass: '#55663F', grassAlt: '#4C5C38', grassDark: '#435132',
    path: '#8A7048', pathLight: '#A08355', pathEdge: '#6D5738', pebble: '#B49A6C',
    post: '#7A5A3B', postTop: '#9C7A55', postInk: '#4A3522',
    target: '#3C7A3E', targetDark: '#2D5E2F', targetLight: '#5E9C55', leaf: '#4E7A3A',
    ink: '#E8EEDC', accent: '#E08A6B', shadow: 'rgba(5,10,4,0.38)', night: false,
  },
  orchard: {
    bg: '#241C16', grass: '#6E6242', grassAlt: '#645839', grassDark: '#584E32',
    path: '#9A6F47', pathLight: '#B08355', pathEdge: '#75532F', pebble: '#C3A471',
    post: '#7A5A3B', postTop: '#9C7A55', postInk: '#4A3522',
    target: '#3E7040', targetDark: '#2F5731', targetLight: '#649553', leaf: '#5E7038',
    ink: '#F2EBDC', accent: '#E08A6B', shadow: 'rgba(10,6,3,0.42)', night: false,
  },
  nest: {
    bg: '#121A1E', grass: '#3E4F4A', grassAlt: '#374741', grassDark: '#31403A',
    path: '#5E504C', pathLight: '#75645F', pathEdge: '#483D3A', pebble: '#8C807A',
    post: '#6A5A50', postTop: '#8A776A', postInk: '#3A302B',
    target: '#3E7A4A', targetDark: '#2E5E39', targetLight: '#5E9C68', leaf: '#4E7A48',
    ink: '#E8F0EA', accent: '#8FB4D8', shadow: 'rgba(2,8,10,0.46)', night: true,
  },
}

export function paletteFor(theme: Theme, dark: boolean): Pal {
  return dark ? DARK[theme] : LIGHT[theme]
}

/** 圆角矩形路径 */
export function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  const rr = Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2)
  ctx.beginPath()
  ctx.moveTo(x + rr, y)
  ctx.lineTo(x + w - rr, y)
  ctx.arcTo(x + w, y, x + w, y + rr, rr)
  ctx.lineTo(x + w, y + h - rr)
  ctx.arcTo(x + w, y + h, x + w - rr, y + h, rr)
  ctx.lineTo(x + rr, y + h)
  ctx.arcTo(x, y + h, x, y + h - rr, rr)
  ctx.lineTo(x, y + rr)
  ctx.arcTo(x, y, x + rr, y, rr)
  ctx.closePath()
}

/** 地面上的影子(虫和西瓜也用) */
export function shadow(ctx: CanvasRenderingContext2D, x: number, y: number, rx: number, ry: number, color: string): void {
  ctx.fillStyle = color
  ctx.beginPath()
  ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2)
  ctx.fill()
}

// ---------------------------------------------------------------- 建造位

/** 建造位:一圈木桩 / 石板;空位是虚线圈,放上塔以后变成短木桩 */
export function drawSlot(ctx: CanvasRenderingContext2D, p: Pal, x: number, y: number, o: {
  empty: boolean
  hover: boolean
  selected: boolean
  highlight: boolean
  now: number
}): void {
  const r = TILE * 0.62
  ctx.save()
  ctx.translate(x, y)
  if (!o.empty) {
    // 有塔的底座:一圈木板
    ctx.fillStyle = p.shadow
    ctx.beginPath()
    ctx.ellipse(0, 8, r * 0.9, r * 0.45, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = p.post
    ctx.beginPath()
    ctx.arc(0, 5, r * 0.7, 0, Math.PI * 2)
    ctx.fill()
    ctx.strokeStyle = p.postInk
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.fillStyle = p.postTop
    ctx.beginPath()
    ctx.arc(0, 2, r * 0.42, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
    return
  }
  // 空位:虚线圆 + 中间小木桩
  ctx.strokeStyle = o.selected ? p.accent : p.postInk
  ctx.globalAlpha = o.hover || o.selected ? 0.95 : 0.55
  ctx.lineWidth = o.hover || o.selected ? 3 : 2
  ctx.setLineDash([5, 5])
  ctx.beginPath()
  ctx.arc(0, 3, r, 0, Math.PI * 2)
  ctx.stroke()
  ctx.setLineDash([])
  ctx.globalAlpha = 1
  ctx.fillStyle = p.post
  roundRect(ctx, -4, -6, 8, 14, 3)
  ctx.fill()
  ctx.fillStyle = p.postTop
  ctx.beginPath()
  ctx.arc(0, -7, 5, 0, Math.PI * 2)
  ctx.fill()
  if (o.highlight) {
    // 第一关的教学高亮:一圈会呼吸的绿光
    const pulse = 0.5 + 0.5 * Math.sin(o.now / 260)
    ctx.strokeStyle = p.accent
    ctx.globalAlpha = 0.35 + pulse * 0.45
    ctx.lineWidth = 3 + pulse * 2
    ctx.beginPath()
    ctx.arc(0, 3, r + 6 + pulse * 4, 0, Math.PI * 2)
    ctx.stroke()
    ctx.globalAlpha = 1
  }
  ctx.restore()
}

// ---------------------------------------------------------------- 塔

const TOWER_COLOR: Record<string, string> = {
  pea: '#7FA650',
  frost: '#5E9CC4',
  pepper: '#D8623A',
  vine: '#C8A83C',
  mushroom: '#9C6BA8',
  bow: '#8A6E4B',
  marigold: '#E0A93C',
}

/** 塔的等级标记:底座一圈金色小点 */
function levelPips(ctx: CanvasRenderingContext2D, level: number, color: string): void {
  ctx.fillStyle = color
  for (let i = 0; i < level; i++) {
    const a = -Math.PI / 2 + (i - (level - 1) / 2) * 0.7
    ctx.beginPath()
    ctx.arc(Math.cos(a) * 20, 10 + Math.sin(a) * 5, 2.6, 0, Math.PI * 2)
    ctx.fill()
  }
}

export function drawTower(ctx: CanvasRenderingContext2D, p: Pal, tower: Tower, def: TowerDef, now: number): void {
  const towerColor = TOWER_COLOR[tower.kind] || def.color
  const stats = towerStats(tower.kind, tower.level)
  // 最近开过火的塔会有一点点后坐(只是让画面有生气,不影响判定)
  const recoil = Math.max(0, Math.min(1, (tower.cd - 1 / Math.max(0.1, stats.rate)) * 4)) * 2.4
  ctx.save()
  shadow(ctx, 0, 12, 20, 8, p.shadow)
  ctx.strokeStyle = p.postInk
  ctx.lineWidth = 2
  ctx.fillStyle = p.postTop
  ctx.beginPath()
  ctx.arc(0, 6, 12, 0, Math.PI * 2)
  ctx.fill()
  ctx.stroke()
  for (let i = 0; i < 4; i++) {
    ctx.strokeStyle = p.post
    ctx.beginPath()
    ctx.moveTo(Math.cos(i * 1.5) * 9, 6 + Math.sin(i * 1.5) * 4)
    ctx.lineTo(Math.cos(i * 1.5) * 13, 6 + Math.sin(i * 1.5) * 6)
    ctx.stroke()
  }
  levelPips(ctx, tower.level, '#F2D06A')
  ctx.translate(0, -2 - recoil)
  const sway = Math.sin(now / 420 + tower.id) * 0.05
  switch (tower.kind) {
    case 'pea': {
      ctx.save()
      ctx.rotate(tower.aim + Math.PI / 2)
      ctx.fillStyle = '#5E8A3C'
      roundRect(ctx, -6, -20, 12, 22, 6)
      ctx.fill()
      ctx.fillStyle = towerColor
      roundRect(ctx, -8, -22, 16, 16, 8)
      ctx.fill()
      ctx.strokeStyle = '#3F5E28'
      ctx.lineWidth = 1.6
      ctx.stroke()
      ctx.fillStyle = '#3F5E28'
      ctx.beginPath()
      ctx.arc(0, -22, 3.4, 0, Math.PI * 2)
      ctx.fill()
      // 3 级双发:两个小炮口
      if (tower.level >= 3) {
        ctx.fillStyle = '#2E4620'
        ctx.beginPath()
        ctx.arc(-4, -26, 2.4, 0, Math.PI * 2)
        ctx.arc(4, -26, 2.4, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.restore()
      break
    }
    case 'frost': {
      const swing = Math.sin(now / 300 + tower.id) * 0.22
      ctx.strokeStyle = p.postInk
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(0, 4)
      ctx.lineTo(0, -14)
      ctx.stroke()
      ctx.save()
      ctx.translate(0, -14)
      ctx.rotate(swing)
      ctx.fillStyle = towerColor
      ctx.beginPath()
      ctx.moveTo(-9, 0)
      ctx.quadraticCurveTo(0, 12, 9, 0)
      ctx.closePath()
      ctx.fill()
      ctx.strokeStyle = '#2F5C7A'
      ctx.lineWidth = 1.4
      ctx.stroke()
      ctx.fillStyle = '#EAF6FF'
      ctx.beginPath()
      ctx.arc(0, -1, 3, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
      break
    }
    case 'pepper': {
      ctx.save()
      ctx.rotate(tower.aim + Math.PI / 2)
      ctx.fillStyle = '#7A3A1E'
      roundRect(ctx, -4, -14, 8, 18, 3)
      ctx.fill()
      ctx.fillStyle = towerColor
      ctx.beginPath()
      ctx.moveTo(-8, -14)
      ctx.quadraticCurveTo(0, -34, 8, -14)
      ctx.quadraticCurveTo(0, -6, -8, -14)
      ctx.fill()
      ctx.strokeStyle = '#8A2F14'
      ctx.lineWidth = 1.6
      ctx.stroke()
      ctx.strokeStyle = '#4E6B2C'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(0, -16)
      ctx.quadraticCurveTo(4, -22, 7, -20)
      ctx.stroke()
      // 引线火花
      ctx.fillStyle = now % 600 < 300 ? '#FFE07A' : '#FF9C4A'
      ctx.beginPath()
      ctx.arc(8, -21, 2.4, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
      break
    }
    case 'vine': {
      ctx.strokeStyle = '#5E7A38'
      ctx.lineWidth = 5
      ctx.beginPath()
      ctx.moveTo(0, 6)
      ctx.bezierCurveTo(-12, -6, 10, -12, 0, -22)
      ctx.stroke()
      ctx.strokeStyle = '#7FA650'
      ctx.lineWidth = 2.6
      ctx.beginPath()
      ctx.moveTo(0, 6)
      ctx.bezierCurveTo(-10, -4, 8, -12, 0, -22)
      ctx.stroke()
      const glow = 0.55 + 0.45 * Math.sin(now / 130 + tower.id * 3)
      ctx.fillStyle = towerColor
      ctx.globalAlpha = glow
      ctx.beginPath()
      ctx.arc(0, -22, 7, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalAlpha = 1
      ctx.strokeStyle = '#FFF2A6'
      ctx.lineWidth = 1.6
      ctx.beginPath()
      ctx.moveTo(-4, -26)
      ctx.lineTo(1, -22)
      ctx.lineTo(-2, -18)
      ctx.lineTo(4, -15)
      ctx.stroke()
      break
    }
    case 'mushroom': {
      ctx.strokeStyle = '#E8DCC8'
      ctx.lineWidth = 7
      ctx.beginPath()
      ctx.moveTo(-2, 6)
      ctx.lineTo(0, -10)
      ctx.stroke()
      ctx.fillStyle = towerColor
      ctx.beginPath()
      ctx.ellipse(0, -16, 16, 10, 0, Math.PI, Math.PI * 2)
      ctx.fill()
      ctx.strokeStyle = '#6E4A78'
      ctx.lineWidth = 1.6
      ctx.stroke()
      ctx.fillStyle = '#D8C0E0'
      for (const [dx, dy, r] of [[-8, -19, 3], [5, -20, 2.4], [0, -15, 2]] as const) {
        ctx.beginPath()
        ctx.arc(dx, dy, r, 0, Math.PI * 2)
        ctx.fill()
      }
      // 飘着的孢子
      for (let i = 0; i < 3; i++) {
        const t = (now / 1400 + i / 3) % 1
        ctx.globalAlpha = 0.5 * (1 - t)
        ctx.fillStyle = '#E0C8F0'
        ctx.beginPath()
        ctx.arc(Math.sin(t * 6 + i) * 10, -24 - t * 14, 2, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalAlpha = 1
      break
    }
    case 'bow': {
      ctx.save()
      ctx.rotate(tower.aim + Math.PI / 2)
      ctx.strokeStyle = '#6B5233'
      ctx.lineWidth = 3
      ctx.beginPath()
      ctx.arc(0, -12, 12, -1.15, 1.15)
      ctx.stroke()
      ctx.strokeStyle = '#D8E0C0'
      ctx.lineWidth = 1.4
      ctx.beginPath()
      ctx.moveTo(-10.8, -7)
      ctx.lineTo(0, -14)
      ctx.lineTo(10.8, -7)
      ctx.stroke()
      ctx.strokeStyle = '#8A6E4B'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(0, -2)
      ctx.lineTo(0, -24)
      ctx.stroke()
      ctx.fillStyle = '#E8DCC8'
      ctx.beginPath()
      ctx.moveTo(0, -28)
      ctx.lineTo(-3, -22)
      ctx.lineTo(3, -22)
      ctx.closePath()
      ctx.fill()
      ctx.restore()
      break
    }
    case 'marigold': {
      ctx.save()
      ctx.translate(0, -14)
      ctx.rotate(sway + now / 2600)
      const petals = 8
      for (let i = 0; i < petals; i++) {
        ctx.rotate((Math.PI * 2) / petals)
        ctx.fillStyle = towerColor
        ctx.beginPath()
        ctx.ellipse(0, -9, 4.2, 8, 0, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.fillStyle = '#8A5E1E'
      ctx.beginPath()
      ctx.arc(0, 0, 5, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
      const sparkle = (now / 900) % 1
      ctx.globalAlpha = 1 - sparkle
      ctx.fillStyle = '#FFE08A'
      ctx.beginPath()
      ctx.arc(14, -30 - sparkle * 8, 2.2, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalAlpha = 1
      break
    }
  }
  ctx.restore()
}
