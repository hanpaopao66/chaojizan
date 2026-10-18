// 12 关 + 无尽模式的具体地图、波次和推荐塔序。全部用 data.ts 的塔/虫数值与路线工具拼出来;
// 建造位由路线自动铺开(见 data.ts 的 computeSlots),保证每条路沿线都有位置。
import { cellCenter, computeSlots, pathInfoOf } from './data'
import type { EnemyKind, LevelDef, Theme, TowerKind, WaveDef, WaveGroup } from './types'

// ---------------------------------------------------------------- 波次简写

/** 一波里的一组虫子:数量 / 间隔 / 延迟 / 走哪条路 */
const G = (kind: EnemyKind, count: number, gap = 0.7, delay = 0, path = 0): WaveGroup => ({ kind, count, gap, delay, path })
/** 一波:各组的组合;boss 标记只是为了界面,不写也行 */
const W = (...groups: WaveGroup[]): WaveDef => ({ groups })

// ---------------------------------------------------------------- 关卡

type RawLevel = Omit<LevelDef, 'world' | 'slots' | 'hintSlot'>

/** 造一关:路线派生世界坐标和建造位,顺便算新手提示的塔位(离入口最近的那个) */
function mkLevel(raw: RawLevel): LevelDef {
  const world = pathInfoOf(raw.paths)
  const slots = computeSlots(raw.paths).slice(0, raw.slotCap)
  let hintSlot = 0
  let best = Infinity
  slots.forEach((slot, i) => {
    const p = cellCenter(slot)
    world.starts.forEach((s) => {
      const d = Math.hypot(p.x - s.x, p.y - s.y)
      if (d < best) {
        best = d
        hintSlot = i
      }
    })
  })
  return { ...raw, world, slots, hintSlot }
}

const GARDEN = ['pea'] as const
const GARDEN2 = ['pea', 'frost'] as const

