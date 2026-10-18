// 枪械规则与命中判定:弹匣、射速、换弹、散布、后坐力、hitscan。
//
// 和界面无关:枪的状态是一份纯数据,开一枪 / 走一帧 / 换完弹都是返回新状态;
// 子弹是「瞬时」的 —— 扣扳机那一刻就沿射线算先撞墙还是先撞人,曳光只是画出来的视觉效果。

import { GameMap, TILE, Vec, rayCircle, wallDistance } from './map'
import { rand } from '../../shared/src/rand'

export type Difficulty = 'casual' | 'normal' | 'hard'

/** 难度从低到高排好,界面按这个顺序摆按钮 */
export const DIFFICULTIES: readonly Difficulty[] = ['casual', 'normal', 'hard']

/** 界面上显示的难度名 */
export const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  casual: '休闲',
  normal: '标准',
  hard: '困难',
}

export const DEG = Math.PI / 180

export interface Rifle {
  /** 弹匣容量 */
  magazine: number
  /** 备弹 */
  reserve: number
  /** 连射间隔(秒) */
  fireInterval: number
  /** 换弹耗时(秒) */
  reloadTime: number
  /** 单发伤害 */
  damage: number
  /** 最远射程(世界单位) */
  range: number
  /** 刚开第一枪时的散布(度) */
  baseSpread: number
  /** 每开一枪增加的散布(度) */
  spreadPerShot: number
  /** 散布上限(度) */
  maxSpread: number
  /** 停火后每秒恢复多少度 */
  recover: number
}

/** 突击步枪:30 发弹匣、90 发备弹、7 发/秒、换弹 2 秒、伤害 24(四枪一个) */
export const RIFLE: Rifle = {
  magazine: 30,
  reserve: 90,
  fireInterval: 1 / 7,
  reloadTime: 2,
  damage: 24,
  range: TILE * 38,
  baseSpread: 1.1,
  spreadPerShot: 0.95,
  maxSpread: 8,
  recover: 7,
}

export interface GunState {
  /** 弹匣里还有几发 */
  mag: number
  /** 备弹 */
  reserve: number
  /** 距离下一发还要等多久(秒) */
  cooldown: number
  /** 换弹还要多久(秒);0 = 没在换 */
  reloadLeft: number
  /** 当前后坐力(额外散布,度) */
  recoil: number
  /** 距离上一发过了多久(秒):停火一会儿才开始恢复 */
  sinceShot: number
}

export function newGun(rifle: Rifle = RIFLE): GunState {
  return { mag: rifle.magazine, reserve: rifle.reserve, cooldown: 0, reloadLeft: 0, recoil: 0, sinceShot: 99 }
}

export function reloading(gun: GunState): boolean {
  return gun.reloadLeft > 0
}

/** 现在能不能扣扳机 */
export function canFire(gun: GunState): boolean {
  return gun.mag > 0 && gun.reloadLeft <= 0 && gun.cooldown <= 0
}

/** 开始换弹。弹匣满了、没备弹、已经在换 —— 都不动 */
export function startReload(gun: GunState, rifle: Rifle = RIFLE): GunState {
  if (gun.reloadLeft > 0 || gun.mag >= rifle.magazine || gun.reserve <= 0) return gun
  return { ...gun, reloadLeft: rifle.reloadTime }
}

/** 开一枪:弹匣 -1、进入射击间隔、后坐力增加。调用前先用 canFire 判断 */
export function fireGun(gun: GunState, rifle: Rifle = RIFLE): GunState {
  if (gun.mag <= 0) return gun
  return {
    ...gun,
    mag: gun.mag - 1,
    cooldown: rifle.fireInterval,
    recoil: Math.min(rifle.maxSpread - rifle.baseSpread, gun.recoil + rifle.spreadPerShot),
    sinceShot: 0,
  }
}

/**
 * 走一帧:射击间隔、换弹倒计时、后坐力恢复。
 * 后坐力停火 0.25 秒后才开始恢复 —— 点射能压住,连射会越打越散。
 */
