// 虫子和大西瓜的画法:圆润的卡通虫(会走会飞、会冻会中毒)+ 有表情的大西瓜。
// 和 art.ts 共用同一套调色板与圆角/影子工具;只画世界坐标,不碰 DOM。
import { roundRect, shadow, type Pal } from './art'
import type { Enemy, EnemyDef, Vec } from './types'

// ---------------------------------------------------------------- 虫

export interface EnemyLook {
  frozen: boolean
  poisoned: boolean
  burning: boolean
  flash: boolean
  now: number
  boss: boolean
}

/** 画一只虫;pos 是地面位置,飞行虫整体往上抬一点并单独画影子 */
export function drawEnemy(ctx: CanvasRenderingContext2D, p: Pal, e: Enemy, def: EnemyDef, pos: Vec, look: EnemyLook): void {
  const bob = Math.sin(look.now / 120 + e.id * 1.7) * (def.flying ? 3 : 1.6)
  const lift = def.flying ? 14 : 0
  const size = def.size
  shadow(ctx, pos.x, pos.y + 6, size * 1.05, size * 0.5, p.shadow)
  ctx.save()
  ctx.translate(pos.x, pos.y - lift + bob)
  let body = def.color
  if (look.frozen) body = mix(body, '#8FD4FF', 0.55)
  else if (look.poisoned) body = mix(body, '#7AC85A', 0.35)
  if (look.flash) body = '#FFF6E0'
  if (look.burning && Math.floor(look.now / 90) % 2 === 0) body = mix(body, '#FFB24A', 0.4)
  ctx.fillStyle = body
  ctx.strokeStyle = 'rgba(30,30,20,0.55)'
  ctx.lineWidth = 1.8
  const drawBody = (): void => {
    ctx.beginPath()
    ctx.ellipse(0, 0, size, size * 0.82, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.stroke()
  }
  switch (e.kind) {
    case 'worm': {
      // 三节身体 + 小脚
      for (let i = 2; i >= 0; i--) {
        ctx.fillStyle = i === 0 ? body : mix(body, '#3E5E28', 0.06 * i)
        ctx.beginPath()
        ctx.arc(-i * size * 0.6, i === 0 ? 0 : Math.sin(look.now / 140 + i) * 1.5, size * (1 - i * 0.15), 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()
      }
      ctx.strokeStyle = '#3E5E28'
      ctx.lineWidth = 1.6
      for (let i = 0; i < 3; i++) {
        const x = -2 + i * 4
        ctx.beginPath()
        ctx.moveTo(x, size * 0.7)
        ctx.lineTo(x + 2, size * 0.7 + 4 + Math.sin(look.now / 100 + i) * 1.5)
        ctx.stroke()
      }
      break
    }
    case 'flea': {
      drawBody()
      ctx.strokeStyle = '#6E5A2E'
      ctx.lineWidth = 1.8
      const kick = Math.sin(look.now / 70 + e.id) * 3
      ctx.beginPath()
      ctx.moveTo(-size * 0.4, size * 0.6)
      ctx.lineTo(-size * 0.9, size + kick)
      ctx.moveTo(size * 0.4, size * 0.6)
      ctx.lineTo(size * 0.9, size + kick)
      ctx.stroke()
      break
    }
    case 'beetle': {
      drawBody()
      // 甲壳中线和护甲纹
      ctx.strokeStyle = '#2E3640'
      ctx.lineWidth = 1.6
      ctx.beginPath()
      ctx.moveTo(0, -size * 0.7)
      ctx.lineTo(0, size * 0.6)
      ctx.moveTo(-size * 0.7, -size * 0.2)
      ctx.lineTo(-size * 0.2, size * 0.1)
      ctx.moveTo(size * 0.7, -size * 0.2)
      ctx.lineTo(size * 0.2, size * 0.1)
      ctx.stroke()
      break
    }
    case 'moth': {
      const flap = 0.75 + Math.sin(look.now / 90 + e.id) * 0.25
      ctx.fillStyle = mix(def.color, '#FFF4D0', 0.4)
      ctx.strokeStyle = 'rgba(120,100,60,0.6)'
      for (const s of [-1, 1]) {
        ctx.save()
        ctx.scale(s, 1)
        ctx.beginPath()
        ctx.ellipse(size * 0.8, -2, size * 0.9, size * 0.55 * flap, 0.4, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()
        ctx.restore()
      }
      ctx.fillStyle = body
      drawBody()
      break
    }
    case 'wasp': {
      const flap = 0.7 + Math.sin(look.now / 70 + e.id) * 0.3
      ctx.fillStyle = 'rgba(230,244,255,0.75)'
      ctx.strokeStyle = 'rgba(90,120,140,0.5)'
      for (const s of [-1, 1]) {
        ctx.beginPath()
        ctx.ellipse(s * size * 0.75, -size * 0.5, size * 0.7, size * 0.35 * flap, s * 0.5, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()
      }
      drawBody()
      // 黄黑条纹
      ctx.strokeStyle = '#2E2A1C'
      ctx.lineWidth = 2.4
      for (let i = -1; i <= 1; i++) {
        ctx.beginPath()
        ctx.moveTo(-size * 0.5, i * size * 0.35)
        ctx.lineTo(size * 0.5, i * size * 0.35)
        ctx.stroke()
      }
      break
    }
    case 'pupa': {
      // 茧:竖着的椭圆 + 治疗光环
      ctx.save()
      ctx.rotate(-0.2)
      ctx.beginPath()
      ctx.ellipse(0, 0, size * 0.72, size, 0, 0, Math.PI * 2)
      ctx.fill()
      ctx.stroke()
      ctx.restore()
      const glow = 0.4 + 0.3 * Math.sin(look.now / 220 + e.id)
      ctx.strokeStyle = `rgba(160,220,255,${glow.toFixed(3)})`
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.arc(0, 0, size + 6, 0, Math.PI * 2)
      ctx.stroke()
      break
    }
    case 'ant':
    case 'antling': {
      const s = e.kind === 'antling' ? 0.8 : 1
      for (let i = 1; i >= 0; i--) {
        ctx.fillStyle = i === 0 ? body : mix(body, '#5E3224', 0.25)
        ctx.beginPath()
        ctx.arc(-i * size * 0.7 * s, Math.sin(look.now / 150 + i) * 1.2, size * (0.62 - i * 0.14) * s, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()
      }
      // 大颚
      ctx.strokeStyle = '#3A1E14'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(size * 0.5 * s, -2)
      ctx.lineTo(size * 0.95 * s, -5)
      ctx.moveTo(size * 0.5 * s, 2)
      ctx.lineTo(size * 0.95 * s, 5)
      ctx.stroke()
      break
    }
    case 'boss': {
      // 巨虫:厚甲壳 + 犄角
      ctx.fillStyle = body
      ctx.beginPath()
      ctx.ellipse(0, 0, size, size * 0.85, 0, 0, Math.PI * 2)
      ctx.fill()
      ctx.stroke()
      ctx.fillStyle = mix(body, '#2A1E16', 0.4)
      ctx.beginPath()
      ctx.ellipse(0, -size * 0.25, size * 0.8, size * 0.45, 0, 0, Math.PI * 2)
      ctx.fill()
      ctx.strokeStyle = '#2A1E16'
      ctx.lineWidth = 3
      ctx.beginPath()
      ctx.moveTo(-size * 0.5, -size * 0.7)
      ctx.lineTo(-size * 0.95, -size * 1.15)
      ctx.moveTo(size * 0.5, -size * 0.7)
      ctx.lineTo(size * 0.95, -size * 1.15)
      ctx.stroke()
      // 眼睛
      ctx.fillStyle = '#FFE08A'
      ctx.beginPath()
      ctx.arc(-size * 0.3, -size * 0.2, 3.2, 0, Math.PI * 2)
      ctx.arc(size * 0.3, -size * 0.2, 3.2, 0, Math.PI * 2)
      ctx.fill()
      break
    }
  }
  // 眼睛(除了 Boss 上面已经画了)
  if (e.kind !== 'boss' && e.kind !== 'pupa') {
    ctx.fillStyle = '#2B2B22'
    ctx.beginPath()
    ctx.arc(-size * 0.32, -size * 0.22, 1.9, 0, Math.PI * 2)
    ctx.arc(size * 0.32, -size * 0.22, 1.9, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = 'rgba(255,255,255,0.85)'
    ctx.beginPath()
    ctx.arc(-size * 0.28, -size * 0.28, 0.7, 0, Math.PI * 2)
    ctx.arc(size * 0.36, -size * 0.28, 0.7, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
  // 小血条(受伤才显示;Boss 由顶部常驻血条负责)
  if (!look.boss && e.hp < e.maxHp) {
    const w = Math.max(16, size * 2)
    const x = pos.x - w / 2
    const y = pos.y - lift - size - 9
    ctx.fillStyle = 'rgba(24,26,20,0.5)'
    roundRect(ctx, x, y, w, 3.6, 1.8)
    ctx.fill()
    ctx.fillStyle = '#8FD46A'
    roundRect(ctx, x, y, Math.max(1, w * Math.max(0, e.hp / e.maxHp)), 3.6, 1.8)
    ctx.fill()
  }
  // 状态标记
  const markY = pos.y - lift - size - 16
  if (look.frozen) {
    ctx.strokeStyle = '#BFE9FF'
    ctx.lineWidth = 1.6
    ctx.beginPath()
    for (let i = 0; i < 3; i++) {
      const a = (i / 3) * Math.PI
      ctx.moveTo(pos.x - Math.cos(a) * 5, markY - Math.sin(a) * 5)
      ctx.lineTo(pos.x + Math.cos(a) * 5, markY + Math.sin(a) * 5)
    }
    ctx.stroke()
  } else if (look.poisoned && Math.sin(look.now / 200) > 0) {
    ctx.fillStyle = '#8ED46A'
    for (let i = 0; i < 2; i++) {
      ctx.beginPath()
      ctx.arc(pos.x - 5 + i * 9, markY - 2, 1.8, 0, Math.PI * 2)
      ctx.fill()
    }
  }
}

/** 两个颜色按比例混(用来做冰冻/中毒的染色) */
function mix(a: string, b: string, t: number): string {
  const pa = parseInt(a.slice(1), 16)
  const pb = parseInt(b.slice(1), 16)
  const r = Math.round(((pa >> 16) & 255) * (1 - t) + ((pb >> 16) & 255) * t)
  const g = Math.round(((pa >> 8) & 255) * (1 - t) + ((pb >> 8) & 255) * t)
  const bl = Math.round((pa & 255) * (1 - t) + (pb & 255) * t)
  return `rgb(${r},${g},${bl})`
}

// ---------------------------------------------------------------- 大西瓜

export type MelonMood = 'idle' | 'hurt' | 'low' | 'win' | 'lose'

export function drawWatermelon(ctx: CanvasRenderingContext2D, p: Pal, center: Vec, radius: number,
  mood: MelonMood, now: number): void {
  const squash = mood === 'hurt' ? Math.sin(now / 40) * 0.06 : Math.sin(now / 700) * 0.02
  ctx.save()
  shadow(ctx, center.x, center.y + radius * 0.72, radius * 0.95, radius * 0.34, p.shadow)
  ctx.translate(center.x, center.y)
  ctx.rotate(0.06)
  ctx.scale(1 + squash, 1 - squash)
  // 瓜身
  ctx.fillStyle = p.target
  ctx.beginPath()
  ctx.ellipse(0, 0, radius, radius * 0.88, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.strokeStyle = p.targetDark
  ctx.lineWidth = 3
  ctx.stroke()
  // 深色瓜纹
  ctx.strokeStyle = p.targetDark
  ctx.lineWidth = radius * 0.11
  ctx.lineCap = 'round'
  for (const k of [-0.55, 0, 0.55]) {
    ctx.beginPath()
    ctx.moveTo(k * radius * 0.85, -radius * 0.62)
    ctx.quadraticCurveTo(k * radius * 1.15, 0, k * radius * 0.85, radius * 0.62)
    ctx.stroke()
  }
  ctx.lineCap = 'butt'
  // 高光
  ctx.fillStyle = p.targetLight
  ctx.globalAlpha = 0.32
  ctx.beginPath()
  ctx.ellipse(-radius * 0.36, -radius * 0.34, radius * 0.26, radius * 0.16, -0.6, 0, Math.PI * 2)
  ctx.fill()
  ctx.globalAlpha = 1
  // 小叶子
  ctx.fillStyle = p.leaf
  ctx.beginPath()
  ctx.ellipse(radius * 0.18, -radius * 0.9, radius * 0.2, radius * 0.1, -0.4, 0, Math.PI * 2)
  ctx.fill()
  ctx.strokeStyle = p.targetDark
  ctx.lineWidth = 2.4
  ctx.beginPath()
  ctx.moveTo(0, -radius * 0.86)
  ctx.quadraticCurveTo(radius * 0.06, -radius, -radius * 0.04, -radius * 1.06)
  ctx.stroke()
  // 脸
  face(ctx, mood, radius, now)
  ctx.restore()
}

function face(ctx: CanvasRenderingContext2D, mood: MelonMood, r: number, now: number): void {
  const eyeY = -r * 0.12
  const eyeX = r * 0.3
  ctx.strokeStyle = '#24301C'
  ctx.fillStyle = '#24301C'
  ctx.lineWidth = Math.max(2, r * 0.055)
  ctx.lineCap = 'round'
  if (mood === 'lose') {
    for (const s of [-1, 1]) {
      ctx.beginPath()
      ctx.moveTo(s * eyeX - r * 0.1, eyeY - r * 0.1)
      ctx.lineTo(s * eyeX + r * 0.1, eyeY + r * 0.1)
      ctx.moveTo(s * eyeX + r * 0.1, eyeY - r * 0.1)
      ctx.lineTo(s * eyeX - r * 0.1, eyeY + r * 0.1)
      ctx.stroke()
    }
    ctx.beginPath()
    ctx.moveTo(-r * 0.16, r * 0.34)
    ctx.quadraticCurveTo(0, r * 0.22, r * 0.16, r * 0.34)
    ctx.stroke()
    return
  }
  const blink = Math.sin(now / 900) > 0.97
  if (blink) {
    for (const s of [-1, 1]) {
      ctx.beginPath()
      ctx.moveTo(s * eyeX - r * 0.1, eyeY)
      ctx.lineTo(s * eyeX + r * 0.1, eyeY)
      ctx.stroke()
    }
  } else {
    for (const s of [-1, 1]) {
      ctx.beginPath()
      ctx.arc(s * eyeX, eyeY, r * 0.11, 0, Math.PI * 2)
      ctx.fill()
      ctx.fillStyle = 'rgba(255,255,255,0.9)'
      ctx.beginPath()
      ctx.arc(s * eyeX - r * 0.03, eyeY - r * 0.04, r * 0.035, 0, Math.PI * 2)
      ctx.fill()
      ctx.fillStyle = '#24301C'
    }
  }
  if (mood === 'win') {
    ctx.beginPath()
    ctx.arc(0, r * 0.12, r * 0.3, 0.15, Math.PI - 0.15)
    ctx.stroke()
    // 腮红
    ctx.fillStyle = 'rgba(240,140,120,0.45)'
    ctx.beginPath()
    ctx.arc(-r * 0.55, r * 0.16, r * 0.12, 0, Math.PI * 2)
    ctx.arc(r * 0.55, r * 0.16, r * 0.12, 0, Math.PI * 2)
    ctx.fill()
    return
  }
  if (mood === 'hurt' || mood === 'low') {
    ctx.beginPath()
    ctx.moveTo(-r * 0.26, r * 0.3)
    ctx.quadraticCurveTo(-r * 0.13, r * 0.2, 0, r * 0.3)
    ctx.quadraticCurveTo(r * 0.13, r * 0.2, r * 0.26, r * 0.3)
    ctx.stroke()
    if (mood === 'low') {
      // 一滴眼泪
      ctx.fillStyle = 'rgba(140,200,255,0.85)'
      ctx.beginPath()
      const drop = (now / 30) % 10
      ctx.ellipse(-r * 0.32, r * 0.06 + drop, r * 0.045, r * 0.07, 0, 0, Math.PI * 2)
      ctx.fill()
    }
    return
  }
  ctx.beginPath()
  ctx.arc(0, r * 0.08, r * 0.22, 0.2, Math.PI - 0.2)
  ctx.stroke()
}
