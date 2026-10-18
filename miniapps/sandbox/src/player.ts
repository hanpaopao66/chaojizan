// 第一人称移动和物理:AABB 碰撞、重力、跳跃、游泳。纯函数 + 固定步长,单测能复现。
//
// 坐标约定:player.x / z 是身体中心,y 是**脚底**;视线高 EYE_HEIGHT。
// 每帧按 dt 分步移动(单步不超过 0.4 格),高速下落也不会穿过一格厚的地板。
import { WATER, isSolid } from './blocks'
import { D, W } from './worldgen'
import type { BlockSource } from './world'

export const PLAYER_WIDTH = 0.6
export const PLAYER_HEIGHT = 1.8
export const EYE_HEIGHT = 1.62

const HALF = PLAYER_WIDTH / 2
const EPS = 1e-4
/** 落地时脚底压进方块的最大深度,防止浮点误差让人一帧落地一帧悬空 */
const GROUND_SNAP = 1e-3

const GRAVITY = 26
const JUMP_SPEED = 8.2
const WALK_SPEED = 4.5
const ACCEL = 14
const MAX_FALL = 48
const WATER_GRAVITY = 6
const WATER_MAX_FALL = 3.2
const SWIM_UP = 2.8
const WATER_SPEED = 2.4

export interface PlayerState {
  x: number
  y: number
  z: number
  vx: number
  vy: number
  vz: number
  yaw: number
  pitch: number
  onGround: boolean
  inWater: boolean
}

export interface MoveInput {
  /** 前后:+1 往前 */
  forward: number
  /** 左右:+1 往右 */
  strafe: number
  jump: boolean
}

export interface StepResult {
  landed: boolean
  jumped: boolean
  /** 掉出世界了,调用方负责把玩家放回出生点 */
  fellOut: boolean
}

export function newPlayer(x: number, y: number, z: number, yaw: number): PlayerState {
  return { x, y, z, vx: 0, vy: 0, vz: 0, yaw, pitch: 0, onGround: false, inWater: false }
}

/** 俯仰限制在 ±83°,抬头低头都看不到自己身后 */
export function clampPitch(pitch: number): number {
  const limit = 1.45
  return pitch < -limit ? -limit : pitch > limit ? limit : pitch
}

export function cameraEye(p: PlayerState): { x: number; y: number; z: number } {
  return { x: p.x, y: p.y + EYE_HEIGHT, z: p.z }
}

function block(source: BlockSource, x: number, y: number, z: number): number {
  return source.blockAt(x, y, z)
}

function inWaterAt(source: BlockSource, x: number, y: number, z: number): boolean {
  return block(source, Math.floor(x), Math.floor(y), Math.floor(z)) === WATER
}

/** 玩家的 AABB 现在压住了哪些实心方块(通常 0 个,撞墙时 1–4 个) */
function overlapCells(source: BlockSource, p: PlayerState): Array<[number, number, number]> {
  const x0 = Math.floor(p.x - HALF + EPS)
  const x1 = Math.floor(p.x + HALF - EPS)
  const y0 = Math.floor(p.y + EPS)
  const y1 = Math.floor(p.y + PLAYER_HEIGHT - EPS)
  const z0 = Math.floor(p.z - HALF + EPS)
  const z1 = Math.floor(p.z + HALF - EPS)
  const out: Array<[number, number, number]> = []
  for (let y = y0; y <= y1; y++) {
    for (let z = z0; z <= z1; z++) {
      for (let x = x0; x <= x1; x++) {
        if (isSolid(block(source, x, y, z))) out.push([x, y, z])
      }
    }
  }
  return out
}

/** 沿一个轴移动;撞到方块就贴面停下,返回有没有撞到 */
function moveAxis(source: BlockSource, p: PlayerState, axis: 'x' | 'y' | 'z', total: number): boolean {
  if (total === 0) return false
  const sign = total > 0 ? 1 : -1
  let remaining = total
  while (Math.abs(remaining) > 1e-9) {
    const stepSize = Math.min(Math.abs(remaining), 0.4)
    const step = stepSize * sign
    if (axis === 'x') p.x += step
    else if (axis === 'y') p.y += step
    else p.z += step
    remaining -= step
    const cells = overlapCells(source, p)
    if (!cells.length) continue
    // 贴到最近的那一面上
    if (axis === 'x') {
      if (sign > 0) p.x = Math.min(...cells.map((c) => c[0])) - HALF
      else p.x = Math.max(...cells.map((c) => c[0])) + 1 + HALF
      p.vx = 0
    } else if (axis === 'z') {
      if (sign > 0) p.z = Math.min(...cells.map((c) => c[2])) - HALF
      else p.z = Math.max(...cells.map((c) => c[2])) + 1 + HALF
      p.vz = 0
    } else {
      if (sign > 0) p.y = Math.min(...cells.map((c) => c[1])) - PLAYER_HEIGHT
      else p.y = Math.max(...cells.map((c) => c[1])) + 1
      p.vy = 0
      if (sign < 0) p.onGround = true
    }
    return true
  }
  return false
}