export function tickGun(gun: GunState, dt: number, rifle: Rifle = RIFLE): GunState {
  let mag = gun.mag
  let reserve = gun.reserve
  let reloadLeft = gun.reloadLeft
  if (reloadLeft > 0) {
    reloadLeft -= dt
    if (reloadLeft <= 0) {
      // 换弹完成:从备弹里补满弹匣
      const need = rifle.magazine - mag
      const take = Math.min(need, reserve)
      mag += take
      reserve -= take
      reloadLeft = 0
    }
  }
  const sinceShot = gun.sinceShot + dt
  const recoil = sinceShot > 0.25 ? Math.max(0, gun.recoil - rifle.recover * dt) : gun.recoil
  return {
    mag,
    reserve,
    reloadLeft,
    cooldown: Math.max(0, gun.cooldown - dt),
    recoil,
    sinceShot,
  }
}

/** 当前散布(度):基础 + 后坐力 */
export function spreadOf(gun: GunState, rifle: Rifle = RIFLE): number {
  return Math.min(rifle.maxSpread, rifle.baseSpread + gun.recoil)
}

/** 在瞄准角上叠一个随机散布,返回 [新的角度, 新的随机数状态] */
export function aimWithSpread(angle: number, spreadDeg: number, rng: number): { angle: number; rng: number } {
  const [u, next] = rand(rng)
  const offset = (u * 2 - 1) * spreadDeg * DEG
  return { angle: angle + offset, rng: next }
}

// ---------------------------------------------------------------- 命中判定

export interface ShotTarget {
  id: number
  pos: Vec
  radius: number
}

export type ShotOutcome =
  | { kind: 'wall'; point: Vec; distance: number }
  | { kind: 'target'; id: number; point: Vec; distance: number }
  | { kind: 'air'; point: Vec; distance: number }

/**
 * 一发子弹:先算到墙的距离,再算每个目标圆,取更近的那个。
 * 「墙先还是人先」的判断就靠这一处,单测也直接测它。
 */
export function hitscan(
  map: GameMap, from: Vec, angle: number, targets: readonly ShotTarget[], range: number,
): ShotOutcome {
  const dir = { x: Math.cos(angle), y: Math.sin(angle) }
  const wall = wallDistance(map, from, dir, range)
  let bestId = -1
  let bestT = Infinity
  for (const target of targets) {
    const t = rayCircle(from, dir, target.pos, target.radius)
    if (t === null) continue
    // 起点就在圆里(贴脸)按 0.5 算,不然 t=0 会被当成「没走」漏掉
    const hitT = Math.max(t, 0.5)
    if (hitT > wall) continue
    if (hitT < bestT) {
      bestT = hitT
      bestId = target.id
    }
  }
  const distance = bestId >= 0 ? bestT : wall
  const point = { x: from.x + dir.x * distance, y: from.y + dir.y * distance }
  if (bestId >= 0) return { kind: 'target', id: bestId, point, distance }
  return wall < range ? { kind: 'wall', point, distance } : { kind: 'air', point, distance }
}

// ---------------------------------------------------------------- 难度

/**
 * 守卫的「人味参数」:三档难度只在这几处有差别 —— 反应时间、瞄准误差、转身速度、视距和移动速度。
 * 枪本身和玩家完全一样(同样的伤害、同样的弹匣、同样的射速),难度不偷偷加伤害/加血。
 */
export interface GuardSkill {
  id: Difficulty
  /** 看见玩家之后多久才开枪(秒) */
  reaction: number
  /** 瞄准误差(度),叠加在枪自己的散布上 */
  aimError: number
  /** 转身速度(弧度/秒) */
  turnSpeed: number
  /** 一次连射几发 */
  burst: number
  /** 两组连射之间停多久(秒) */
  pause: number
  /** 视距(世界单位) */
  viewRange: number
  /** 总视野角(弧度);贴脸 3 格内不受视野角限制 */
  fov: number
  /** 移动速度(世界单位/秒) */
  speed: number
}

export const SKILLS: Record<Difficulty, GuardSkill> = {
  // 休闲:反应慢、枪法松、看得近、走得慢,给第一次玩的人留出反应时间
  casual: {
    id: 'casual', reaction: 1.3, aimError: 9.5, turnSpeed: 3, burst: 2, pause: 1.8,
    viewRange: TILE * 8, fov: 1.9, speed: TILE * 2.5,
  },
  normal: {
    id: 'normal', reaction: 0.65, aimError: 5.6, turnSpeed: 4.5, burst: 3, pause: 1.15,
    viewRange: TILE * 12, fov: 2.3, speed: TILE * 3.2,
  },
  hard: {
    id: 'hard', reaction: 0.38, aimError: 3.0, turnSpeed: 7, burst: 4, pause: 0.8,
    viewRange: TILE * 16, fov: 2.7, speed: TILE * 3.8,
  },
}