export const LEVELS: readonly LevelDef[] = [
  // ===== 菜园(白天):教学、双塔、冰火、第一个小 Boss =====
  mkLevel({
    id: 1,
    name: '菜畦小径',
    theme: 'garden',
    firstPrep: 14,
    goalHp: 20,
    startGold: 200,
    towers: GARDEN,
    slotCap: 10,
    recommend: ['pea', 'pea', 'pea', 'pea', 'pea', 'pea'],
    paths: [[{ c: 4, r: 0 }, { c: 4, r: 3 }, { c: 2, r: 3 }, { c: 2, r: 7 }, { c: 6, r: 7 }, { c: 6, r: 10 }, { c: 4, r: 10 }, { c: 4, r: 11 }]],
    waves: [
      W(G('worm', 5, 1.0)),
      W(G('worm', 7, 0.8)),
      W(G('flea', 4, 0.6), G('worm', 5, 0.8, 1)),
      W(G('worm', 8, 0.6), G('flea', 3, 0.5, 2)),
      W(G('worm', 6, 0.6), G('flea', 5, 0.4, 2)),
      { groups: [G('worm', 10, 0.5), G('flea', 6, 0.4, 3)], prep: 4 },
    ],
  }),
  mkLevel({
    id: 2,
    name: '豆架迷宫',
    theme: 'garden',
    firstPrep: 10,
    goalHp: 20,
    startGold: 220,
    towers: GARDEN2,
    slotCap: 11,
    recommend: ['pea', 'pea', 'frost', 'pea', 'pea', 'frost'],
    paths: [[{ c: 3, r: 0 }, { c: 3, r: 2 }, { c: 1, r: 2 }, { c: 1, r: 6 }, { c: 7, r: 6 }, { c: 7, r: 9 }, { c: 4, r: 9 }, { c: 4, r: 11 }]],
    waves: [
      W(G('worm', 6, 0.9)),
      W(G('flea', 6, 0.6)),
      W(G('beetle', 3, 1.2), G('worm', 6, 0.7, 1)),
      W(G('flea', 8, 0.4), G('beetle', 2, 1.5, 2)),
      W(G('worm', 10, 0.55), G('beetle', 4, 1.1, 2)),
      { groups: [G('beetle', 5, 1.0), G('flea', 8, 0.4, 1), G('worm', 8, 0.6, 3)], prep: 4 },
    ],
  }),
  mkLevel({
    id: 3,
    name: '南瓜回廊',
    theme: 'garden',
    firstPrep: 10,
    goalHp: 22,
    startGold: 240,
    towers: ['pea', 'frost', 'pepper', 'marigold'],
    slotCap: 12,
    recommend: ['pea', 'pea', 'frost', 'pepper', 'pea', 'pepper', 'frost'],
    paths: [[{ c: 0, r: 1 }, { c: 6, r: 1 }, { c: 6, r: 3 }, { c: 1, r: 3 }, { c: 1, r: 7 }, { c: 7, r: 7 }, { c: 7, r: 10 }, { c: 4, r: 10 }, { c: 4, r: 11 }]],
    waves: [
      W(G('worm', 6, 0.9)),
      W(G('flea', 5, 0.55), G('worm', 4, 0.8, 1)),
      W(G('beetle', 4, 1.2), G('worm', 6, 0.7, 1)),
      W(G('moth', 4, 0.9), G('flea', 4, 0.5, 1)),
      W(G('beetle', 6, 1.0), G('moth', 4, 0.9, 2)),
      W(G('worm', 12, 0.45), G('flea', 8, 0.35, 1)),
      { groups: [G('beetle', 6, 0.9), G('moth', 6, 0.7, 1), G('flea', 8, 0.35, 3)], prep: 4 },
    ],
  }),
  mkLevel({
    id: 4,
    name: '巨型青虫',
    theme: 'garden',
    firstPrep: 12,
    goalHp: 25,
    startGold: 260,
    towers: ['pea', 'frost', 'pepper', 'marigold'],
    slotCap: 13,
    recommend: ['pea', 'pea', 'frost', 'pepper', 'pea', 'pepper', 'frost', 'pea'],
    paths: [[{ c: 8, r: 1 }, { c: 4, r: 1 }, { c: 4, r: 4 }, { c: 1, r: 4 }, { c: 1, r: 8 }, { c: 6, r: 8 }, { c: 6, r: 10 }, { c: 4, r: 10 }, { c: 4, r: 11 }]],
    waves: [
      W(G('worm', 8, 0.8)),
      W(G('flea', 6, 0.5), G('beetle', 3, 1.2, 1)),
      W(G('moth', 6, 0.8)),
      W(G('beetle', 5, 1.0), G('worm', 10, 0.5, 2)),
      W(G('flea', 10, 0.35), G('moth', 6, 0.7, 2)),
      W(G('beetle', 8, 0.8), G('moth', 4, 0.9, 2)),
      { groups: [G('boss', 1, 1, 6), G('worm', 10, 0.5), G('flea', 6, 0.4, 3)], prep: 5, boss: true },
    ],
  }),

  // ===== 果园(黄昏):飞行虫、装甲虫、分裂蚁、治疗蛹 =====
  mkLevel({
    id: 5,
    name: '落日果梯',
    theme: 'orchard',
    firstPrep: 10,
    goalHp: 22,
    startGold: 220,
    towers: ['pea', 'frost', 'pepper', 'marigold', 'mushroom'],
    slotCap: 13,
    recommend: ['pea', 'pea', 'frost', 'pepper', 'mushroom', 'pea', 'pepper'],
    paths: [[{ c: 4, r: 0 }, { c: 4, r: 2 }, { c: 1, r: 2 }, { c: 1, r: 6 }, { c: 7, r: 6 }, { c: 7, r: 9 }, { c: 4, r: 9 }, { c: 4, r: 11 }]],
    waves: [
      W(G('worm', 8, 0.8)),
      W(G('ant', 4, 1.2), G('worm', 4, 0.8, 1)),
      W(G('beetle', 4, 1.1), G('ant', 4, 1.2, 1)),
      W(G('moth', 6, 0.8), G('flea', 6, 0.5, 1)),
      W(G('pupa', 2, 2.0), G('worm', 10, 0.55, 1)),
      W(G('ant', 6, 1.0), G('beetle', 6, 0.9, 1)),
      { groups: [G('pupa', 3, 1.8), G('flea', 12, 0.3), G('ant', 6, 1.0, 2)], prep: 4 },
    ],
  }),
  mkLevel({
    id: 6,
    name: '蜂糖栈道',
    theme: 'orchard',
    firstPrep: 10,
    goalHp: 24,
    startGold: 240,
    towers: ['pea', 'frost', 'pepper', 'marigold', 'mushroom', 'bow'],
    slotCap: 14,
    recommend: ['pea', 'pea', 'frost', 'bow', 'pepper', 'mushroom', 'pea', 'bow'],
    paths: [[{ c: 0, r: 3 }, { c: 3, r: 3 }, { c: 3, r: 1 }, { c: 6, r: 1 }, { c: 6, r: 6 }, { c: 2, r: 6 }, { c: 2, r: 9 }, { c: 6, r: 9 }, { c: 6, r: 11 }, { c: 4, r: 11 }]],
    waves: [
      W(G('flea', 8, 0.5)),
      W(G('ant', 5, 1.0)),
      W(G('wasp', 4, 0.9)),
      W(G('beetle', 6, 0.9), G('ant', 4, 1.1, 1)),
      W(G('pupa', 2, 1.8), G('worm', 10, 0.5)),
      W(G('wasp', 3, 0.8), G('moth', 3, 0.8, 1)),
      W(G('ant', 6, 0.9), G('beetle', 5, 0.8, 1), G('pupa', 2, 2.0, 2)),
      { groups: [G('wasp', 3, 0.8), G('flea', 8, 0.35, 1), G('beetle', 5, 0.9, 2)], prep: 4 },
    ],
  }),
  mkLevel({
    id: 7,
    name: '蛹灯夜径',
    theme: 'orchard',
    firstPrep: 10,
    goalHp: 26,
    startGold: 260,
    towers: ['pea', 'frost', 'pepper', 'marigold', 'mushroom', 'bow', 'vine'],
    slotCap: 14,
    recommend: ['pea', 'pea', 'frost', 'vine', 'bow', 'pepper', 'mushroom', 'vine'],
    paths: [[{ c: 8, r: 2 }, { c: 5, r: 2 }, { c: 5, r: 5 }, { c: 2, r: 5 }, { c: 2, r: 9 }, { c: 6, r: 9 }, { c: 6, r: 11 }, { c: 4, r: 11 }]],
    waves: [
      W(G('worm', 10, 0.7)),
      W(G('ant', 6, 1.0), G('flea', 6, 0.45, 1)),
      W(G('beetle', 6, 0.9), G('wasp', 3, 0.9, 1)),
      W(G('pupa', 4, 1.6), G('ant', 6, 1.0, 1)),
      W(G('moth', 5, 0.7), G('wasp', 2, 0.9, 2)),
      W(G('beetle', 6, 0.8), G('ant', 6, 0.8, 1)),
      W(G('pupa', 3, 1.5), G('wasp', 5, 0.7, 1), G('flea', 8, 0.35, 2)),
      { groups: [G('ant', 8, 0.8), G('beetle', 6, 0.8, 1), G('pupa', 3, 1.6, 2)], prep: 4 },
    ],
  }),
  mkLevel({
    id: 8,
    name: '果园守卫战',
    theme: 'orchard',
    firstPrep: 12,
    goalHp: 28,
    startGold: 280,
    towers: ['pea', 'frost', 'pepper', 'marigold', 'mushroom', 'bow', 'vine'],
    slotCap: 15,
    recommend: ['pea', 'pea', 'frost', 'pepper', 'bow', 'vine', 'mushroom', 'pea', 'bow'],
    paths: [[{ c: 0, r: 5 }, { c: 3, r: 5 }, { c: 3, r: 1 }, { c: 7, r: 1 }, { c: 7, r: 7 }, { c: 3, r: 7 }, { c: 3, r: 10 }, { c: 4, r: 10 }, { c: 4, r: 11 }]],
    waves: [
      W(G('worm', 10, 0.7)),
      W(G('flea', 10, 0.4), G('ant', 4, 1.1, 1)),
      W(G('beetle', 6, 0.9), G('wasp', 4, 0.8, 1)),
      W(G('moth', 8, 0.6), G('ant', 6, 0.9, 1)),
      W(G('pupa', 4, 1.6), G('beetle', 8, 0.8, 1)),
      W(G('wasp', 5, 0.9), G('flea', 10, 0.3, 1)),
      W(G('ant', 8, 0.8), G('beetle', 6, 0.8, 1), G('pupa', 3, 1.8, 2)),
      W(G('moth', 5, 0.9), G('wasp', 5, 0.9, 1)),
      { groups: [G('boss', 1, 1, 6), G('beetle', 6, 0.8), G('ant', 6, 0.9, 2)], prep: 5, boss: true },
    ],
  }),

  // ===== 虫巢(月夜):混合波、双入口(第 10 关起)、Boss 波 =====
  mkLevel({
    id: 9,
    name: '月光虫道',
    theme: 'nest',
    firstPrep: 12,
    goalHp: 26,
    startGold: 240,
    towers: ['pea', 'frost', 'pepper', 'marigold', 'mushroom', 'bow', 'vine'],
    slotCap: 15,
    recommend: ['pea', 'pea', 'frost', 'pepper', 'bow', 'vine', 'mushroom', 'vine', 'bow'],
    paths: [[{ c: 4, r: 0 }, { c: 1, r: 0 }, { c: 1, r: 4 }, { c: 3, r: 4 }, { c: 3, r: 8 }, { c: 7, r: 8 }, { c: 7, r: 4 }, { c: 8, r: 4 }, { c: 8, r: 10 }, { c: 5, r: 10 }, { c: 5, r: 11 }, { c: 4, r: 11 }]],
    waves: [
      W(G('ant', 6, 1.0), G('flea', 8, 0.4, 1)),
      W(G('beetle', 8, 0.8), G('moth', 6, 0.7, 1)),
      W(G('wasp', 8, 0.6)),
      W(G('pupa', 3, 1.5), G('ant', 6, 0.9, 1)),
      W(G('beetle', 10, 0.7), G('wasp', 6, 0.7, 1)),
      W(G('moth', 8, 0.5), G('flea', 10, 0.3, 1)),
      W(G('pupa', 4, 1.5), G('ant', 8, 0.8, 1)),
      W(G('beetle', 10, 0.7), G('wasp', 10, 0.5, 1)),
      { groups: [G('pupa', 5, 1.4), G('moth', 10, 0.5, 1), G('ant', 10, 0.8, 2)], prep: 4 },
    ],
  }),
  mkLevel({
    id: 10,
    name: '双孔巢门',
    theme: 'nest',
    firstPrep: 12,
    goalHp: 30,
    startGold: 280,
    towers: ['pea', 'frost', 'pepper', 'marigold', 'mushroom', 'bow', 'vine'],
    slotCap: 16,
    recommend: ['pea', 'pea', 'frost', 'pepper', 'bow', 'vine', 'mushroom', 'vine', 'bow'],
    paths: [
      [{ c: 0, r: 2 }, { c: 0, r: 9 }, { c: 3, r: 9 }, { c: 3, r: 5 }, { c: 6, r: 5 }, { c: 6, r: 9 }, { c: 4, r: 9 }, { c: 4, r: 11 }],
      [{ c: 8, r: 2 }, { c: 8, r: 9 }, { c: 5, r: 9 }, { c: 5, r: 5 }, { c: 2, r: 5 }, { c: 2, r: 9 }, { c: 4, r: 9 }, { c: 4, r: 11 }],
    ],
    waves: [
      W(G('worm', 10, 0.6, 0, 0)),
      W(G('ant', 6, 0.9, 0, 0), G('beetle', 5, 0.9, 0.5, 1)),
      W(G('wasp', 8, 0.5, 0, 0)),
      W(G('moth', 8, 0.5, 0, 0), G('flea', 10, 0.3, 0.5, 1)),
      W(G('pupa', 4, 1.5, 0, 0), G('ant', 8, 0.8, 1.0, 1)),
      W(G('beetle', 10, 0.7, 0, 0), G('wasp', 6, 0.6, 0.5, 1)),
      W(G('moth', 5, 0.8, 0, 0), G('flea', 8, 0.35, 0.5, 1)),
      W(G('pupa', 4, 1.5, 0, 0), G('beetle', 8, 0.7, 0.5, 1), G('ant', 8, 0.8, 1.0, 0)),
      W(G('wasp', 10, 0.4, 0, 0), G('moth', 8, 0.5, 0.5, 1)),
      { groups: [G('beetle', 10, 0.6, 0, 0), G('ant', 10, 0.7, 0.5, 1), G('pupa', 4, 1.5, 1.0, 0)], prep: 4 },
    ],
  }),
  mkLevel({
    id: 11,
    name: '毒雾深井',
    theme: 'nest',
    firstPrep: 12,
    goalHp: 30,
    startGold: 300,
    towers: ['pea', 'frost', 'pepper', 'marigold', 'mushroom', 'bow', 'vine'],
    slotCap: 20,
    recommend: ['pea', 'pea', 'frost', 'pepper', 'bow', 'vine', 'mushroom', 'vine', 'bow', 'pepper'],
    paths: [
      [{ c: 4, r: 0 }, { c: 1, r: 0 }, { c: 1, r: 4 }, { c: 4, r: 4 }, { c: 4, r: 8 }, { c: 1, r: 8 }, { c: 1, r: 11 }, { c: 4, r: 11 }],
      [{ c: 8, r: 1 }, { c: 5, r: 1 }, { c: 5, r: 5 }, { c: 8, r: 5 }, { c: 8, r: 9 }, { c: 5, r: 9 }, { c: 5, r: 11 }, { c: 4, r: 11 }],
    ],
    waves: [
      W(G('ant', 4, 0.9, 0, 0), G('flea', 7, 0.35, 0.5, 1)),
      W(G('beetle', 7, 0.7, 0, 0), G('moth', 5, 0.6, 0.5, 1)),
      W(G('wasp', 5, 0.9, 0, 0)),
      W(G('pupa', 3, 1.4, 0, 0), G('ant', 4, 0.8, 0.8, 0)),
      W(G('beetle', 8, 0.7, 0, 0), G('wasp', 3, 0.9, 0.5, 1)),
      W(G('moth', 7, 0.7, 0, 0), G('flea', 9, 0.32, 0.5, 1)),
      W(G('pupa', 4, 1.3, 0, 0), G('ant', 5, 0.7, 0.8, 0)),
      W(G('beetle', 8, 0.7, 0, 0), G('wasp', 4, 0.9, 0.5, 1)),
      W(G('pupa', 4, 1.3, 0, 0), G('moth', 7, 0.6, 0.5, 1), G('ant', 6, 0.7, 1.0, 0)),
      { groups: [G('beetle', 10, 0.6, 0, 0), G('wasp', 5, 0.9, 0.5, 1), G('pupa', 4, 1.3, 1.0, 0)], prep: 4 },
    ],
  }),
  mkLevel({
    id: 12,
    name: '虫巢母体',
    theme: 'nest',
    firstPrep: 15,
    goalHp: 30,
    startGold: 300,
    towers: ['pea', 'frost', 'pepper', 'marigold', 'mushroom', 'bow', 'vine'],
    slotCap: 21,
    recommend: ['pea', 'pea', 'frost', 'pepper', 'bow', 'vine', 'mushroom', 'vine', 'bow', 'pepper'],
    paths: [
      [{ c: 0, r: 1 }, { c: 3, r: 1 }, { c: 3, r: 7 }, { c: 0, r: 7 }, { c: 0, r: 11 }, { c: 4, r: 11 }],
      [{ c: 8, r: 1 }, { c: 5, r: 1 }, { c: 5, r: 7 }, { c: 8, r: 7 }, { c: 8, r: 11 }, { c: 4, r: 11 }],
    ],
    waves: [
      W(G('worm', 9, 0.6, 0, 0), G('worm', 4, 0.7, 0.5, 1)),
      W(G('ant', 4, 0.9, 0, 0), G('beetle', 3, 0.9, 0.5, 1)),
      W(G('wasp', 5, 0.9, 0, 0), G('moth', 3, 0.9, 0.5, 1)),
      W(G('moth', 10, 0.45, 0, 0), G('flea', 12, 0.28, 0.5, 1)),
      W(G('pupa', 3, 1.4, 0, 0), G('ant', 6, 0.8, 1.0, 1)),
      W(G('beetle', 7, 0.7, 0, 0), G('wasp', 4, 0.9, 0.5, 1)),
      W(G('moth', 8, 0.6, 0, 0), G('flea', 10, 0.3, 0.5, 1)),
      W(G('pupa', 3, 1.4, 0, 0), G('beetle', 6, 0.8, 0.5, 1), G('ant', 6, 0.8, 1.0, 0)),
      W(G('wasp', 6, 0.9, 0, 0), G('moth', 5, 0.8, 0.5, 1)),
      W(G('pupa', 3, 1.4, 0, 0), G('beetle', 7, 0.8, 0.5, 1), G('ant', 7, 0.8, 1.0, 0)),
      { groups: [G('boss', 1, 1, 11, 0), G('beetle', 4, 0.9, 4, 0), G('wasp', 4, 0.9, 5, 1), G('ant', 5, 0.9, 5, 0)], prep: 8, boss: true },
    ],
  }),
]

