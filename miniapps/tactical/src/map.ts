// 突击时刻的地图与物理:44×26 的 ASCII 关卡、格子碰撞、视线与射线。
//
// 这个文件不碰 DOM,也不认识「回合」「界面」—— 地图解析、圆和方块的碰撞、子弹先撞墙还是先撞人,
// 全都是纯函数,可以直接在 node:test 里跑。地图变丑了、出生点被墙堵了,单测会先炸。

export interface Vec { x: number; y: number }

export const COLS = 44
export const ROWS = 26
/** 一格的世界尺寸。整张地图一屏放下,44×26 格 ≈ 1056×624 世界单位 */
export const TILE = 24
export const WORLD_W = COLS * TILE
export const WORLD_H = ROWS * TILE

/** 格子类型:地面 / 墙 / 箱子(掩体,挡人也挡子弹) */
export const FLOOR = 0
export const WALL = 1
export const CRATE = 2

export type Site = 'A' | 'B'

/** 炸弹点区域(格子坐标,两端都含) */
export interface TileRect { x0: number; y0: number; x1: number; y1: number }

/** 地图 id。仓库是第一张,夜市是 1.1 加的第二章 */
export type MapId = 'warehouse' | 'market'

/** 地图主题,决定 canvas 配色和地面/摊位画法 */
export type MapTheme = 'warehouse' | 'market'

export interface MapDef {
  readonly id: MapId
  readonly name: string
  /** 一句话介绍,首页选图用 */
  readonly tagline: string
  readonly theme: MapTheme
  /** ASCII 图:# 外墙/内墙、c 箱子/摊位、A/B 炸弹点、P 玩家出生点、G 守卫出生点、. 地面 */
  readonly rows: readonly string[]
  readonly siteA: TileRect
  readonly siteB: TileRect
}

export interface GameMap {
  readonly id: MapId
  readonly name: string
  readonly theme: MapTheme
  /** COLS×ROWS 的格子类型,行优先 */
  readonly tiles: Uint8Array
  readonly siteA: TileRect
  readonly siteB: TileRect
  readonly playerSpawn: Vec
  readonly guardSpawns: readonly Vec[]
}

// 第一张图「旧仓库」:左边进攻方出生区(三条竖走廊各有上/中/下三道门),中间三间房,
// 右边一整条长厅,A 点在北头、B 点在南头。三条路都能绕到,没有死路。
const WAREHOUSE_ROWS: readonly string[] = [
  '############################################',
  '#..........#...................#...........#',
  '#..........#.............c.....#..AAAAAAAc.#',
  '#..........#...c...............#..AAAAAAA..#',
  '#..c..............................AAAGAAA..#',
  '#.................................AAAAAAA..#',
  '#..........#........c..........#..AAAAAAA..#',
  '#..........#................c..#.cAAAAAAA..#',
  '#..........#...................#...........#',
  '#.......c..#######...###########...........#',
  '#..........#.................c.#...........#',
  '#..........#..c.......c........#..c........#',
  '#........................G.................#',
  '#....P.....................c.......c.......#',
  '#..........#.....c.............#.......c...#',
  '#.......c..#...................#...........#',
  '#..........#######...###########...........#',
  '#..........#...................#.c.........#',
  '#..........#.........c.........#..BBBBBBB..#',
  '#...c......#...................#..BBBBBBB..#',
  '#.................................BBBGBBB..#',
  '#..............c..................BBBBBBB..#',
  '#..........#...............c...#..BBBBBBB..#',
  '#..........#...................#.........c.#',
  '#..........................................#',
  '############################################',
]

