// 移动/物理:AABB 碰撞、滑动、跳跃高度、头顶碰撞、游泳、掉出世界。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AIR, STONE, WATER } from '../src/blocks'
import {
  MoveInput, PLAYER_HEIGHT, PLAYER_WIDTH, PlayerState, cameraEye, clampPitch, newPlayer, placePlayer,
  stepPlayer,
} from '../src/player'
import type { BlockSource } from '../src/world'

const source = (fn: (x: number, y: number, z: number) => number): BlockSource => ({ blockAt: fn })
/** 平地:y < 4 是石头,脚底应该停在 y=4 */
const flat = source((_x, y) => (y < 4 ? STONE : AIR))

const still: MoveInput = { forward: 0, strafe: 0, jump: false }
const walk: MoveInput = { forward: 1, strafe: 0, jump: false }

function run(p: PlayerState, world: BlockSource, input: MoveInput, frames: number): void {
  for (let i = 0; i < frames; i++) stepPlayer(world, p, input, 1 / 60)
}

test('重力:从空中落下停在方块顶面,落地事件只报一次', () => {
  const p = newPlayer(10.5, 8, 10.5, 0)
  let landed = 0
  for (let i = 0; i < 240; i++) if (stepPlayer(flat, p, still, 1 / 60).landed) landed++
  assert.equal(p.y, 4)
  assert.equal(p.vy, 0)
  assert.equal(p.onGround, true)
  assert.ok(landed >= 1 && landed <= 2, `落地事件 ${landed} 次`)
  // 站着不动不会掉下去
  run(p, flat, still, 120)
  assert.equal(p.y, 4)
})

test('往前走撞墙:停在墙面前,不穿进去;斜着走会贴着墙滑', () => {
  // x >= 20 立一堵墙(从地面到 y=6)
  const wall = source((x, y) => (y < 4 || (x >= 20 && y < 7) ? STONE : AIR))
  const p = newPlayer(10.5, 4, 10.5, 0)
  run(p, wall, walk, 240)
  assert.ok(Math.abs(p.x - (20 - PLAYER_WIDTH / 2)) < 1e-3, `x=${p.x}`)
  assert.ok(p.x < 20)
  // 45° 斜着走:贴住墙后 z 继续增加
  const q = newPlayer(10.5, 4, 10.5, 0)
  const diagonal: MoveInput = { forward: 1, strafe: 1, jump: false }
  run(q, wall, diagonal, 480)
  assert.ok(Math.abs(q.x - (20 - PLAYER_WIDTH / 2)) < 1e-3, `x=${q.x}`)
  const z0 = q.z
  run(q, wall, diagonal, 120)
  assert.ok(q.z > z0 + 1, `贴着墙应该继续滑:z=${q.z}`)
})

test('自动上一层台阶:一格能走上去,两格照旧挡住', () => {
  // 平地 y<4,台阶在 x>=12 高一层(实心 y=4)
  const one = source((x, y) => (y < 4 || (x >= 12 && y === 4) ? STONE : AIR))
  const p = newPlayer(10.5, 4, 10.5, 0)
  run(p, one, walk, 60)
  assert.ok(p.x > 12.4, `一格台阶没走上去:x=${p.x}`)
  assert.equal(p.y, 5, `应该站在台阶上:y=${p.y}`)
  // 两格高的墙:抬起来会卡头,不能自动上去
  const two = source((x, y) => (y < 4 || (x >= 12 && y <= 5) ? STONE : AIR))
  const q = newPlayer(10.5, 4, 10.5, 0)
  run(q, two, walk, 120)
  assert.ok(q.x < 12 - 0.29, `两格墙应该挡住:x=${q.x}`)
  assert.equal(q.y, 4)
})

test('跳跃:跳起超过一格,落回原高度', () => {
  const p = newPlayer(10.5, 4, 10.5, 0)
  run(p, flat, still, 10)
  assert.equal(p.onGround, true)
  assert.equal(stepPlayer(flat, p, { ...still, jump: true, jumpPressed: true }, 1 / 60).jumped, true)
  let peak = p.y
  for (let i = 0; i < 120; i++) {
    stepPlayer(flat, p, still, 1 / 60)
    peak = Math.max(peak, p.y)
  }
  assert.ok(peak - 4 > 1.15, `跳得太低:${peak}`)
  assert.ok(peak - 4 < 1.5, `跳得太高:${peak}`)
  assert.equal(p.y, 4)
})

test('头顶有方块:跳起来会被挡住,不会穿模', () => {
  // 脚底 y=4,头顶 5.8;天花板在 y=6
  const ceiling = source((_x, y) => (y < 4 || y === 6 ? STONE : AIR))
  const p = newPlayer(10.5, 4, 10.5, 0)
  stepPlayer(ceiling, p, still, 1 / 60)
  stepPlayer(ceiling, p, { ...still, jump: true, jumpPressed: true }, 1 / 60)
  for (let i = 0; i < 60; i++) stepPlayer(ceiling, p, { ...still, jump: true }, 1 / 60)
  assert.ok(p.y + PLAYER_HEIGHT <= 6 + 1e-3, `头顶穿进天花板:y=${p.y}`)
  assert.ok(p.y >= 4 - 1e-3)
})

