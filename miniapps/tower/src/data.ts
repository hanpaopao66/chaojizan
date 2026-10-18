// 瓜田防线:全部内容数据 —— 地图尺寸、七种塔 × 三级、九种虫、三个主题、12 关 + 无尽、成就。
// 只有数据和查表函数,和界面无关;规则在 engine.ts,数值的平衡性由 test/balance.test.ts 验证。
//
// 世界观、地名、塔名、虫名、数值和界面都是为超级赞原创的;没有使用任何商业塔防游戏的名字、
// 角色、关卡、美术、数值或界面。
import type { EnemyDef, EnemyKind, GridPoint, PathInfo, Theme, TowerDef, TowerKind, Vec } from './types'

// ---------------------------------------------------------------- 地图

/** 一格的世界尺寸(地图固定 360×560,渲染时整体缩放) */
export const TILE = 40
export const COLS = 9
export const ROWS = 14
export const WORLD_W = COLS * TILE
export const WORLD_H = ROWS * TILE
/** 大西瓜占的那一格 */
export const TARGET: GridPoint = { c: 4, r: 12 }
/** 大西瓜中心(所有路线的终点) */
export const TARGET_CENTER: Vec = { x: (TARGET.c + 0.5) * TILE, y: (TARGET.r + 0.5) * TILE }
/** 固定步长:引擎按 60Hz 推进,渲染帧率无关 */
export const STEP = 1 / 60
/** 每波前的准备时间(秒);第一波由关卡单独给 */
export const PREP_TIME = 3
/** 提前召唤奖励 */
export const EARLY_BONUS = 5
/** 卖出返还比例 */
export const SELL_RATE = 0.7

/** 格坐标 → 世界坐标(格子中心) */
export function cellCenter(p: GridPoint): Vec {
  return { x: (p.c + 0.5) * TILE, y: (p.r + 0.5) * TILE }
}

/** 一条折线(格点)转成世界坐标折线,末尾补上西瓜中心 */
function toWorld(points: readonly GridPoint[]): Vec[] {
  const out: Vec[] = points.map(cellCenter)
  const last = out[out.length - 1]
  if (!last || last.x !== TARGET_CENTER.x || last.y !== TARGET_CENTER.y) out.push({ ...TARGET_CENTER })
  return out
}

function len(a: Vec, b: Vec): number {
  return Math.hypot(b.x - a.x, b.y - a.y)
}

/** 路线的派生信息:折线、长度、入口(关卡模块也用) */
export function pathInfoOf(paths: readonly (readonly GridPoint[])[]): PathInfo {
  const polys = paths.map(toWorld)
  return {
    polys,
    lens: polys.map((poly) => poly.reduce((sum, p, i) => (i === 0 ? 0 : sum + len(poly[i - 1], p)), 0)),
    starts: polys.map((poly) => poly[0]),
    target: { ...TARGET_CENTER },
  }
}

/** 折线上走了 dist 之后的世界坐标(超出返回终点) */
export function pointAt(poly: readonly Vec[], dist: number): Vec {
  let left = Math.max(0, dist)
  for (let i = 1; i < poly.length; i++) {
    const a = poly[i - 1]
    const b = poly[i]
    const l = len(a, b)
    if (l <= 0) continue
    if (left <= l) {
      const t = left / l
      return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }
    }
    left -= l
  }
  const last = poly[poly.length - 1]
  return { x: last.x, y: last.y }
}

/** 把路线经过的格子全标出来(轴对齐折线,按格走) */
export function pathTiles(paths: readonly (readonly GridPoint[])[]): Set<number> {
  const tiles = new Set<number>()
  for (const path of paths) {
    for (let i = 0; i < path.length; i++) {
      const a = path[i]
      const b = path[i + 1]
      tiles.add(a.r * COLS + a.c)
      if (b) {
        const dc = Math.sign(b.c - a.c)
        const dr = Math.sign(b.r - a.r)
        let c = a.c
        let r = a.r
        while (c !== b.c || r !== b.r) {
          c += dc
          r += dr
          tiles.add(r * COLS + c)
        }
      }
    }
  }
  return tiles
}

/**
 * 建造位:路线两侧一格内、不压路也不是西瓜格的草地;按「能盖住多少段路」贪心铺开,
 * 所以每条路沿线都会有塔位,不会全挤在一处。结果只由关卡路线决定,测试里可以复用。
 */