// 第二张图「霓虹夜市」:北边是 A/B 两间夜市档口(中间隔着仓库),南边是主街 + 两排摊位,
// 出生点在西南角的巷口。和旧仓库反过来:南北对称改成东西开口,掩体更密、巷战更多。
const MARKET_ROWS: readonly string[] = [
  '############################################',
  '#...........#...................#..........#',
  '#.cAAAAAAA..#.c...............c.#cBBBBBBBc.#',
  '#..AAAAAAA..#.........c.........#.BBBBBBB..#',
  '#..AAAGAAA..#...................#.BBBGBBB..#',
  '#..AAAAAAA..#.....c.............#.BBBBBBB..#',
  '#..AAAAAAAc.#.............c.....#.BBBBBBBc.#',
  '#...........#...................#..........#',
  '######..############....############..######',
  '#..........................................#',
  '#..........c........c.......c............c.#',
  '#..c............c.......c........c.........#',
  '#......c.............................c.....#',
  '#.....................G....................#',
  '#....c........c....c......c...c....c.......#',
  '#........c...#######..#########........c...#',
  '#...........#..................#...........#',
  '#...........#..................#...........#',
  '#...c.......#c.......c.......c.#......c....#',
  '#.......c........c.......c........c........#',
  '#..........................................#',
  '#...P.......#..................#...........#',
  '#.....c.....#..c.......c.......#c.......c..#',
  '#..........c#......c.......c...#....c......#',
  '#..........................................#',
  '############################################',
]

const WAREHOUSE_SITE_A: TileRect = { x0: 34, y0: 2, x1: 40, y1: 7 }
const WAREHOUSE_SITE_B: TileRect = { x0: 34, y0: 18, x1: 40, y1: 22 }
const MARKET_SITE_A: TileRect = { x0: 3, y0: 2, x1: 9, y1: 6 }
const MARKET_SITE_B: TileRect = { x0: 34, y0: 2, x1: 40, y1: 6 }

export const MAPS: readonly MapDef[] = [
  {
    id: 'warehouse',
    name: '旧仓库',
    tagline: '三路长厅 · 南北双点 · 适合正面推进',
    theme: 'warehouse',
    rows: WAREHOUSE_ROWS,
    siteA: WAREHOUSE_SITE_A,
    siteB: WAREHOUSE_SITE_B,
  },
  {
    id: 'market',
    name: '霓虹夜市',
    tagline: '南北对开 · 摊位密布 · 适合巷战绕后',
    theme: 'market',
    rows: MARKET_ROWS,
    siteA: MARKET_SITE_A,
    siteB: MARKET_SITE_B,
  },
]

export const MAP_IDS: readonly MapId[] = MAPS.map((m) => m.id)
export const DEFAULT_MAP_ID: MapId = 'warehouse'

export function mapById(id: MapId): MapDef {
  return MAPS.find((m) => m.id === id) ?? MAPS[0]
}

/** 兼容旧代码/测试:第一张图的 ASCII */
export const MAP_ROWS: readonly string[] = WAREHOUSE_ROWS

/** 世界坐标 → 格子下标(向下取整;越界坐标也会给出越界的下标,查格子时统一按墙算) */
export function tileCol(x: number): number { return Math.floor(x / TILE) }
export function tileRow(y: number): number { return Math.floor(y / TILE) }

export function tileIndex(col: number, row: number): number { return row * COLS + col }

/** 格子中心点的世界坐标 */
export function tileCenter(col: number, row: number): Vec {
  return { x: (col + 0.5) * TILE, y: (row + 0.5) * TILE }
}

export function inBounds(col: number, row: number): boolean {
  return col >= 0 && col < COLS && row >= 0 && row < ROWS
}

// ---------------------------------------------------------------- 解析

/**
 * 把 ASCII 地图解析成格子网格和关键点。图长什么样就是什么样,格式不对直接抛错 ——
 * 与其上线后「人卡在墙里」,不如单测里就红。可达性由 nav.ts 的寻路单测负责(这里不引寻路,免得循环依赖)。
 */