/** 头顶是不是被方块挡住了(水里上浮时用) */
export function headBlocked(source: BlockSource, p: PlayerState): boolean {
  return isSolid(block(source, Math.floor(p.x), Math.floor(p.y + PLAYER_HEIGHT - 0.05), Math.floor(p.z)))
}

/**
 * 推进一帧。会直接改 p(游戏里每帧都要用,避免分配);测试里传入自己造的状态检查结果。
 */
export function stepPlayer(source: BlockSource, p: PlayerState, input: MoveInput, dt: number): StepResult {
  const out: StepResult = { landed: false, jumped: false, fellOut: false }
  const step = Math.min(0.05, Math.max(0, dt))
  if (step <= 0) return out

  p.inWater = inWaterAt(source, p.x, p.y + 0.15, p.z) || inWaterAt(source, p.x, p.y + 0.95, p.z)
  const wasOnGround = p.onGround

  // 水平:往相机朝向的方向走,水里慢
  const cos = Math.cos(p.yaw)
  const sin = Math.sin(p.yaw)
  let dx = cos * input.forward - sin * input.strafe
  let dz = sin * input.forward + cos * input.strafe
  const len = Math.hypot(dx, dz)
  if (len > 1) {
    dx /= len
    dz /= len
  }
  const speed = p.inWater ? WATER_SPEED : WALK_SPEED
  const k = 1 - Math.exp(-ACCEL * step)
  p.vx += (dx * speed - p.vx) * k
  p.vz += (dz * speed - p.vz) * k

  // 竖直:水里慢慢浮/沉,陆地上跳
  if (input.jump) {
    if (p.inWater) {
      p.vy = Math.min(p.vy + WATER_GRAVITY * 5.5 * step, SWIM_UP)
      out.jumped = true
    } else if (p.onGround) {
      p.vy = JUMP_SPEED
      p.onGround = false
      out.jumped = true
    }
  }
  const gravity = p.inWater ? WATER_GRAVITY : GRAVITY
  p.vy -= gravity * step
  const maxFall = p.inWater ? WATER_MAX_FALL : MAX_FALL
  if (p.vy < -maxFall) p.vy = -maxFall
  if (p.inWater) p.vy *= 1 - 1.2 * step

  // 先水平、再竖直:顺着墙滑而不是卡住
  const preVx = p.vx
  const preVz = p.vz
  const hitX = moveAxis(source, p, 'x', preVx * step)
  const hitZ = moveAxis(source, p, 'z', preVz * step)
  if ((hitX || hitZ) && wasOnGround && !input.jump && !p.inWater) {
    // 自动上一层台阶:站在地上撞到不高于一格的坎,抬起来再走一次;
    // 两层以上(或抬起来会卡头)就照旧停住,想上去得跳。
    const saveX = p.x
    const saveY = p.y
    const saveZ = p.z
    const base = Math.round(p.y + 1e-6)
    const climb = base + 1 - p.y
    if (climb > 0.5 && climb <= 1.05) {
      p.y = base + 1
      if (overlapCells(source, p).length === 0) {
        p.vx = preVx
        p.vz = preVz
        const againX = moveAxis(source, p, 'x', preVx * step)
        const againZ = moveAxis(source, p, 'z', preVz * step)
        if (againX || againZ) {
          p.x = saveX
          p.y = saveY
          p.z = saveZ
          p.vx = 0
          p.vz = 0
        }
      } else {
        p.x = saveX
        p.y = saveY
        p.z = saveZ
      }
    } else {
      p.x = saveX
      p.y = saveY
      p.z = saveZ
    }
  }
  p.onGround = false
  moveAxis(source, p, 'y', p.vy * step)
  // 脚下再探一次:站在方块上时(竖直速度可能刚好是 0)也算落地
  if (!p.onGround && p.vy <= 0) {
    const ground = overlapCells(source, { ...p, y: p.y - GROUND_SNAP })
    if (ground.length) {
      p.y = Math.max(...ground.map((c) => c[1])) + 1
      p.vy = 0
      p.onGround = true
    }
  }
  if (p.onGround && !wasOnGround) out.landed = true

  if (p.y < -6) {
    out.fellOut = true
    p.vy = 0
  }
  if (p.x < HALF) p.x = HALF
  if (p.x > W - HALF) p.x = W - HALF
  if (p.z < HALF) p.z = HALF
  if (p.z > D - HALF) p.z = D - HALF
  return out
}

/** 把玩家放到出生点(或读档位置):如果卡在方块里就往上抬到空位 */
export function placePlayer(source: BlockSource, p: PlayerState, x: number, y: number, z: number): void {
  p.x = x
  p.y = y
  p.z = z
  p.vx = 0
  p.vy = 0
  p.vz = 0
  p.onGround = false
  p.inWater = false
  const probe = { ...p }
  for (let i = 0; i < 24; i++) {
    if (!overlapCells(source, probe).length) break
    probe.y += 0.25
  }
  p.y = probe.y
}