test('游泳:水里下落变慢,按跳会往上浮', () => {
  // y<4 石头,4..12 水,12 以上空气
  const sea = source((_x, y) => (y < 4 ? STONE : y <= 12 ? WATER : AIR))
  const p = newPlayer(10.5, 10, 10.5, 0)
  stepPlayer(sea, p, still, 1 / 60)
  assert.equal(p.inWater, true)
  const sinkStart = p.y
  run(p, sea, still, 30)
  assert.ok(sinkStart - p.y < 1.2, `水里沉太快:${sinkStart - p.y}`)
  const before = p.y
  run(p, sea, { ...still, jump: true }, 60)
  assert.ok(p.y > before - 0.1, '按跳应该往上浮')
  // 不按跳时会慢慢沉到底(石头顶面 y=4)
  run(p, sea, still, 600)
  assert.ok(Math.abs(p.y - 4) < 0.1, `没沉到底:${p.y}`)
})

test('掉出世界:很低的时候返回 fellOut,让界面把玩家送回出生点', () => {
  const voidWorld = source(() => AIR)
  const p = newPlayer(10.5, 0, 10.5, 0)
  let fell = false
  for (let i = 0; i < 300 && !fell; i++) fell = stepPlayer(voidWorld, p, still, 1 / 60).fellOut
  assert.equal(fell, true)
  assert.ok(p.y <= -6)
})

test('放回地面:卡在方块里会被抬到空位;俯仰有上限;眼睛高度对', () => {
  const p = newPlayer(10.5, 4.5, 10.5, 0)
  placePlayer(flat, p, 10.5, 3.5, 10.5)
  assert.ok(p.y >= 4 - 1e-6, `被埋住了:${p.y}`)
  // 放进实心地面(y=3.5 在石头里)会抬到地面以上
  const q = newPlayer(0.5, 4, 0.5, 0)
  placePlayer(flat, q, 5.5, 1, 5.5)
  assert.ok(q.y >= 4 - 1e-6)
  assert.equal(clampPitch(3), 1.3)
  assert.equal(clampPitch(-3), -1.3)
  assert.equal(clampPitch(0.3), 0.3)
  q.pitch = 0
  assert.equal(cameraEye(q).y, q.y + 1.62)
})

test('土狼时间:刚走下落差 0.1 秒内还能跳', () => {
  // x < 6 有地面(y<4),x >= 6 是空的
  const ledge = source((x, y) => (y < 4 && x < 6 ? STONE : AIR))
  const p = newPlayer(5.2, 4, 0.5, 0)
  let jumped = false
  // 先走两步站稳
  for (let i = 0; i < 10; i++) stepPlayer(ledge, p, walk, 1 / 60)
  // 走到边缘外
  let guard = 0
  while (p.x < 6.45 && guard++ < 120) stepPlayer(ledge, p, walk, 1 / 60)
  assert.ok(p.x >= 6.45 && !p.onGround, `应该已经走出去了:x=${p.x}`)
  jumped = stepPlayer(ledge, p, { ...still, jump: true, jumpPressed: true }, 1 / 60).jumped
  assert.equal(jumped, true, '离开地面后 0.1 秒内应该还能跳')
  // 超过宽限时间再按就没用了
  const q = newPlayer(5.2, 4, 0.5, 0)
  for (let i = 0; i < 10; i++) stepPlayer(ledge, q, walk, 1 / 60)
  guard = 0
  while (q.x < 6.45 && guard++ < 120) stepPlayer(ledge, q, walk, 1 / 60)
  for (let i = 0; i < 12; i++) stepPlayer(ledge, q, still, 1 / 60) // 掉 0.2 秒
  assert.equal(q.onGround, false)
  assert.equal(stepPlayer(ledge, q, { ...still, jump: true, jumpPressed: true }, 1 / 60).jumped, false)
})

test('跳跃缓冲:落地前 0.1 秒内按跳,落地马上起跳', () => {
  const p = newPlayer(10.5, 8, 10.5, 0)
  let guard = 0
  while (p.y > 4.5 && guard++ < 300) stepPlayer(flat, p, still, 1 / 60)
  assert.ok(!p.onGround && p.y > 4, `还在空中:y=${p.y}`)
  // 落地前按下跳
  assert.equal(stepPlayer(flat, p, { ...still, jump: true, jumpPressed: true }, 1 / 60).jumped, false)
  let landedThenJumped = false
  for (let i = 0; i < 20; i++) {
    const r = stepPlayer(flat, p, still, 1 / 60)
    if (r.jumped) landedThenJumped = true
    if (landedThenJumped) break
  }
  assert.equal(landedThenJumped, true, '缓冲的跳应该在落地后生效')
  assert.ok(p.y > 4.1)
})

test('移动距离与帧率无关:30fps 和 144fps 走一秒差不多远', () => {
  const runFps = (fps: number): number => {
    const p = newPlayer(10.5, 4, 10.5, 0)
    const frames = Math.round(fps)
    for (let i = 0; i < frames; i++) stepPlayer(flat, p, walk, 1 / fps)
    return p.x - 10.5
  }
  const slow = runFps(30)
  const fast = runFps(144)
  assert.ok(slow > 2 && fast > 2)
  assert.ok(Math.abs(slow - fast) / Math.max(slow, fast) < 0.05, `30fps ${slow.toFixed(2)} vs 144fps ${fast.toFixed(2)}`)
})