export function parseMap(def: MapDef = MAPS[0]): GameMap {
  const rows = def.rows
  const problems: string[] = []
  if (rows.length !== ROWS) problems.push(`地图应有 ${ROWS} 行,实际 ${rows.length} 行`)

  const tiles = new Uint8Array(COLS * ROWS)
  let playerSpawn: Vec | null = null
  const guardSpawns: Vec[] = []

  for (let row = 0; row < ROWS; row++) {
    const line = rows[row] ?? ''
    if (line.length !== COLS) problems.push(`第 ${row + 1} 行应有 ${COLS} 格,实际 ${line.length} 格`)
    for (let col = 0; col < COLS; col++) {
      const ch = line[col] ?? ' '
      let type = FLOOR
      switch (ch) {
        case '#': type = WALL; break
        case 'c': type = CRATE; break
        case '.': case 'A': case 'B': type = FLOOR; break
        case 'P': playerSpawn = tileCenter(col, row); break
        case 'G': guardSpawns.push(tileCenter(col, row)); break
        default: problems.push(`第 ${row + 1} 行第 ${col + 1} 格是不认识的字符「${ch}」`)
      }
      tiles[tileIndex(col, row)] = type
    }
  }

  // 外圈必须是墙,不然玩家能走出地图
  for (let col = 0; col < COLS; col++) {
    if (tiles[tileIndex(col, 0)] !== WALL) problems.push('地图上边界不是墙')
    if (tiles[tileIndex(col, ROWS - 1)] !== WALL) problems.push('地图下边界不是墙')
  }
  for (let row = 0; row < ROWS; row++) {
    if (tiles[tileIndex(0, row)] !== WALL) problems.push(`地图左边界第 ${row + 1} 行不是墙`)
    if (tiles[tileIndex(COLS - 1, row)] !== WALL) problems.push(`地图右边界第 ${row + 1} 行不是墙`)
  }

  if (!playerSpawn) problems.push('地图里没有玩家出生点 P(出生点必须落在地面上)')
  if (guardSpawns.length !== 3) problems.push(`地图里应有 3 个守卫出生点 G,实际 ${guardSpawns.length} 个`)

  for (const [name, rect] of [['A', def.siteA], ['B', def.siteB]] as Array<[string, TileRect]>) {
    if (rect.x0 < 0 || rect.y0 < 0 || rect.x1 >= COLS || rect.y1 >= ROWS) problems.push(`${name} 点区域越界`)
    if (siteTileCount(tiles, rect) < 10) problems.push(`${name} 点区域太小或者被墙占满`)
  }
  // A/B 必须真的在 ASCII 图里标出来,免得改了图忘了改区域
  for (const [name, rect] of [['A', def.siteA], ['B', def.siteB]] as Array<[string, TileRect]>) {
    let marked = 0
    for (let row = rect.y0; row <= rect.y1; row++) {
      for (let col = rect.x0; col <= rect.x1; col++) {
        const ch = rows[row]?.[col] ?? ' '
        if (ch === name || ch === 'G') marked++
      }
    }
    if (marked === 0) problems.push(`ASCII 图里 ${name} 点区域没有标「${name}」`)
  }

  if (problems.length) throw new Error(`地图不合法:${problems.join(';')}`)
  return {
    id: def.id,
    name: def.name,
    theme: def.theme,
    tiles,
    siteA: def.siteA,
    siteB: def.siteB,
    playerSpawn: playerSpawn!,
    guardSpawns,
  }
}

/** 给测试用的入口:只看 ASCII 行,关键点用第一张图的区域(坏图测试用) */
export function parseMapRows(
  rows: readonly string[],
  meta: Partial<Omit<MapDef, 'rows'>> = {},
): GameMap {
  return parseMap({
    id: meta.id ?? 'warehouse',
    name: meta.name ?? '测试地图',
    tagline: meta.tagline ?? '',
    theme: meta.theme ?? 'warehouse',
    rows,
    siteA: meta.siteA ?? WAREHOUSE_SITE_A,
    siteB: meta.siteB ?? WAREHOUSE_SITE_B,
  })
}

