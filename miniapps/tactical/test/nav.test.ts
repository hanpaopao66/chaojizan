import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Vec, parseMap, tileCenter } from '../src/map'
import {
  NavGrid, aStarPath, bfsPath, gridIndex, manhattan, navFromMap, nearestWalkable, pathPoints, routeBetween,
  stepsBetween, walkableNear,
} from '../src/nav'

/** 手写的小网格:'.' 能走,'#' 不能走 */
function grid(rows: string[]): NavGrid {
  return {
    cols: rows[0].length,
    rows: rows.length,
    walkable: (col, row) => row >= 0 && row < rows.length && col >= 0 && col < rows[0].length && rows[row][col] === '.',
  }
}

const OPEN = grid([
  '.....',
  '.....',
  '.....',
  '.....',
  '.....',
])

test('BFS / A*:空地上最短路一样长,而且真的最短', () => {
  const start = gridIndex(OPEN, 0, 0)
  const goal = gridIndex(OPEN, 4, 4)
  const bfs = bfsPath(OPEN, start, goal)
  const astar = aStarPath(OPEN, start, goal)
  assert.ok(bfs)
  assert.ok(astar)
  assert.equal(bfs.length, 9, '0,0 → 4,4 是 8 步 9 个点')
  assert.equal(astar.length, bfs.length, 'A* 和 BFS 一样长')
  assert.equal(bfs[0], start)
  assert.equal(bfs[bfs.length - 1], goal)
  // 每一步都是相邻格
  for (let i = 1; i < astar.length; i++) assert.equal(manhattan(OPEN, astar[i - 1], astar[i]), 1)
  assert.deepEqual(bfsPath(OPEN, start, start), [start])
})

test('走不通:一堵墙把网格分成两半', () => {
  const split = grid([
    '..#..',
    '..#..',
    '..#..',
  ])
  assert.equal(bfsPath(split, gridIndex(split, 0, 0), gridIndex(split, 4, 0)), null)
  assert.equal(aStarPath(split, gridIndex(split, 0, 0), gridIndex(split, 4, 0)), null)
})

test('目标在墙里:先找最近能站的一格', () => {
  const split = grid([
    '..#..',
    '..#..',
    '..#..',
  ])
  const near = nearestWalkable(split, 2, 1)
  assert.ok(near >= 0)
  const col = near % split.cols
  assert.ok(col < 2 || col > 2, `落在第 ${col} 列,不是墙`)
  assert.equal(nearestWalkable(grid(['###', '###', '###']), 1, 1), -1, '周围全是墙返回 -1')
})

test('整张地图:玩家出生点到 A 点、B 点和三个守卫出生点都走得通', () => {
  const map = parseMap()
  const nav = navFromMap(map)
  const start = walkableNear(nav, map.playerSpawn)
  assert.ok(start >= 0)
  const targets = [tileCenter(37, 4), tileCenter(37, 20), ...map.guardSpawns]
  for (const target of targets) {
    const goal = walkableNear(nav, target)
    const path = bfsPath(nav, start, goal)
    assert.ok(path, `走不到 ${JSON.stringify(target)}`)
    assert.ok(path.length > 10)
  }
})

test('整张地图:routeBetween 的每一步都落在能走的格子里', () => {
  const map = parseMap()
  const nav = navFromMap(map)
  const path = routeBetween(nav, map.playerSpawn, tileCenter(37, 4))
  assert.ok(path.length > 10)
  // 起点在玩家脚下附近,终点在 A 点附近
  assert.ok(Math.hypot(path[0].x - map.playerSpawn.x, path[0].y - map.playerSpawn.y) < 24 * 2)
  for (const point of path) {
    const col = Math.floor(point.x / 24)
    const row = Math.floor(point.y / 24)
    assert.equal(nav.walkable(col, row), true, `路径点 ${col},${row} 不能走`)
  }
  assert.equal(stepsBetween(nav, map.playerSpawn, tileCenter(37, 4)), path.length - 1, 'A* 结果和 BFS 步数一致')
})

test('路径点:pathPoints 把格子下标转成格中心', () => {
  const path = pathPoints(OPEN, [0, 1, 2])
  const first: Vec = path[0]
  const expected = tileCenter(0, 0)
  assert.ok(Math.abs(first.x - expected.x) < 1e-9 && Math.abs(first.y - expected.y) < 1e-9)
  assert.equal(path.length, 3)
})