export function computeSlots(paths: readonly (readonly GridPoint[])[]): GridPoint[] {
  const occupied = pathTiles(paths)
  const targetKey = TARGET.r * COLS + TARGET.c
  const seen = new Set<number>()
  const candidates: GridPoint[] = []
  const add = (c: number, r: number): void => {
    if (c < 0 || c >= COLS || r < 0 || r >= ROWS) return
    const key = r * COLS + c
    if (seen.has(key) || occupied.has(key) || key === targetKey) return
    seen.add(key)
    candidates.push({ c, r })
  }
  for (const key of occupied) {
    const c = key % COLS
    const r = Math.floor(key / COLS)
    add(c - 1, r)
    add(c + 1, r)
    add(c, r - 1)
    add(c, r + 1)
  }
  // 采样路面和空中走廊(每半格一个点),贪心挑能覆盖最多「还没被盖住」的路面的塔位。
  // 空中走廊也要算:飞行虫是从入口直线飞向西瓜的,塔位得留一些能打到天上的位置。
  const info = pathInfoOf(paths)
  const samples: Vec[] = []
  for (let i = 0; i < info.polys.length; i++) {
    for (let d = 0; d < info.lens[i]; d += TILE / 2) samples.push(pointAt(info.polys[i], d))
    const start = info.starts[i]
    const air = Math.hypot(info.target.x - start.x, info.target.y - start.y)
    for (let d = 0; d < air; d += TILE / 2) {
      const t = d / air
      samples.push({ x: start.x + (info.target.x - start.x) * t, y: start.y + (info.target.y - start.y) * t })
    }
  }
  const cover = (slot: GridPoint, sample: Vec): boolean => {
    const p = cellCenter(slot)
    return Math.hypot(sample.x - p.x, sample.y - p.y) <= 2.4 * TILE
  }
  // 塔位之间至少隔 2 格,免得全挤在同一个路口;在满足间距的候选里挑「能盖住最多新路面」的
  const taken = new Array<boolean>(samples.length).fill(false)
  const picked: GridPoint[] = []
  const farEnough = (slot: GridPoint): boolean => picked.every((p) => {
    const dc = p.c - slot.c
    const dr = p.r - slot.r
    return dc * dc + dr * dr >= 4
  })
  while (picked.length < 20) {
    let best = -1
    let bestGain = -1
    for (let i = 0; i < candidates.length; i++) {
      const slot = candidates[i]
      if (picked.some((p) => p.c === slot.c && p.r === slot.r) || !farEnough(slot)) continue
      let gain = 0
      for (let j = 0; j < samples.length; j++) if (!taken[j] && cover(slot, samples[j])) gain++
      if (gain > bestGain) {
        bestGain = gain
        best = i
      }
    }
    if (best < 0) break
    const slot = candidates[best]
    picked.push(slot)
    for (let j = 0; j < samples.length; j++) if (!taken[j] && cover(slot, samples[j])) taken[j] = true
  }
  return picked
}

// ---------------------------------------------------------------- 主题

export interface ThemeDef {
  id: Theme
  name: string
  tagline: string
  /** 菜单里这一页的标题色 */
  accent: string
}

export const THEMES: readonly ThemeDef[] = [
  { id: 'garden', name: '菜园', tagline: '白天的菜畦,虫子在土路上探头探脑', accent: '#6E8F3C' },
  { id: 'orchard', name: '果园', tagline: '黄昏的果梯,飞虫和装甲虫一起来了', accent: '#B46A34' },
  { id: 'nest', name: '虫巢', tagline: '月夜下的虫道,两条路一起通到瓜田', accent: '#4E6E8F' },
]

export function themeOf(id: Theme): ThemeDef {
  const t = THEMES.find((x) => x.id === id)
  if (!t) throw new Error(`没有这个主题:${id}`)
  return t
}

// ---------------------------------------------------------------- 塔

