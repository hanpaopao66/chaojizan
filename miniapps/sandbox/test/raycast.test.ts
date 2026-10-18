// DDA 射线:已知的命中位置、命中面、法线、穿过水、距离上限、放置位置。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AIR, BEDROCK, SAND, STONE, WATER } from '../src/blocks'
import { placePosition, rayFromEye, raycast, lookDirection } from '../src/raycast'
import type { BlockSource } from '../src/world'

/** 用函数造一个假世界,测试就不用生成 78 万格的真世界 */
const source = (fn: (x: number, y: number, z: number) => number): BlockSource => ({ blockAt: fn })

/** 平地:y < 4 是石头,上面是空气 */
const flat = source((_x, y) => (y < 4 ? STONE : AIR))

test('竖直向下:命中方块顶面,距离和法线正确', () => {
  const hit = raycast(flat, 10.5, 10, 10.5, 0, -1, 0, 32)
  assert.ok(hit)
  assert.deepEqual([hit.x, hit.y, hit.z], [10, 3, 10])
  assert.deepEqual([hit.nx, hit.ny, hit.nz], [0, 1, 0])
  assert.equal(hit.face, 'y+')
  assert.equal(hit.block, STONE)
  assert.equal(hit.dist, 6)
  // 超出射程打不到
  assert.equal(raycast(flat, 10.5, 10, 10.5, 0, -1, 0, 5.9), null)
})

test('水平射线:命中侧面的法线朝外,距离正确', () => {
  // 在 x=15 立一堵墙(y=4..6)
  const world = source((x, y, z) => (x === 15 && y >= 4 && y <= 6 && z === 4 ? STONE : (y < 4 ? STONE : AIR)))
  const hit = raycast(world, 10.5, 4.5, 4.5, 1, 0, 0, 32)
  assert.ok(hit)
  assert.deepEqual([hit.x, hit.y, hit.z], [15, 4, 4])
  assert.deepEqual([hit.nx, hit.ny, hit.nz], [-1, 0, 0])
  assert.equal(hit.face, 'x-')
  assert.equal(hit.dist, 4.5)
  // 反向的射线看到的是另一面
  const back = raycast(world, 20.5, 4.5, 4.5, -1, 0, 0, 32)
  assert.ok(back)
  assert.deepEqual([back.x, back.ny, back.nz], [15, 0, 0])
  assert.equal(back.face, 'x+')
})

test('水不挡视线:准星穿过去点到水底的沙子', () => {
  // y=4..6 是水,y<4 是沙子
  const sea = source((_x, y) => (y < 4 ? SAND : y <= 6 ? WATER : AIR))
  const hit = raycast(sea, 8.5, 10, 8.5, 0, -1, 0, 32)
  assert.ok(hit)
  assert.deepEqual([hit.x, hit.y, hit.z], [8, 3, 8])
  assert.equal(hit.block, SAND)
  assert.equal(hit.dist, 6)
})

test('从眼睛里沿朝向打:yaw 0 朝 +x,pitch 控制上下', () => {
  const wall = source((x, y, z) => (x === 20 && y >= 4 && y <= 8 && z === 0 ? STONE : AIR))
  const eye = { x: 10.5, y: 5.5, z: 0.5 }
  const hit = rayFromEye(wall, eye.x, eye.y, eye.z, 0, 0, 16)
  assert.ok(hit)
  assert.deepEqual([hit.x, hit.y, hit.z], [20, 5, 0])
  // 抬头 45° 打向空中,什么都打不到
  assert.equal(rayFromEye(wall, eye.x, eye.y, eye.z, 0, Math.PI / 4, 16), null)
  // 朝下 45° 打到脚下地面
  const ground = source((_x, y) => (y < 4 ? STONE : AIR))
  const down = rayFromEye(ground, eye.x, eye.y, eye.z, 0, -Math.PI / 4, 16)
  assert.ok(down)
  assert.equal(down.y, 3)
  assert.equal(down.face, 'y+')
  // lookDirection 是单位向量
  const d = lookDirection(1.1, -0.4)
  assert.ok(Math.abs(Math.hypot(d.x, d.y, d.z) - 1) < 1e-9)
})

test('放置位置 = 命中格 + 法线,朝玩家这一侧', () => {
  const ground = source((_x, y) => (y < 4 ? STONE : AIR))
  const top = raycast(ground, 5.5, 10, 5.5, 0, -1, 0, 32)
  assert.ok(top)
  assert.deepEqual(placePosition(top), { x: 5, y: 4, z: 5 })
  const world = source((x, y, z) => (x === 15 && y === 4 && z === 4 ? STONE : AIR))
  const side = raycast(world, 10.5, 4.5, 4.5, 1, 0, 0, 32)
  assert.ok(side)
  assert.deepEqual(placePosition(side), { x: 14, y: 4, z: 4 })
  const bottom = raycast(world, 15.5, 8.5, 4.5, 0, -1, 0, 32)
  assert.ok(bottom)
  assert.deepEqual(placePosition(bottom), { x: 15, y: 5, z: 4 })
  // 基岩也会被射线挡住(不然能看穿世界底),但挖不动由方块表决定
  const bedrock = source((_x, y) => (y < 2 ? BEDROCK : AIR))
  assert.ok(raycast(bedrock, 1.5, 8, 1.5, 0, -1, 0, 32))
})

test('方向向量不归一化也能用;零向量不崩', () => {
  const hit = raycast(flat, 10.5, 10, 10.5, 0, -3.5, 0, 32)
  assert.ok(hit)
  assert.deepEqual([hit.y, hit.dist], [3, 6])
  assert.equal(raycast(flat, 0.5, 0.5, 0.5, 0, 0, 0, 5), null)
  assert.equal(raycast(flat, 0.5, 10, 0.5, 0, -1, 0, 0), null)
})
