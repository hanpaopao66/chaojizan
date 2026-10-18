// 测试用的两种参考策略:
// - mixed:混塔 —— 按关卡的 recommend 序列铺减速/溅射/链电/穿甲/毒,再升级;这是「合理玩家」的打法,
//   也是新手提示里推荐的塔序;
// - pea:纯豆荚炮 —— 只铺最便宜的豆荚炮再升级。前期够用,第 7 关起护甲/分路/群怪压力上来后就不够了,
//   测试会断言它拿不到 3 星(用来防止数值退化回「一座塔打穿全游戏」)。
import { advance, command, newGame } from '../src/engine'
import { resultOf } from '../src/save'
import type { GameState, TowerKind } from '../src/types'
import { levelById, levelByIdOrNull } from '../src/levels'
import { enemyDef, towerDef } from '../src/data'

/** 参考策略先铺多少座塔,铺完就升级(两种策略用同一个上限,公平比较) */
export const BUILD_LIMIT = 16
const CHEAP: TowerKind = 'pea'

export type Strategy = 'pea' | 'mixed'

export interface SimResult {
  state: GameState
  won: boolean
  stars: number
  /** 在多少秒内结束/停止 */
  seconds: number
  /** 无尽模式是否撑到了目标波数 */
  survived: boolean
  /** 造过的塔(测试失败时方便看) */
  built: TowerKind[]
}

/**
 * 混塔策略的升级优先级:先把便宜的基础输出升起来(豆荚炮铺量,升级性价比最高),
 * 再升控场和穿甲;「先升减速」反而会在中期缺伤害。
 */
const UPGRADE_ORDER: readonly TowerKind[] = ['pea', 'frost', 'bow', 'pepper', 'vine', 'mushroom']

/** 这一轮想造什么塔(混塔用 recommend,纯炮只用豆荚炮) */
function planTowerAt(state: GameState, strategy: Strategy): TowerKind {
  const level = levelById(state.levelId)
  if (strategy === 'pea' || !level.recommend.length) {
    return level.towers.includes(CHEAP) ? CHEAP : level.towers[0]
  }
  let plan = level.recommend.filter((k) => level.towers.includes(k))
  // 有飞行虫的关卡:先把能打空中的塔摆在最靠前(建造位也是按空中覆盖优先排的)
  if (level.waves.some((w) => w.groups.some((g) => enemyDef(g.kind).flying))) {
    const airFirst = ['frost', 'bow'].filter((k) => level.towers.includes(k as TowerKind)) as TowerKind[]
    plan = [...airFirst, ...plan.filter((k) => !airFirst.includes(k))]
  }
  return plan[state.towers.length % plan.length] || CHEAP
}

/**
 * 升级先升哪个:等级低的优先,同级按 UPGRADE_ORDER(控场/穿甲优先)。
 * reserve 是「还要留着造下一座计划塔的钱」——混塔策略会先攒钱把推荐序列造出来,
 * 不会把金币全花在升级上导致冰霜铃/瓜藤弓一直造不出来。
 */
function nextUpgrade(state: GameState, strategy: Strategy, reserve: number): GameState['towers'][number] | null {
  const candidates = state.towers.filter((t) => t.level < 3)
  if (!candidates.length) return null
  const rank = (k: TowerKind): number => {
    const i = UPGRADE_ORDER.indexOf(k)
    return i < 0 ? 99 : i
  }
  candidates.sort((a, b) => {
    if (strategy === 'pea') return a.level - b.level || a.id - b.id
    return a.level - b.level || rank(a.kind) - rank(b.kind) || a.id - b.id
  })
  const t = candidates[0]
  const cost = t.level === 1 ? towerDef(t.kind).upgrade[0] : towerDef(t.kind).upgrade[1]
  return state.gold >= cost + reserve ? t : null
}

/** 一个「会花金币」的玩家:先铺塔,铺到上限就升级,实在没处花就提前召唤 */
function botStep(state: GameState, targetWaves: number, strategy: Strategy): void {
  const level = levelById(state.levelId)
  const limit = Math.min(level.slots.length, BUILD_LIMIT)
  let guard = 0
  while (guard++ < 12) {
    // ① 铺塔(还没到上限):混塔严格按推荐序列(钱不够就攒着,不乱造便宜的替代),
    //    纯炮只造豆荚炮
    if (state.towers.length < limit) {
      const want = planTowerAt(state, strategy)
      if (state.gold >= towerDef(want).cost) {
        let slot = -1
        for (let i = 0; i < limit; i++) if (!state.towers.some((t) => t.slot === i)) { slot = i; break }
        if (slot >= 0 && command(state, { kind: 'build', slot, tower: want }).ok) continue
      }
    }
    // ② 升级(有关卡的空中威胁时,混塔要留出造冰霜铃/瓜藤弓的钱)
    const want = state.towers.length < limit ? planTowerAt(state, strategy) : null
    // 混塔策略始终给下一座计划塔留钱,避免把金币全砸在升级上、塔的种类铺不开
    const reserve = want && strategy === 'mixed' ? towerDef(want).cost : 0
    const next = nextUpgrade(state, strategy, reserve)
    if (next && command(state, { kind: 'upgrade', id: next.id }).ok) continue
    break
  }
  // 攒不出任何东西了,就别干等:提前召唤 (+5 金币)
  if (state.phase === 'prep' && state.wave < targetWaves) {
    const canBuild = state.towers.length < limit && state.gold >= 60
    const canUpgrade = state.towers.some((t) => t.level < 3 &&
      state.gold >= (t.level === 1 ? towerDef(t.kind).upgrade[0] : towerDef(t.kind).upgrade[1]))
    if (!canBuild && !canUpgrade) command(state, { kind: 'summon' })
  }
}

/**
 * 跑一局参考策略。stopWave 是「撑过第 n 波就停」,无尽模式用;
 * 普通关卡跑到结束。maxSeconds 兜底,防止数据写坏时测试死循环。
 */
export function simulate(levelId: number | 'endless', seed: number,
  opts: { maxSeconds?: number; stopWave?: number; dt?: number; strategy?: Strategy } = {}): SimResult {
  const level = levelByIdOrNull(levelId)
  if (!level) throw new Error(`没有这一关:${levelId}`)
  const strategy = opts.strategy ?? 'mixed'
  const maxSeconds = opts.maxSeconds ?? 900
  const dt = opts.dt ?? 0.1
  const targetWaves = opts.stopWave ?? (level.id === 'endless' ? 21 : level.waves.length)
  const state = newGame(level, seed)
  let survived = false
  let guard = 0
  while (!state.over && state.time < maxSeconds && guard++ < 200000) {
    botStep(state, targetWaves, strategy)
    advance(state, dt)
    if (opts.stopWave !== undefined && state.wave >= opts.stopWave && state.phase === 'prep' && !state.over) {
      survived = true
      break
    }
  }
  return {
    state, won: state.over === 'win', stars: state.stars, seconds: state.time, survived,
    built: state.towers.map((t) => t.kind),
  }
}

/** 固定种子跑一关(平衡调参用) */
export function runLevel(levelId: number | 'endless', seed = 12345,
  opts?: { stopWave?: number; maxSeconds?: number; strategy?: Strategy }): SimResult {
  return simulate(levelId, seed, opts)
}

/** 一局到现在的战报 */
export function summaryOf(state: GameState): ReturnType<typeof resultOf> {
  return resultOf(state)
}