function siteTileCount(tiles: Uint8Array, rect: TileRect): number {
  let n = 0
  for (let row = rect.y0; row <= rect.y1; row++) {
    for (let col = rect.x0; col <= rect.x1; col++) if (tiles[tileIndex(col, row)] === FLOOR) n++
  }
  return n
}

// ---------------------------------------------------------------- 格子查询

/** 取一格;越界一律当墙(子弹打出去不会漏) */
export function tileAt(map: GameMap, col: number, row: number): number {
  if (!inBounds(col, row)) return WALL
  return map.tiles[tileIndex(col, row)]
}

export function solidAt(map: GameMap, col: number, row: number): boolean {
  return tileAt(map, col, row) !== FLOOR
}

export function solidAtWorld(map: GameMap, x: number, y: number): boolean {
  return solidAt(map, tileCol(x), tileRow(y))
}

/** 这一格能不能站人 */
export function walkable(map: GameMap, col: number, row: number): boolean {
  return inBounds(col, row) && !solidAt(map, col, row)
}

// ---------------------------------------------------------------- 圆和格子

/**
 * 圆是不是压在墙/箱子上:只查和圆外接矩形相交的几格,取每格离圆心最近的点比距离。
 * 玩家半径比半格小,一帧移动又限制在 5 世界单位以内,所以直接查,不用扫掠。
 */
export function circleBlocked(map: GameMap, x: number, y: number, radius: number): boolean {
  const c0 = tileCol(x - radius)
  const c1 = tileCol(x + radius)
  const r0 = tileRow(y - radius)
  const r1 = tileRow(y + radius)
  for (let row = r0; row <= r1; row++) {
    for (let col = c0; col <= c1; col++) {
      if (!solidAt(map, col, row)) continue
      const left = col * TILE
      const top = row * TILE
      const nearestX = Math.min(Math.max(x, left), left + TILE)
      const nearestY = Math.min(Math.max(y, top), top + TILE)
      const dx = x - nearestX
      const dy = y - nearestY
      if (dx * dx + dy * dy < radius * radius) return true
    }
  }
  return false
}

/** 把位置夹回地图里(留出半径) */
export function clampWorld(x: number, y: number, radius: number): Vec {
  return {
    x: Math.min(Math.max(x, radius), WORLD_W - radius),
    y: Math.min(Math.max(y, radius), WORLD_H - radius),
  }
}

/**
 * 圆按 (dx, dy) 移动,撞墙时沿墙滑。拆成小步走:一步最多 radius/2,
 * 每小步分两轴试 —— 一轴被挡另一轴还能走,贴着墙斜着走就不会整个卡住。
 */
export function moveCircle(map: GameMap, from: Vec, dx: number, dy: number, radius: number): Vec {
  const dist = Math.hypot(dx, dy)
  if (dist === 0) return clampWorld(from.x, from.y, radius)
  const steps = Math.max(1, Math.ceil(dist / (radius * 0.5)))
  const sx = dx / steps
  const sy = dy / steps
  let x = from.x
  let y = from.y
  for (let i = 0; i < steps; i++) {
    const nx = x + sx
    if (!circleBlocked(map, nx, y, radius)) x = nx
    const ny = y + sy
    if (!circleBlocked(map, x, ny, radius)) y = ny
  }
  const clamped = clampWorld(x, y, radius)
  return clamped
}

// ---------------------------------------------------------------- 射线

/**
 * 从 from 沿单位向量 dir 走,到第一格实心格子的距离;超过 maxDist 就返回 maxDist。
 * 标准 DDA( Amanatides–Woo ):一格一格跨,永远先跨到更近的那条格线。
 */
