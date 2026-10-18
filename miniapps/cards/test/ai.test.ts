// 电脑单测:每一步都必须是合法动作、能自己打完一局不把状态走坏、会斩杀、可复现、
// 困难档更会解场和保护自己。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { aiNext, findLethal } from '../src/ai'
import { applyAction, legalActions } from '../src/engine'
import type { Action, GameState, Level } from '../src/types'
import { board, clone, fresh, hand, setHp, setTurn } from './helpers'

const same = (a: Action, b: Action): boolean => JSON.stringify(a) === JSON.stringify(b)

/** 摆一个轮到电脑(1)的局面:手里有牌、能量够、场上有随从 */
function aiState(seed: number): GameState {
  let s = fresh(seed)
  s = hand(s, 1, ['f_bolt', 'pebble', 'scout', 'r_bless', 's_dancer'], 10)
  s = board(s, 1, ['spark', 'guard'])
  s = board(s, 0, ['scout'])
  s = setHp(s, 0, 22)
  s = setHp(s, 1, 16)
  return setTurn(s, 1)
}

const keys = (s: GameState): string => JSON.stringify(s)

/** 对局不变量:引擎不该产生这些状态 */
function assertSane(s: GameState): void {
  for (const side of s.sides) {
    assert.ok(side.board.length <= 7, '场上超过 7 个随从')
    assert.ok(side.hand.length <= 10, '手牌超过 10 张')
    assert.ok(side.hp >= 0 && side.hp <= 30, `英雄血量越界:${side.hp}`)
    assert.ok(side.energy >= 0 && side.energy <= side.maxEnergy, '当前能量超过上限')
    assert.ok(side.maxEnergy >= 0 && side.maxEnergy <= 10, '能量上限超过 10')
    for (const m of side.board) {
      assert.ok(m.health > 0, '场上有已经死掉的随从')
      assert.ok(m.attack >= 0 && m.health <= m.maxHealth, '随从身材不合法')
      assert.ok(m.attacks >= 0 && m.attacks <= 1, '随从攻击次数不合法')
    }
  }
  if (s.over) assert.ok(s.sides.some((side) => side.hp <= 0) || s.over.reason === 'quit')
}

test('AI 的每一步都是 legalActions 里的合法动作(两档难度、若干局面)', () => {
  for (const seed of [101, 103, 105]) {
    const s = aiState(seed)
    for (const level of ['normal', 'hard'] as Level[]) {
      const a = aiNext(s, level)
      const legal = legalActions(s)
      assert.ok(legal.some((x) => same(x, a)), `AI 选了非法动作:${JSON.stringify(a)}`)
    }
  }
})

test('AI 自己打完整局:不会产生非法状态,也不会卡死', () => {
  let s = aiState(201)
  let actions = 0
  let ended = false
  while (actions < 600) {
    if (s.over) {
      ended = true
      break
    }
    // 两边的行动都交给 AI(玩家那一边用标准档,电脑用困难档),这样一局能自己打完
    const level: Level = s.active === 1 ? 'hard' : 'normal'
    const a = aiNext(s, level)
    const r = applyAction(s, a)
    assert.ok(r.ok, `AI 第 ${actions} 步非法:${JSON.stringify(a)}:${r.ok ? '' : r.why}`)
    s = r.state
    assertSane(s)
    actions++
  }
  assert.ok(ended, `600 步内没打完(可能是死循环):${keys(s).slice(0, 200)}`)
})

test('斩杀:能一步打死就直接打脸;两步斩杀困难档算得到,标准档算不到', () => {
  // 一步斩杀
  let s = aiState(301)
  s = setHp(s, 0, 3)
  s = board(s, 1, ['giant'])
  s = setTurn(s, 1)
  const a = aiNext(s, 'hard')
  assert.equal(a.kind, 'attack')
  assert.ok(a.kind === 'attack' && a.target.kind === 'hero')
  const r = applyAction(s, a)
  assert.ok(r.ok)
  assert.equal(r.state.over?.winner, 1)
  // 两张 3 伤法术、对面 5 血:一步打不死、两步可以
  let t = fresh(303)
  t = setHp(t, 0, 5)
  t = hand(t, 1, ['f_bolt', 'f_bolt'], 10)
  t = board(t, 1, [])
  t = setTurn(t, 1)
  assert.notEqual(findLethal(t, 1, 'hard'), null, '困难档应该算到两步斩杀')
  assert.equal(findLethal(t, 1, 'normal'), null, '标准档只算一步')
  let seq = t
  for (let i = 0; i < 6 && !seq.over; i++) {
    const act = aiNext(seq, 'hard')
    const res = applyAction(seq, act)
    assert.ok(res.ok)
    seq = res.state
  }
  assert.equal(seq.over?.winner, 1, '困难档应该把这局斩杀')
})

