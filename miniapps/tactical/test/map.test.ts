import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  COLS, CRATE, FLOOR, MAP_ROWS, ROWS, TILE, WALL, WORLD_H, WORLD_W, circleBlocked, lineOfSight, moveCircle,
  parseMap, rayCircle, siteAt, siteCenter, solidAt, tileAt, tileCenter, tileCol, tileRow, wallDistance,
} from '../src/map'

const map = parseMap()
const near = (a: number, b: number, eps = 0.001) => Math.abs(a - b) <= eps
const at = (col: number, row: number) => tileCenter(col, row)

test('地图解析:44×26、外圈是墙、出生点和两个炸弹点都在地上', () => {
  assert.equal(map.tiles.length, COLS * ROWS)
  assert.equal(COLS, 44)
  assert.equal(ROWS, 26)
  assert.equal(WORLD_W, 44 * TILE)
  assert.equal(WORLD_H, 26 * TILE)
  for (let col = 0; col < COLS; col++) {
    assert.equal(tileAt(map, col, 0), WALL, `上边界 ${col}`)
    assert.equal(tileAt(map, col, ROWS - 1), WALL, `下边界 ${col}`)
  }
  for (let row = 0; row < ROWS; row++) {
    assert.equal(tileAt(map, 0, row), WALL, `左边界 ${row}`)
    assert.equal(tileAt(map, COLS - 1, row), WALL, `右边界 ${row}`)
  }
  assert.equal(tileAt(map, tileCol(map.playerSpawn.x), tileRow(map.playerSpawn.y)), FLOOR)
  assert.equal(map.guardSpawns.length, 3)
  for (const spawn of map.guardSpawns) assert.equal(tileAt(map, tileCol(spawn.x), tileRow(spawn.y)), FLOOR)
  const a = siteCenter(map.siteA)
  const b = siteCenter(map.siteB)
  assert.equal(siteAt(map, a), 'A')
  assert.equal(siteAt(map, b), 'B')
  assert.equal(siteAt(map, map.playerSpawn), null)
  // 越界一律当墙
  assert.equal(tileAt(map, -1, 0), WALL)
  assert.equal(tileAt(map, COLS, 0), WALL)
})

test('地图解析会拒绝坏图(行数、字符、边界)', () => {
  assert.throws(() => parseMap(MAP_ROWS.slice(1)), /地图不合法/)
  const badChar = MAP_ROWS.slice()
  badChar[1] = '#' + '?'.repeat(COLS - 1) + '#'
  assert.throws(() => parseMap(badChar), /不认识的字符/)
  const short = MAP_ROWS.slice()
  short[1] = short[1].slice(0, 20)
  assert.throws(() => parseMap(short), /地图不合法/)
})

test('视线:墙会挡、门不挡', () => {
  // 第 2 行中间有一道竖墙,第 4 行有一道门(门开在 rows 4/5)
  assert.equal(lineOfSight(map, at(10, 2), at(13, 2)), false, '隔着墙看不见')
  assert.equal(lineOfSight(map, at(10, 4), at(13, 4)), true, '从门里看得见')
  assert.equal(lineOfSight(map, at(5, 13), at(8, 13)), true, '同一间房看得见')
  assert.equal(lineOfSight(map, at(5, 13), at(37, 4)), false, '横穿整张图看不见')
})

test('墙内不能站人:circleBlocked 和 moveCircle 的滑动', () => {
  assert.equal(circleBlocked(map, at(2, 2).x, at(2, 2).y, 8), false)
  assert.equal(circleBlocked(map, at(0, 0).x, at(0, 0).y, 8), true)
  assert.equal(circleBlocked(map, TILE * 11 + 1, at(2, 2).y, 8), true, '墙里')

  // 往右撞第 11 列的墙:停在墙边,不会穿过去
  const start = { x: 10 * TILE + 12, y: 2 * TILE + 12 }
  const blocked = moveCircle(map, start, 100, 0, 8)
  assert.ok(blocked.x < 11 * TILE - 8 + 0.01, `撞墙后位置 ${blocked.x}`)
  assert.ok(blocked.x >= start.x, '还是往右挪了一点')
  // 斜着撞墙:另一轴还能走(贴着墙滑)
  const slide = moveCircle(map, start, 60, 40, 8)
  assert.ok(slide.y > start.y + 5, `沿墙滑动了 ${slide.y - start.y}`)
  // 空地正常走
  const free = moveCircle(map, at(5, 13), 10, 5, 8)
  assert.ok(near(free.x, at(5, 13).x + 10) && near(free.y, at(5, 13).y + 5))
})

test('射线:DDA 到墙的距离、射线和圆', () => {
  const from = { x: 5 * TILE + 12, y: 3 * TILE + 12 }
  // 第 3 行左边这间房右边是第 11 列的墙
  assert.ok(near(wallDistance(map, from, { x: 1, y: 0 }, 500), 11 * TILE - from.x), '到墙距离')
  // 一行里没有墙:走到最大距离
  assert.equal(wallDistance(map, at(5, 13), { x: 0, y: 1 }, 10), 10)
  assert.equal(rayCircle({ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 100, y: 0 }, 10), 90)
  assert.equal(rayCircle({ x: 0, y: 0 }, { x: 0, y: 1 }, { x: 100, y: 0 }, 10), null)
  assert.equal(rayCircle({ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 5, y: 0 }, 10), 0, '起点在圆里')
})

test('炸弹点与地块:箱子挡人挡子弹', () => {
  assert.equal(tileAt(map, 3, 4), CRATE, '地图上有一个箱子')
  assert.equal(solidAt(map, 3, 4), true)
  assert.equal(solidAt(map, 2, 2), false)
  assert.equal(circleBlocked(map, at(3, 4).x, at(3, 4).y, 8), true)
})