export function wallDistance(map: GameMap, from: Vec, dir: Vec, maxDist: number): number {
  let col = tileCol(from.x)
  let row = tileRow(from.y)
  if (solidAt(map, col, row)) return 0
  const stepX = dir.x > 0 ? 1 : -1
  const stepY = dir.y > 0 ? 1 : -1
  const deltaX = dir.x !== 0 ? Math.abs(TILE / dir.x) : Infinity
  const deltaY = dir.y !== 0 ? Math.abs(TILE / dir.y) : Infinity
  let nextX = dir.x !== 0
    ? (dir.x > 0 ? (col + 1) * TILE - from.x : from.x - col * TILE) / Math.abs(dir.x)
    : Infinity
  let nextY = dir.y !== 0
    ? (dir.y > 0 ? (row + 1) * TILE - from.y : from.y - row * TILE) / Math.abs(dir.y)
    : Infinity
  let t = 0
  // 格子再多也就 44×26,给个上限防止 dir 异常时死循环
  for (let guard = 0; guard < COLS + ROWS + 4; guard++) {
    if (nextX < nextY) {
      t = nextX
      col += stepX
      nextX += deltaX
    } else {
      t = nextY
      row += stepY
      nextY += deltaY
    }
    if (t >= maxDist) return maxDist
    if (solidAt(map, col, row)) return t
  }
  return maxDist
}

/** 射线和圆:返回最近的正向交点距离;打不到返回 null。dir 必须是单位向量 */
export function rayCircle(origin: Vec, dir: Vec, center: Vec, radius: number): number | null {
  const ox = origin.x - center.x
  const oy = origin.y - center.y
  const b = ox * dir.x + oy * dir.y
  const c = ox * ox + oy * oy - radius * radius
  if (c <= 0) return 0 // 起点已经在圆里
  const disc = b * b - c
  if (disc < 0) return null
  const t = -b - Math.sqrt(disc)
  return t >= 0 ? t : null
}

export function dist(a: Vec, b: Vec): number {
  return Math.hypot(b.x - a.x, b.y - a.y)
}

export function norm(v: Vec): Vec {
  const len = Math.hypot(v.x, v.y)
  return len === 0 ? { x: 0, y: 0 } : { x: v.x / len, y: v.y / len }
}

/** 从 from 指向 to 的角度(弧度,0 是 +x,顺时针为正,因为屏幕 y 向下) */
export function angleTo(from: Vec, to: Vec): number {
  return Math.atan2(to.y - from.y, to.x - from.x)
}

/** 两个角度之间的最小差(带符号,-π..π) */
export function angleDiff(a: number, b: number): number {
  let d = (b - a) % (Math.PI * 2)
  if (d > Math.PI) d -= Math.PI * 2
  if (d < -Math.PI) d += Math.PI * 2
  return d
}

/** 两点的视线有没有被墙/箱子挡住 */
export function lineOfSight(map: GameMap, a: Vec, b: Vec): boolean {
  const d = dist(a, b)
  if (d === 0) return true
  const dir = { x: (b.x - a.x) / d, y: (b.y - a.y) / d }
  return wallDistance(map, a, dir, d) >= d - 0.001
}

// ---------------------------------------------------------------- 炸弹点

export function inTileRect(rect: TileRect, col: number, row: number): boolean {
  return col >= rect.x0 && col <= rect.x1 && row >= rect.y0 && row <= rect.y1
}

/** 世界坐标落在哪个炸弹点上;不在任何点上返回 null */
export function siteAt(map: GameMap, pos: Vec): Site | null {
  const col = tileCol(pos.x)
  const row = tileRow(pos.y)
  if (inTileRect(map.siteA, col, row)) return 'A'
  if (inTileRect(map.siteB, col, row)) return 'B'
  return null
}

/** 炸弹点区域的中心(世界坐标),给界面画标记用 */
export function siteCenter(rect: TileRect): Vec {
  return { x: ((rect.x0 + rect.x1 + 1) / 2) * TILE, y: ((rect.y0 + rect.y1 + 1) / 2) * TILE }
}