test('AI 可复现:同一个局面、同样的难度,走出来的动作序列一样', () => {
  const run = (start: GameState, level: Level): Action[] => {
    let s = clone(start)
    const out: Action[] = []
    for (let i = 0; i < 12; i++) {
      if (s.over) break
      const a = aiNext(s, level)
      out.push(a)
      const r = applyAction(s, a)
      assert.ok(r.ok)
      s = r.state
      if (a.kind === 'end') break
    }
    return out
  }
  const s = aiState(401)
  assert.deepEqual(run(s, 'hard'), run(clone(s), 'hard'))
  assert.deepEqual(run(s, 'normal'), run(clone(s), 'normal'))
})

test('困难档:低血量时优先打出嘲讽随从保护自己;标准档更想抢脸', () => {
  let s = fresh(501)
  s = hand(s, 1, ['r_sentry', 'scout'], 5)
  s = board(s, 1, [])
  s = board(s, 0, [])
  s = setHp(s, 1, 8)
  s = setTurn(s, 1)
  const hard = aiNext(s, 'hard')
  const normal = aiNext(s, 'normal')
  assert.equal(hard.kind, 'play')
  assert.ok(hard.kind === 'play' && hard.hand === 0, '困难档应该先上嘲讽的霜线哨兵')
  assert.equal(normal.kind, 'play')
  assert.ok(normal.kind === 'play' && normal.hand === 1, '标准档应该先上攻击更高的风哨斥候')
})

test('困难档会用法术解掉对面的随从,标准档更愿意把伤害打到脸上', () => {
  let s = fresh(601)
  s = hand(s, 1, ['f_bolt'], 10)
  s = board(s, 1, [])
  s = board(s, 0, ['scout'])
  s = setTurn(s, 1)
  const hard = aiNext(s, 'hard')
  const normal = aiNext(s, 'normal')
  assert.equal(hard.kind, 'play')
  assert.ok(hard.kind === 'play' && hard.target?.kind === 'minion', '困难档应该解场')
  assert.equal(normal.kind, 'play')
  assert.ok(normal.kind === 'play' && normal.target?.kind === 'hero', '标准档应该打脸')
})

test('AI 没有好动作时会结束回合(不出没意义的牌)', () => {
  let s = fresh(701)
  s = hand(s, 1, ['f_bolt'], 1) // 能量不够
  s = board(s, 1, [])
  s = setTurn(s, 1)
  assert.equal(aiNext(s, 'hard').kind, 'end')
  // 场面和手牌都空:直接结束
  let t = fresh(703)
  t = hand(t, 1, [], 0)
  t = board(t, 1, [])
  t = setTurn(t, 1)
  assert.equal(aiNext(t, 'normal').kind, 'end')
})

test('斩杀里会先处理挡路的嘲讽:困难档能找到「先打嘲讽、再打脸」的连招', () => {
  let s = fresh(801)
  s = board(s, 1, ['scout', 'cart']) // 3/2 去换嘲讽,4/5 留着打脸
  s = board(s, 0, ['pebble']) // 2/3 嘲讽,挡路
  s = setHp(s, 0, 4) // 打破嘲讽后,旧货车的 4 点攻击正好打死英雄
  s = setTurn(s, 1)
  const first = findLethal(s, 1, 'hard')
  assert.ok(first && first.kind === 'attack' && first.target.kind === 'minion', '第一步应该先打嘲讽')
  let now = s
  for (let i = 0; i < 6 && !now.over; i++) {
    const a = aiNext(now, 'hard')
    const r = applyAction(now, a)
    assert.ok(r.ok)
    now = r.state
  }
  assert.equal(now.over?.winner, 1)
})