/** 全部塔的数值(基准值,平衡测试会验证「可赢」) */
export const TOWERS: readonly TowerDef[] = [
  {
    kind: 'pea',
    name: '豆荚炮',
    role: '便宜单体',
    desc: '青豆一颗一颗往外蹦,前期最稳的输出。3 级双发。',
    cost: 60,
    upgrade: [70, 110],
    color: '#7FA650',
    shape: 'pod',
    levels: [
      { damage: 12, rate: 1.6, range: 2.6 },
      { damage: 18, rate: 1.8, range: 2.8 },
      { damage: 26, rate: 2.0, range: 3.0, shots: 2 },
    ],
  },
  {
    kind: 'frost',
    name: '冰霜铃',
    role: '减速控场',
    desc: '摇一摇铃铛,路过的虫子脚下结霜。3 级有概率冻住。',
    cost: 80,
    upgrade: [90, 140],
    color: '#5E9CC4',
    shape: 'bell',
    levels: [
      { damage: 6, rate: 1.3, range: 2.4, slowFactor: 0.3, slowDur: 1.2 },
      { damage: 9, rate: 1.4, range: 2.6, slowFactor: 0.38, slowDur: 1.4 },
      { damage: 12, rate: 1.5, range: 2.8, slowFactor: 0.45, slowDur: 1.6, freezeChance: 0.15, freezeDur: 0.5 },
    ],
  },
  {
    kind: 'pepper',
    name: '火焰椒',
    role: '溅射清群',
    desc: '一颗辣椒炸弹,落点周围一起烧。3 级还会点着虫子。',
    cost: 100,
    upgrade: [110, 170],
    color: '#D8623A',
    shape: 'pepper',
    levels: [
      { damage: 14, rate: 0.85, range: 2.2, splash: 0.8 },
      { damage: 22, rate: 0.9, range: 2.4, splash: 1.0 },
      { damage: 22, rate: 0.95, range: 2.6, splash: 1.1, burnDps: 4, burnDur: 3 },
    ],
  },
  {
    kind: 'vine',
    name: '闪电藤',
    role: '链电多目标',
    desc: '藤蔓上攒一道电,顺着虫群跳过去,每跳弱一点。',
    cost: 120,
    upgrade: [140, 210],
    color: '#C8A83C',
    shape: 'vine',
    levels: [
      { damage: 20, rate: 0.7, range: 2.8, chain: 2 },
      { damage: 20, rate: 0.75, range: 3.0, chain: 3 },
      { damage: 25, rate: 0.8, range: 3.2, chain: 4 },
    ],
  },
  {
    kind: 'mushroom',
    name: '毒蘑菇',
    role: '持续毒伤',
    desc: '孢子落在虫群里,毒无视护甲。3 级死后留一片毒云。',
    cost: 90,
    upgrade: [100, 150],
    color: '#9C6BA8',
    shape: 'mushroom',
    levels: [
      { damage: 3, rate: 1.1, range: 2.0, poisonDps: 6, poisonDur: 4, poisonRadius: 1.0 },
      { damage: 3, rate: 1.2, range: 2.2, poisonDps: 9, poisonDur: 4, poisonRadius: 1.2 },
      { damage: 4, rate: 1.3, range: 2.4, poisonDps: 9, poisonDur: 4, poisonRadius: 1.4, deathCloud: true },
    ],
  },
  {
    kind: 'bow',
    name: '瓜藤弓',
    role: '远程穿甲',
    desc: '一根瓜藤当弓弦,射得远、打得疼。3 级穿甲。',
    cost: 140,
    upgrade: [170, 260],
    color: '#8A6E4B',
    shape: 'bow',
    levels: [
      { damage: 42, rate: 0.45, range: 4.2 },
      { damage: 56, rate: 0.5, range: 4.4 },
      { damage: 72, rate: 0.55, range: 4.6, pierce: true },
    ],
  },
  {
    kind: 'marigold',
    name: '金盏花',
    role: '经济',
    desc: '不打架,只管开花;每清完一波给你送金币。',
    cost: 100,
    upgrade: [120, 180],
    color: '#E0A93C',
    shape: 'flower',
    levels: [
      { damage: 0, rate: 0, range: 0, goldPerWave: 30 },
      { damage: 0, rate: 0, range: 0, goldPerWave: 45 },
      { damage: 0, rate: 0, range: 0, goldPerWave: 65 },
    ],
  },
]

const TOWER_BY_KIND = new Map<TowerKind, TowerDef>(TOWERS.map((t) => [t.kind, t]))

export function towerDef(kind: TowerKind): TowerDef {
  const t = TOWER_BY_KIND.get(kind)
  if (!t) throw new Error(`没有这种塔:${kind}`)
  return t
}

export function towerDefOrNull(kind: unknown): TowerDef | null {
  return typeof kind === 'string' ? TOWER_BY_KIND.get(kind as TowerKind) || null : null
}

/** 某种塔在场上这一级的数值 */
export function towerStats(kind: TowerKind, level: number): TowerDef['levels'][number] {
  const def = towerDef(kind)
  const i = Math.min(2, Math.max(0, Math.round(level) - 1))
  return def.levels[i]
}

/** 升到下一级要多少钱;满级返回 0 */
export function upgradeCost(kind: TowerKind, level: number): number {
  const def = towerDef(kind)
  if (level >= 3) return 0
  return def.upgrade[level - 1]
}

/** 卖出返还(总投入的 70%,向下取整) */
export function sellValue(invested: number): number {
  return Math.floor(invested * SELL_RATE)
}

// ---------------------------------------------------------------- 虫

