// 网格寻路:守卫在地图里追人、去调查枪声、跑去拆弹都靠它。
//
// 4 邻接、每步代价一样,所以 BFS 就是最短路;A*(曼哈顿启发)只少绕点路,结果和 BFS 一样长。
// 两个都留着:BFS 用来做「够不够得着」的判定,A* 拿来跑每帧真正要走的路径。
// 界面无关,测试里可以塞一张手写的小网格进去。

import { COLS, ROWS, GameMap, Vec, inBounds, solidAt, tileCenter, tileCol, tileRow } from './map'

export interface NavGrid {
  cols: number
  rows: number
  /** 这一格能不能站人 */
  walkable(col: number, row: number): boolean
}

/** 地图 → 寻路网格(墙和箱子都不能走) */
export function navFromMap(map: GameMap): NavGrid {
  return {
    cols: COLS,
    rows: ROWS,
    walkable: (col, row) => inBounds(col, row) && !solidAt(map, col, row),
  }
}

export function gridIndex(grid: NavGrid, col: number, row: number): number {
  return row * grid.cols + col
}

export function gridCoords(grid: NavGrid, index: number): { col: number; row: number } {
  return { col: index % grid.cols, row: Math.floor(index / grid.cols) }
}

export function manhattan(grid: NavGrid, a: number, b: number): number {
  const ca = gridCoords(grid, a)
  const cb = gridCoords(grid, b)
  return Math.abs(ca.col - cb.col) + Math.abs(ca.row - cb.row)
}

const NEIGHBORS: ReadonlyArray<readonly [number, number]> = [
  [1, 0], [-1, 0], [0, 1], [0, -1],
]

/**
 * 找离目标格最近的一个能站的格子(目标可能是一堵墙、一个刚好在箱子里的坐标)。
 * 自己往外一圈圈找,半径有上限,免得整张图都走不通时白转。
 */
export function nearestWalkable(grid: NavGrid, col: number, row: number, maxRings = 6): number {
  if (grid.walkable(col, row)) return gridIndex(grid, col, row)
  for (let ring = 1; ring <= maxRings; ring++) {
    for (let dr = -ring; dr <= ring; dr++) {
      for (let dc = -ring; dc <= ring; dc++) {
        // 只看这一圈的边
        if (Math.max(Math.abs(dr), Math.abs(dc)) !== ring) continue
        const c = col + dc
        const r = row + dr
        if (inBounds(c, r) && grid.walkable(c, r)) return gridIndex(grid, c, r)
      }
    }
  }
  return -1
}

/** 世界坐标 → 最近的能走格子下标 */
export function walkableNear(grid: NavGrid, pos: Vec): number {
  return nearestWalkable(grid, tileCol(pos.x), tileRow(pos.y))
}

/** 广度优先:找最短路(步数最少)。找到返回含起终点的格子下标数组,走不通返回 null */
export function bfsPath(grid: NavGrid, start: number, goal: number): number[] | null {
  if (start === goal) return [start]
  const size = grid.cols * grid.rows
  if (start < 0 || goal < 0 || start >= size || goal >= size) return null
  const from = new Int32Array(size).fill(-1)
  const seen = new Uint8Array(size)
  seen[start] = 1
  const queue = [start]
  let head = 0
  while (head < queue.length) {
    const cur = queue[head++]
    if (cur === goal) return rebuild(from, start, goal)
    const col = cur % grid.cols
    const row = Math.floor(cur / grid.cols)
    for (const [dc, dr] of NEIGHBORS) {
      const c = col + dc
      const r = row + dr
      if (!inBounds(c, r) || !grid.walkable(c, r)) continue
      const next = r * grid.cols + c
      if (seen[next]) continue
      seen[next] = 1
      from[next] = cur
      queue.push(next)
    }
  }
  return null
}

/**
 * A*:4 邻接 + 曼哈顿距离,和 BFS 走出一样短的路径,但朝目标那边先试,扩展的格子少。
 * 开表很小(44×26),线性找最小就够了,不值得上堆。
 */
export function aStarPath(grid: NavGrid, start: number, goal: number): number[] | null {
  if (start === goal) return [start]
  const size = grid.cols * grid.rows
  if (start < 0 || goal < 0 || start >= size || goal >= size) return null
  if (!grid.walkable(goal % grid.cols, Math.floor(goal / grid.cols))) return null
  const from = new Int32Array(size).fill(-1)
  const gScore = new Float64Array(size).fill(Infinity)
  const closed = new Uint8Array(size)
  gScore[start] = 0
  const open = [start]
  while (open.length) {
    let best = 0
    let bestF = Infinity
    for (let i = 0; i < open.length; i++) {
      const f = gScore[open[i]] + manhattan(grid, open[i], goal)
      if (f < bestF) {
        bestF = f
        best = i
      }
    }
    const cur = open.splice(best, 1)[0]
    if (cur === goal) return rebuild(from, start, goal)
    if (closed[cur]) continue
    closed[cur] = 1
    const col = cur % grid.cols
    const row = Math.floor(cur / grid.cols)
    for (const [dc, dr] of NEIGHBORS) {
      const c = col + dc
      const r = row + dr
      if (!inBounds(c, r) || !grid.walkable(c, r)) continue
      const next = r * grid.cols + c
      if (closed[next]) continue
      const tentative = gScore[cur] + 1
      if (tentative < gScore[next]) {
        gScore[next] = tentative
        from[next] = cur
        open.push(next)
      }
    }
  }
  return null
}

function rebuild(from: Int32Array, start: number, goal: number): number[] {
  const path = [goal]
  let cur = goal
  while (cur !== start) {
    cur = from[cur]
    if (cur < 0) return [start, goal] // 不该发生:防御性兜底
    path.push(cur)
  }
  return path.reverse()
}

/** 把格子路径变成一格一格中心点的世界坐标路径 */
export function pathPoints(grid: NavGrid, path: readonly number[]): Vec[] {
  return path.map((i) => {
    const { col, row } = gridCoords(grid, i)
    return tileCenter(col, row)
  })
}

/**
 * 从 from 走到 to 的一条世界坐标路径(含起点、终点格中心)。
 * 走不通或者两头都在实心格子里找不到落脚点时返回空数组。
 */
export function routeBetween(grid: NavGrid, from: Vec, to: Vec): Vec[] {
  const start = walkableNear(grid, from)
  const goal = walkableNear(grid, to)
  if (start < 0 || goal < 0) return []
  const path = aStarPath(grid, start, goal)
  return path ? pathPoints(grid, path) : []
}

/** 两格之间的步数;同一格是 0 */
export function stepsBetween(grid: NavGrid, from: Vec, to: Vec): number {
  const start = walkableNear(grid, from)
  const goal = walkableNear(grid, to)
  if (start < 0 || goal < 0) return Infinity
  const path = bfsPath(grid, start, goal)
  return path ? path.length - 1 : Infinity
}

/** 两个世界坐标所在格子的中心距离(格数),给 AI 判「到没到」用 */
export function tileGap(a: Vec, b: Vec): number {
  return Math.abs(tileCol(a.x) - tileCol(b.x)) + Math.abs(tileRow(a.y) - tileRow(b.y))
}

/** 沿路径往前看,走到第几个点;给移动逻辑用,不依赖界面 */
export function nextWaypoint(path: readonly Vec[], from: Vec, radius: number): number {
  for (let i = 0; i < path.length; i++) {
    if (Math.hypot(path[i].x - from.x, path[i].y - from.y) > radius) return i
  }
  return path.length - 1
}
