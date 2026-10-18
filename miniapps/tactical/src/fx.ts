// 画面上的「瞬时效果」:曳光、枪口火光、火花、烟。只是纯数据,渲染层照着画,不参与任何判定。
//
// 和 match.ts 分开是因为这部分只让画面好看,规则测试不需要关心它;match.ts 里只要调 addTracer / addSpark。

import { Vec } from './map'
import { rand } from '../../shared/src/rand'

export type Side = 'player' | 'guard'
export type FxKind = 'flash' | 'spark' | 'smoke' | 'shell'

export interface Fx {
  pos: Vec
  vel: Vec
  life: number
  max: number
  kind: FxKind
  team: Side
  angle: number
}

export interface Tracer { from: Vec; to: Vec; team: Side; life: number; max: number }

/** 特效和随机数的「容器」:Round 结构上满足它,测试里也可以塞一个小的 */
export interface FxWorld {
  tracers: Tracer[]
  fx: Fx[]
  rng: number
}

/** 枪口在身体前方多远 */
const MUZZLE = 15

function gunTip(pos: Vec, angle: number): Vec {
  return { x: pos.x + Math.cos(angle) * MUZZLE, y: pos.y + Math.sin(angle) * MUZZLE }
}

/** 一发子弹的曳光线,0.09 秒消散 */
export function addTracer(world: FxWorld, from: Vec, to: Vec, team: Side): void {
  world.tracers.push({ from: { ...from }, to: { ...to }, team, life: 0.09, max: 0.09 })
}

/** 枪口火光 + 两缕烟 */
export function addFlash(world: FxWorld, pos: Vec, angle: number, team: Side): void {
  world.fx.push({ pos: gunTip(pos, angle), vel: { x: 0, y: 0 }, life: 0.06, max: 0.06, kind: 'flash', team, angle })
  for (let i = 0; i < 2; i++) {
    const [u, next] = rand(world.rng)
    world.rng = next
    const a = angle + (u - 0.5) * 0.8
    world.fx.push({
      pos: gunTip(pos, angle),
      vel: { x: Math.cos(a) * 22, y: Math.sin(a) * 22 },
      life: 0.3 + u * 0.2,
      max: 0.5,
      kind: 'smoke',
      team,
      angle,
    })
  }
}

/** 抛壳:向枪的侧后方弹出的小弹壳,落地前带一点旋转位移 */
export function addShell(world: FxWorld, pos: Vec, angle: number, team: Side): void {
  const [u, next] = rand(world.rng)
  world.rng = next
  const side = u > 0.5 ? 1 : -1
  const a = angle + side * (Math.PI / 2) - 0.35
  const speed = 60 + u * 50
  world.fx.push({
    pos: { x: pos.x + Math.cos(angle) * 10, y: pos.y + Math.sin(angle) * 10 },
    vel: { x: Math.cos(a) * speed, y: Math.sin(a) * speed },
    life: 0.55 + u * 0.25,
    max: 0.8,
    kind: 'shell',
    team,
    angle: a,
  })
}

/** 命中/撞墙的小火花:几颗小点朝四周溅开 */
export function addSpark(world: FxWorld, pos: Vec, kind: FxKind): void {
  const count = kind === 'smoke' ? 3 : 4
  for (let i = 0; i < count; i++) {
    const [u, next] = rand(world.rng)
    world.rng = next
    const [v, next2] = rand(world.rng)
    world.rng = next2
    const a = u * Math.PI * 2
    const speed = 40 + v * 110
    world.fx.push({
      pos: { ...pos },
      vel: { x: Math.cos(a) * speed, y: Math.sin(a) * speed },
      life: kind === 'smoke' ? 0.5 + v * 0.4 : 0.18 + v * 0.18,
      max: kind === 'smoke' ? 0.9 : 0.36,
      kind,
      team: 'player',
      angle: a,
    })
  }
}

/** 炸弹爆炸:一圈更多更快的火花 */
export function burstFx(world: FxWorld, pos: Vec, kind: FxKind, count: number, team: Side): void {
  for (let i = 0; i < count; i++) {
    const [u, next] = rand(world.rng)
    world.rng = next
    const [v, next2] = rand(world.rng)
    world.rng = next2
    const a = u * Math.PI * 2
    const speed = 40 + v * 260
    world.fx.push({
      pos: { ...pos },
      vel: { x: Math.cos(a) * speed, y: Math.sin(a) * speed },
      life: 0.4 + v * 0.6,
      max: 1,
      kind,
      team,
      angle: a,
    })
  }
}

/** 每帧推进:寿命减、位置按速度走、速度衰减;过期的删掉 */
export function decayFx(world: FxWorld, dt: number): void {
  for (const t of world.tracers) t.life -= dt
  world.tracers = world.tracers.filter((t) => t.life > 0)
  for (const f of world.fx) {
    f.life -= dt
    f.pos = { x: f.pos.x + f.vel.x * dt, y: f.pos.y + f.vel.y * dt }
    f.vel = { x: f.vel.x * (1 - dt * 3), y: f.vel.y * (1 - dt * 3) }
  }
  world.fx = world.fx.filter((f) => f.life > 0)
}
