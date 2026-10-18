// 测试用的基准策略:一个「合理但不神」的玩家 —— 先用便宜的豆荚炮铺 14 个建造位,
// 然后有钱就从上往下升级;实在没处花就点提前召唤。每 0.1 秒思考一次。
// 平衡测试用它跑 12 关和无尽模式,验证关卡数据「可赢、且能 3 星」。
import { advance, command, newGame } from '../src/engine'
import { resultOf } from '../src/save'
import type { GameState } from '../src/types'
import { levelById, levelByIdOrNull } from '../src/levels'

/** 基准策略先铺多少座基础塔,铺完就升级 */
export const BUILD_LIMIT = 14
/** 最便宜的攻击塔(每关都有豆荚炮) */
const CHEAP = 'pea' as const

export interface SimResult {
  state: GameState
  won: boolean
  stars: number
  /** 在多少秒内结束/停止 */
  seconds: number
  /** 无尽模式是否撑到了目标波数 */
  survived: boolean
}

/** 一个「会花金币」的玩家:先铺塔,铺到上限就升级,实在没处花就提前召唤 */
function botStep(state: GameState, targetWaves: number): void {
  const level = levelById(state.levelId)
  const limit = Math.min(level.slots.length, BUILD_LIMIT)
  let guard = 0
  while (guard++ < 12) {
    const towers = state.towers.length
    // ① 铺塔(还没到上限、钱够)
    if (towers < limit && state.gold >= 60) {
      let slot = -1
      for (let i = 0; i < limit; i++) if (!state.towers.some((t) => t.slot === i)) { slot = i; break }
      if (slot >= 0 && command(state, { kind: 'build', slot, tower: CHEAP }).ok) continue
    }
    // ② 升级:先升等级最低的,同级先造的先升
    const next = state.towers.filter((t) => t.level < 3)
      .sort((a, b) => a.level - b.level || a.id - b.id)[0]
    if (next) {
      const cost = next.level === 1 ? 70 : 110
      if (state.gold >= cost && command(state, { kind: 'upgrade', id: next.id }).ok) continue
    }
    break
  }
  // 攒不出任何东西了,就别干等:提前召唤 (+5 金币)
  if (state.phase === 'prep' && state.wave < targetWaves) {
    const canBuild = state.towers.length < limit && state.gold >= 60
    const canUpgrade = state.towers.some((t) => t.level < 3 &&
      state.gold >= (t.level === 1 ? 70 : 110))
    if (!canBuild && !canUpgrade) command(state, { kind: 'summon' })
  }
}

/**
 * 跑一局基准策略。stopWave 是「撑过第 n 波就停」,无尽模式用;
 * 普通关卡跑到结束。maxSeconds 兜底,防止数据写坏时测试死循环。
 */
export function simulate(levelId: number | 'endless', seed: number,
  opts: { maxSeconds?: number; stopWave?: number; dt?: number } = {}): SimResult {
  const level = levelByIdOrNull(levelId)
  if (!level) throw new Error(`没有这一关:${levelId}`)
  const maxSeconds = opts.maxSeconds ?? 900
  const dt = opts.dt ?? 0.1
  const targetWaves = opts.stopWave ?? (level.id === 'endless' ? 21 : level.waves.length)
  const state = newGame(level, seed)
  let survived = false
  let guard = 0
  while (!state.over && state.time < maxSeconds && guard++ < 200000) {
    botStep(state, targetWaves)
    advance(state, dt)
    if (opts.stopWave !== undefined && state.wave >= opts.stopWave && state.phase === 'prep' && !state.over) {
      survived = true
      break
    }
  }
  return { state, won: state.over === 'win', stars: state.stars, seconds: state.time, survived }
}

/** 固定种子跑一关(平衡调参用) */
export function runLevel(levelId: number | 'endless', seed = 12345,
  opts?: { stopWave?: number; maxSeconds?: number }): SimResult {
  return simulate(levelId, seed, opts)
}

/** 一局到现在的战报 */
export function summaryOf(state: GameState): ReturnType<typeof resultOf> {
  return resultOf(state)
}