/** 无尽模式:地图和第 12 关一样(双入口),波次由 waves.ts 现场生成 */
export const ENDLESS: LevelDef = mkLevel({
  id: 'endless',
  name: '无尽瓜田',
  theme: 'nest',
  firstPrep: 15,
  goalHp: 20,
  startGold: 600,
  towers: ['pea', 'frost', 'pepper', 'marigold', 'mushroom', 'bow', 'vine'],
  slotCap: 17,
  recommend: ['pea', 'pea', 'frost', 'pepper', 'bow', 'vine', 'mushroom', 'vine', 'bow', 'pepper'],
  paths: LEVELS[11].paths,
  waves: [],
})

export const LEVEL_LIST: readonly LevelDef[] = [...LEVELS, ENDLESS]

const LEVEL_BY_ID = new Map<number | 'endless', LevelDef>(LEVEL_LIST.map((l) => [l.id, l]))

/** 按 id 找关卡;找不到抛错。'endless' 也在里面 */
export function levelById(id: number | 'endless'): LevelDef {
  const l = LEVEL_BY_ID.get(id)
  if (!l) throw new Error(`没有这一关:${id}`)
  return l
}

export function levelByIdOrNull(id: unknown): LevelDef | null {
  if (id === 'endless') return ENDLESS
  if (typeof id !== 'number' || !Number.isInteger(id)) return null
  return LEVELS[id - 1] || null
}

/** 这一关有多少波(无尽返回 Infinity) */
export function waveCount(level: LevelDef): number {
  return level.id === 'endless' ? Infinity : level.waves.length
}

/** 某种塔第一次能在哪一关用 */
export function unlockLevelOf(kind: TowerKind): number {
  const i = LEVELS.findIndex((l) => l.towers.includes(kind))
  return i < 0 ? 99 : (LEVELS[i].id as number)
}

/** 三页主题:每页 4 关 */
export function levelsOfTheme(theme: Theme): readonly LevelDef[] {
  return LEVELS.filter((l) => l.theme === theme)
}
