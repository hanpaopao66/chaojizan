// 单测共用的摆局面工具:把对局改成想要的样子,再调引擎/AI 的纯函数。
// (测试里直接改这份 JSON 是安全的:引擎不收传进来的引用,所有操作都从 clone 开始。)
import { newGame, placeMinion } from '../src/engine'
import type { GameState, Side, SideState } from '../src/types'

export const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T

/** 开一局:默认熔火工坊(玩家)对暮影集市(电脑),玩家先手 */
export function fresh(seed = 7, first: Side = 0): GameState {
  return newGame({ seed, hero0: 'forge', hero1: 'dusk', first }).state
}

export function patch(s: GameState, side: Side, p: Partial<SideState>): GameState {
  const n = clone(s)
  Object.assign(n.sides[side], p)
  return n
}

/** 把一边的场面换成这些随从;放了之后默认这回合就能攻击(攻击相关的用例方便) */
export function board(s: GameState, side: Side, ids: string[]): GameState {
  let n = clone(s)
  n.sides[side].board = []
  for (const id of ids) n = placeMinion(n, side, id)
  for (const m of n.sides[side].board) {
    m.sick = false
    m.attacks = 1
  }
  return n
}

/** 换手牌,顺手把能量补到够用 */
export function hand(s: GameState, side: Side, ids: string[], energy = 10): GameState {
  const n = patch(s, side, { hand: ids.slice(), energy })
  n.sides[side].maxEnergy = Math.max(n.sides[side].maxEnergy, energy)
  return n
}

export function setHp(s: GameState, side: Side, hp: number): GameState {
  return patch(s, side, { hp })
}

/** 直接把行动权交给某一边(AI 单测用) */
export function setTurn(s: GameState, side: Side): GameState {
  const n = clone(s)
  n.active = side
  return n
}

/** 清掉结束标记(摆一些已经结束的局面给 AI 时用) */
export function reopen(s: GameState): GameState {
  const n = clone(s)
  n.over = null
  return n
}
