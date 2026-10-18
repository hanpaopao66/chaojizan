// 体素射线:DDA(Amanatides & Woo)逐格前进,给准星选方块和「按住挖」用。纯函数。
//
// 只认「挡住视线」的方块:水不挡(准星可以穿过去点水下的沙子),基岩挡但挖不动。
import { AIR, WATER } from './blocks'
import { D, H, W } from './worldgen'
import type { BlockSource } from './world'

/** 命中的面:法线指向射线来的那一侧 */
export type Face = 'x+' | 'x-' | 'y+' | 'y-' | 'z+' | 'z-'

export interface RayHit {
  /** 被命中的方块坐标 */
  x: number
  y: number
  z: number
  /** 从方块哪一面穿出来,法线朝外(放方块就放在这一面外侧) */
  nx: number
  ny: number
  nz: number
  face: Face
  /** 命中的方块编号 */
  block: number
  /** 从射线起点到命中点的距离(和方向向量同一单位) */
  dist: number
}

const FACES: Record<string, Face> = {
  '1,0,0': 'x+', '-1,0,0': 'x-', '0,1,0': 'y+', '0,-1,0': 'y-', '0,0,1': 'z+', '0,0,-1': 'z-',
}

/**
 * 从 (ox,oy,oz) 沿单位方向 (dx,dy,dz) 打一条射线,最多 maxDist 格。
 * 返回第一个不透明方块(空气、水会穿过去);什么都没打到返回 null。
 */
export function raycast(source: BlockSource, ox: number, oy: number, oz: number,
  dx: number, dy: number, dz: number, maxDist: number): RayHit | null {
  // 方向归一化(调用方一般已经归一化,这里兜一下,测试里写起来也舒服)
  const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
  if (!(len > 1e-9) || !(maxDist > 0)) return null
  if (len !== 1) {
    dx /= len
    dy /= len
    dz /= len
  }
  let x = Math.floor(ox)
  let y = Math.floor(oy)
  let z = Math.floor(oz)
  const stepX = dx > 0 ? 1 : dx < 0 ? -1 : 0
  const stepY = dy > 0 ? 1 : dy < 0 ? -1 : 0
  const stepZ = dz > 0 ? 1 : dz < 0 ? -1 : 0
  const tDeltaX = stepX === 0 ? Infinity : Math.abs(1 / dx)
  const tDeltaY = stepY === 0 ? Infinity : Math.abs(1 / dy)
  const tDeltaZ = stepZ === 0 ? Infinity : Math.abs(1 / dz)
  let tMaxX = stepX === 0 ? Infinity : (stepX > 0 ? x + 1 - ox : ox - x) / Math.abs(dx)
  let tMaxY = stepY === 0 ? Infinity : (stepY > 0 ? y + 1 - oy : oy - y) / Math.abs(dy)
  let tMaxZ = stepZ === 0 ? Infinity : (stepZ > 0 ? z + 1 - oz : oz - z) / Math.abs(dz)

  // 起点就在方块里(理论上不会):不返回命中,免得贴脸时选中自己脚下的方块
  let nx = 0
  let ny = 0
  let nz = 0
  let t = 0
  // 上限按最长可能步数来,防止极端情况下死循环
  for (let i = 0; i < 512; i++) {
    const block = source.blockAt(x, y, z)
    if (block !== AIR && block !== WATER) {
      return { x, y, z, nx, ny, nz, face: FACES[`${nx},${ny},${nz}`] ?? 'y+', block, dist: t }
    }
    if (tMaxX <= tMaxY && tMaxX <= tMaxZ) {
      x += stepX
      t = tMaxX
      tMaxX += tDeltaX
      nx = -stepX
      ny = 0
      nz = 0
    } else if (tMaxY <= tMaxZ) {
      y += stepY
      t = tMaxY
      tMaxY += tDeltaY
      nx = 0
      ny = -stepY
      nz = 0
    } else {
      z += stepZ
      t = tMaxZ
      tMaxZ += tDeltaZ
      nx = 0
      ny = 0
      nz = -stepZ
    }
    if (t > maxDist) return null
    // 走出世界:不再往前打(世界外没有方块可点)
    if (x < 0 || x >= W || z < 0 || z >= D || y < 0 || y >= H) return null
  }
  return null
}

/** 相机朝向 → 单位方向向量(yaw 0 朝 +x,绕 y 轴) */
export function lookDirection(yaw: number, pitch: number): { x: number; y: number; z: number } {
  const cp = Math.cos(pitch)
  return { x: Math.cos(yaw) * cp, y: Math.sin(pitch), z: Math.sin(yaw) * cp }
}

/** 从眼睛位置沿视线打射线(准星射线) */
export function rayFromEye(source: BlockSource, x: number, y: number, z: number,
  yaw: number, pitch: number, maxDist: number): RayHit | null {
  const d = lookDirection(yaw, pitch)
  return raycast(source, x, y, z, d.x, d.y, d.z, maxDist)
}

/** 放置位置 = 命中格 + 命中面法线 */
export function placePosition(hit: RayHit): { x: number; y: number; z: number } {
  return { x: hit.x + hit.nx, y: hit.y + hit.ny, z: hit.z + hit.nz }
}