export const ENEMIES: readonly EnemyDef[] = [
  {
    kind: 'worm', name: '青虫', hp: 30, speed: 1.0, bounty: 6, armor: 0, flying: false, leak: 1,
    size: 11, color: '#7FAE5A',
  },
  {
    kind: 'flea', name: '跳蚤', hp: 18, speed: 2.0, bounty: 5, armor: 0, flying: false, leak: 1,
    size: 8, color: '#C9A24A',
  },
  {
    kind: 'beetle', name: '甲虫', hp: 70, speed: 0.8, bounty: 10, armor: 4, flying: false, leak: 1,
    size: 13, color: '#6E7A8A',
  },
  {
    kind: 'moth', name: '飞蛾', hp: 35, speed: 1.5, bounty: 7, armor: 0, flying: true, leak: 1,
    size: 9, color: '#D8C48A',
  },
  {
    kind: 'wasp', name: '毒蜂', hp: 60, speed: 1.6, bounty: 9, armor: 0, flying: true, leak: 1,
    size: 9, color: '#D8A03C',
  },
  {
    kind: 'pupa', name: '治疗蛹', hp: 80, speed: 0.9, bounty: 12, armor: 0, flying: false, leak: 1,
    heal: { rate: 5, radius: 1.6 }, size: 12, color: '#B48EC8',
  },
  {
    kind: 'ant', name: '分裂蚁', hp: 55, speed: 1.1, bounty: 8, armor: 0, flying: false, leak: 1,
    split: 2, size: 11, color: '#A8644B',
  },
  {
    kind: 'antling', name: '小蚁', hp: 22, speed: 1.2, bounty: 2, armor: 0, flying: false, leak: 1,
    size: 7, color: '#BC8062',
  },
  {
    kind: 'boss', name: '巨虫', hp: 900, speed: 0.6, bounty: 150, armor: 6, flying: false, leak: 5,
    boss: true, size: 22, color: '#5A4A3E',
  },
]

const ENEMY_BY_KIND = new Map<EnemyKind, EnemyDef>(ENEMIES.map((e) => [e.kind, e]))

export function enemyDef(kind: EnemyKind): EnemyDef {
  const e = ENEMY_BY_KIND.get(kind)
  if (!e) throw new Error(`没有这种虫:${kind}`)
  return e
}

export function enemyDefOrNull(kind: unknown): EnemyDef | null {
  return typeof kind === 'string' ? ENEMY_BY_KIND.get(kind as EnemyKind) || null : null
}

/** 血量的波次成长:HP × (1 + 0.06×(波次−1) + 0.03×(关卡−1)) */
export function healthScale(wave: number, levelIndex: number): number {
  return 1 + 0.06 * Math.max(0, wave - 1) + 0.03 * Math.max(0, levelIndex - 1)
}

/** 无尽模式的血量成长:比关卡更快,但二阶项温和,20 波不至于没法打 */
export function endlessHealthScale(wave: number): number {
  const n = Math.max(0, wave - 1)
  return 1 + 0.05 * n + 0.0018 * n * n
}

/**
 * Boss 的血量成长只看波次,不再叠加关卡系数。
 * 巨虫本来就有 900 基础血 + 护甲 6,关卡系数再乘一遍会让后期 Boss 变成只能靠满级塔才打得动的血袋,
 * 也容易让「前面都守住了、最后一只漏掉」变成 1 星。
 */
export function bossHealthScale(wave: number): number {
  return 1 + 0.06 * Math.max(0, wave - 1)
}

// ---------------------------------------------------------------- 成就

export interface AchievementDef {
  id: string
  name: string
  desc: string
}

/** 成就(判定逻辑在 profile.ts) */
export const ACHIEVEMENTS: readonly AchievementDef[] = [
  { id: 'first_win', name: '第一次丰收', desc: '通关任意一关。' },
  { id: 'first_build', name: '第一根木桩', desc: '在田里造出第一座塔。' },
  { id: 'flawless', name: '毫发无伤', desc: '满血通关任意一关(3 星)。' },
  { id: 'garden_full', name: '菜园看门人', desc: '菜园 4 关全部 3 星。' },
  { id: 'orchard_guard', name: '果园守夜', desc: '通关第 8 关「果园守卫战」。' },
  { id: 'night_walker', name: '月夜行者', desc: '通关第 12 关「虫巢母体」。' },
  { id: 'boss_hunter', name: '屠虫者', desc: '累计击败 3 只巨虫 Boss。' },
  { id: 'tower_master', name: '一田七塔', desc: '在任意一局里造出 12 座塔。' },
  { id: 'all_towers', name: '七种武器', desc: '七种塔都至少造过一次。' },
  { id: 'endless_10', name: '坚持十波', desc: '无尽模式撑过 10 波。' },
  { id: 'endless_20', name: '二十波不倒', desc: '无尽模式撑过 20 波。' },
  { id: 'rich_farmer', name: '富农', desc: '累计赚到 5000 金币。' },
]

export const ACHIEVEMENT_BY_ID = new Map<string, AchievementDef>(ACHIEVEMENTS.map((a) => [a.id, a]))

/** 某一关的三星门槛(界面说明用) */
export const STAR_RULE = '满血 3 星 · 剩余 ≥60% 2 星 · 通关 1 星'
