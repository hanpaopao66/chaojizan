// 规则引擎单测:开局、能量、抽牌/疲劳、召唤上限、攻击合法性、圣盾、战吼/亡语、群伤、
// 死亡顺序、胜负、纯函数、合法动作。全部只看纯函数的状态和事件,不碰界面。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  applyAction, attackTargets, canAttackWith, canPlayCard, legalActions, playTargets, surrender,
} from '../src/engine'
import type { GameState, Side } from '../src/types'
import { board, clone, fresh, hand, patch, setHp } from './helpers'

const pass = (s: GameState): GameState => {
  const r = applyAction(s, { kind: 'end' })
  assert.ok(r.ok)
  return r.state
}

const enemyHero = { kind: 'hero', side: 1 } as const
const myHero = { kind: 'hero', side: 0 } as const

test('开局:双方 30 血,玩家先手,先手 4 张牌、后手 4 张牌,各剩 26 张牌库', () => {
  const s = fresh(1)
  assert.equal(s.turn, 1)
  assert.equal(s.active, 0)
  assert.deepEqual(s.sides.map((x) => x.hp), [30, 30])
  // 先手先摸 3 张、后手 4 张;第一回合开始再各抽 1 张 → 4 / 4
  assert.equal(s.sides[0].hand.length, 4)
  assert.equal(s.sides[1].hand.length, 4)
  assert.equal(s.sides[0].deck.length, 26)
  assert.equal(s.sides[1].deck.length, 26)
  assert.equal(s.sides[0].energy, 1)
  assert.equal(s.sides[0].maxEnergy, 1)
  assert.equal(s.sides[1].energy, 0)
  // 同一个种子开局完全一样
  assert.deepEqual(fresh(1), fresh(1))
})

test('回合:结束回合换边,对方能量 +1 并回满,新回合抽一张', () => {
  let s = fresh(3)
  const r = applyAction(s, { kind: 'end' })
  assert.ok(r.ok)
  s = r.state
  assert.equal(s.active, 1)
  assert.equal(s.turn, 2)
  assert.equal(s.sides[1].energy, 1)
  assert.equal(s.sides[1].maxEnergy, 1)
  assert.equal(s.sides[1].hand.length, 5) // 4 张开局 + 第 1 次抽牌
  assert.ok(r.events.some((e) => e.e === 'turn' && e.side === 1 && e.turn === 2))
  s = pass(s)
  assert.equal(s.active, 0)
  assert.equal(s.sides[0].maxEnergy, 2)
  assert.equal(s.sides[0].energy, 2)
})

test('能量:每回合上限 +1,最多 10,回合开始回满', () => {
  let s = fresh(5)
  s = hand(s, 0, ['spark'], 1)
  // 用掉一点能量,下回合开始时回满
  const r = applyAction(s, { kind: 'play', hand: 0, target: null })
  assert.ok(r.ok)
  assert.equal(r.state.sides[0].energy, 0)
  s = pass(pass(r.state))
  assert.equal(s.sides[0].energy, 2)
  for (let i = 0; i < 20; i++) s = pass(s)
  for (const side of [0, 1] as Side[]) assert.equal(s.sides[side].maxEnergy, 10)
  assert.equal(s.sides[s.active].energy, 10)
})

test('手牌上限 10:手里满了再抽,牌被烧掉(离开牌库、不进手牌)', () => {
  let s = fresh(9)
  s = hand(s, 0, ['spark', 'spark', 'spark', 'spark', 'spark', 'spark', 'spark', 'spark', 'spark', 'spark'])
  const deckBefore = s.sides[0].deck.length
  const r1 = applyAction(s, { kind: 'end' })
  assert.ok(r1.ok)
  const r2 = applyAction(r1.state, { kind: 'end' })
  assert.ok(r2.ok)
  assert.equal(r2.state.sides[0].hand.length, 10)
  assert.equal(r2.state.sides[0].deck.length, deckBefore - 1)
  assert.ok(r2.events.some((e) => e.e === 'burn' && e.side === 0))
})

test('疲劳:牌库抽空后每次抽牌受 1、2、3… 递增伤害;疲劳致死算对方赢', () => {
  let s = fresh(11)
  s = patch(s, 0, { deck: [] })
  const r1 = applyAction(s, { kind: 'end' })
  assert.ok(r1.ok)
  const r2 = applyAction(r1.state, { kind: 'end' })
  assert.ok(r2.ok)
  assert.equal(r2.state.sides[0].hp, 29)
  assert.equal(r2.state.sides[0].fatigue, 1)
  let t = r2.state
  t = pass(t)
  const r4 = applyAction(t, { kind: 'end' })
  assert.ok(r4.ok)
  assert.equal(r4.state.sides[0].hp, 27)
  assert.equal(r4.state.sides[0].fatigue, 2)
  // 只剩 1 血时疲劳直接结束对局
  const dying = patch(r4.state, 0, { deck: [], hp: 1 })
  const a = pass(dying)
  const b = applyAction(a, { kind: 'end' })
  assert.ok(b.ok)
  assert.equal(b.state.over?.winner, 1)
  assert.equal(b.state.over?.reason, 'fatigue')
})

test('场上最多 7 个随从:满了再出随从会被拒绝并说明原因', () => {
  let s = fresh(13)
  s = board(s, 0, ['spark', 'spark', 'spark', 'spark', 'spark', 'spark', 'spark'])
  s = hand(s, 0, ['spark'])
  assert.equal(s.sides[0].board.length, 7)
  const chk = canPlayCard(s, 0, 0)
  assert.equal(chk.ok, false)
  assert.match(chk.why, /7/)
  assert.equal(applyAction(s, { kind: 'play', hand: 0, target: null }).ok, false)
})

test('能量不够、不轮到你、目标不对:出牌被拒绝且原因可读', () => {
  let s = fresh(15)
  s = hand(s, 0, ['warhammer'], 3) // 5 费
  assert.equal(canPlayCard(s, 0, 0).ok, false)
  assert.equal(canPlayCard(s, 1, 0).why, '还没轮到你')
  // 需要目标但不给目标
  s = hand(s, 0, ['f_ember'], 10)
  assert.deepEqual(playTargets(s, 0, 0), [enemyHero])
  assert.equal(applyAction(s, { kind: 'play', hand: 0, target: null }).ok, false)
  // 伤害牌不能打自己人
  assert.equal(applyAction(s, { kind: 'play', hand: 0, target: myHero }).ok, false)
  // 不是自己的回合不能结束回合之外的动作
  assert.equal(applyAction(s, { kind: 'attack', uid: 1, target: enemyHero }).ok, false)
})

test('出随从:扣能量、进场;非冲锋当回合不能攻击,下一回合可以', () => {
  let s = fresh(17)
  s = hand(s, 0, ['scout'], 10)
  const r = applyAction(s, { kind: 'play', hand: 0, target: null })
  assert.ok(r.ok)
  s = r.state
  assert.equal(s.sides[0].energy, 8)
  assert.equal(s.sides[0].board.length, 1)
  assert.equal(s.sides[0].played, 1)
  const scout = s.sides[0].board[0]
  assert.equal(scout.sick, true)
  assert.equal(canAttackWith(s, 0, scout.uid).ok, false)
  s = pass(pass(s)) // 转一圈回到自己
  assert.equal(s.sides[0].board[0].sick, false)
  assert.equal(canAttackWith(s, 0, s.sides[0].board[0].uid).ok, true)
})

test('冲锋:上场的当回合就能打', () => {
  let s = fresh(19)
  s = hand(s, 0, ['s_dancer'], 10)
  const r = applyAction(s, { kind: 'play', hand: 0, target: null })
  assert.ok(r.ok)
  s = r.state
  const dancer = s.sides[0].board[0]
  assert.equal(dancer.sick, false)
  assert.equal(canAttackWith(s, 0, dancer.uid).ok, true)
})

test('攻击:双方同时互相扣血;每个随从每回合只能攻击一次', () => {
  let s = fresh(21)
  s = board(s, 0, ['cart']) // 4/5
  s = board(s, 1, ['spark', 'scout'])
  const atk = s.sides[0].board[0]
  const def = s.sides[1].board[0]
  const r = applyAction(s, { kind: 'attack', uid: atk.uid, target: { kind: 'minion', side: 1, uid: def.uid } })
  assert.ok(r.ok)
  s = r.state
  // 4/5 打 1/2:星火萤死,旧货车吃 1 点还剩 4 血
  assert.equal(s.sides[1].board.length, 1)
  assert.equal(s.sides[0].board[0].health, 4)
  assert.ok(r.events.some((e) => e.e === 'attack' && e.toTarget === 4 && e.toSelf === 1))
  assert.ok(r.events.some((e) => e.e === 'death' && e.side === 1))
  // 已经攻击过的随从不能再打
  assert.equal(canAttackWith(s, 0, atk.uid).ok, false)
  assert.match(canAttackWith(s, 0, atk.uid).why, /攻击过/)
  assert.equal(applyAction(s, { kind: 'attack', uid: atk.uid, target: enemyHero }).ok, false)
  // 双方同时死亡:都从场上移除
  let m = fresh(22)
  m = board(m, 0, ['scout'])
  m = board(m, 1, ['scout'])
  const r2 = applyAction(m, { kind: 'attack', uid: m.sides[0].board[0].uid, target: { kind: 'minion', side: 1, uid: m.sides[1].board[0].uid } })
  assert.ok(r2.ok)
  assert.equal(r2.state.sides[0].board.length, 0)
  assert.equal(r2.state.sides[1].board.length, 0)
  // 不会留下「已经死了」的随从
  assert.equal(r2.state.sides[0].board.find((x) => x.health <= 0), undefined)
})

test('嘲讽:对面有嘲讽时只能先打嘲讽,打英雄被拒绝', () => {
  let s = fresh(23)
  s = board(s, 0, ['scout'])
  s = board(s, 1, ['pebble', 'spark'])
  const atk = s.sides[0].board[0].uid
  const pebble = s.sides[1].board[0].uid
  const targets = attackTargets(s, 0, atk)
  assert.deepEqual(targets, [{ kind: 'minion', side: 1, uid: pebble }])
  const bad = applyAction(s, { kind: 'attack', uid: atk, target: enemyHero })
  assert.ok(!bad.ok)
  assert.match(bad.why, /嘲讽/)
  const good = applyAction(s, { kind: 'attack', uid: atk, target: targets[0] })
  assert.ok(good.ok)
})

test('圣盾:免疫第一次伤害并破盾,第二次正常掉血', () => {
  let s = fresh(25)
  s = board(s, 1, ['shell'])
  s = hand(s, 0, ['f_bolt', 'f_bolt'], 10)
  const shell = s.sides[1].board[0]
  const target = { kind: 'minion', side: 1, uid: shell.uid } as const
  const r1 = applyAction(s, { kind: 'play', hand: 0, target })
  assert.ok(r1.ok)
  let now = r1.state
  assert.equal(now.sides[1].board[0].health, 3)
  assert.equal(now.sides[1].board[0].shield, false)
  assert.ok(r1.events.some((e) => e.e === 'shield'))
  const r2 = applyAction(now, { kind: 'play', hand: 0, target })
  assert.ok(r2.ok)
  now = r2.state
  assert.equal(now.sides[1].board[0], undefined) // 3 血吃 3 点死
})

test('战吼:伤害要选目标、自增益不用选、抽牌真的抽到牌', () => {
  // 火舌学徒:战吼 1 点伤害(打敌方英雄)
  let s = fresh(27)
  s = hand(s, 0, ['f_ember'], 1)
  const r = applyAction(s, { kind: 'play', hand: 0, target: enemyHero })
  assert.ok(r.ok)
  assert.equal(r.state.sides[1].hp, 29)
  assert.equal(r.state.sides[0].board[0].card, 'f_ember')
  // 夜巡枭:战吼 +2/+1 加自己
  s = hand(fresh(29), 0, ['owl'], 3)
  const r2 = applyAction(s, { kind: 'play', hand: 0, target: null })
  assert.ok(r2.ok)
  const owl = r2.state.sides[0].board[0]
  assert.deepEqual([owl.attack, owl.health, owl.maxHealth], [4, 3, 3])
  // 织星雀:战吼抽一张
  s = hand(fresh(31), 0, ['starling'], 2)
  const deckBefore = s.sides[0].deck.length
  const r3 = applyAction(s, { kind: 'play', hand: 0, target: null })
  assert.ok(r3.ok)
  assert.equal(r3.state.sides[0].deck.length, deckBefore - 1)
  assert.equal(r3.state.sides[0].hand.length, 1)
})

test('亡语:死亡时触发(对英雄伤害 / 召唤),死亡顺序固定', () => {
  // 烬火傀儡和风哨斥候对撞,双方都死;亡语打敌方英雄 2 点
  let s = fresh(33)
  s = board(s, 0, ['f_ash'])
  s = board(s, 1, ['scout'])
  const r = applyAction(s, { kind: 'attack', uid: s.sides[0].board[0].uid, target: { kind: 'minion', side: 1, uid: s.sides[1].board[0].uid } })
  assert.ok(r.ok)
  assert.equal(r.state.sides[1].hp, 28)
  const deaths = r.events.filter((e) => e.e === 'death')
  assert.deepEqual(deaths.map((e) => (e.e === 'death' ? e.side : -1)), [0, 1])
  // 双生灯灵死亡时召唤一个灯苗
  s = fresh(35)
  s = board(s, 0, ['twin'])
  s = board(s, 1, ['cart'])
  const r2 = applyAction(s, { kind: 'attack', uid: s.sides[0].board[0].uid, target: { kind: 'minion', side: 1, uid: s.sides[1].board[0].uid } })
  assert.ok(r2.ok)
  assert.equal(r2.state.sides[0].board.length, 1)
  assert.equal(r2.state.sides[0].board[0].card, 'wisp')
  assert.ok(r2.events.some((e) => e.e === 'summon' && e.side === 0))
})

test('群体伤害:只打敌方随从,不伤自己人;死亡按从左到右结算', () => {
  let s = fresh(37)
  s = board(s, 0, ['spark'])
  s = board(s, 1, ['pebble', 'scout', 'spark'])
  s = hand(s, 0, ['f_rain'], 10)
  const r = applyAction(s, { kind: 'play', hand: 0, target: null })
  assert.ok(r.ok)
  assert.equal(r.state.sides[1].board.length, 1) // 3/2 和 1/2 都死了,2/3 剩 1 血
  assert.equal(r.state.sides[1].board[0].card, 'pebble')
  assert.equal(r.state.sides[1].board[0].health, 1)
  assert.equal(r.state.sides[0].board.length, 1)
  assert.equal(r.state.sides[0].board[0].health, 2)
  const deaths = r.events.filter((e) => e.e === 'death')
  // 从左到右:碎岩兵没死,风哨斥候先死、星火萤后死
  assert.deepEqual(deaths.map((e) => (e.e === 'death' ? e.card : '')), ['scout', 'spark'])
})

test('治疗与加攻:治疗不超上限,加攻同时加生命上限', () => {
  let s = fresh(39)
  s = setHp(s, 0, 20)
  s = hand(s, 0, ['medic'], 3)
  const r = applyAction(s, { kind: 'play', hand: 0, target: myHero })
  assert.ok(r.ok)
  assert.equal(r.state.sides[0].hp, 23)
  // 29 血吃 3 点治疗只回到 30
  s = setHp(s, 0, 29)
  const r2 = applyAction(s, { kind: 'play', hand: 0, target: myHero })
  assert.ok(r2.ok)
  assert.equal(r2.state.sides[0].hp, 30)
  // 凛冬祝福 +2/+2
  s = board(fresh(41), 0, ['scout'])
  s = hand(s, 0, ['r_bless'], 2)
  const uid = s.sides[0].board[0].uid
  const r3 = applyAction(s, { kind: 'play', hand: 0, target: { kind: 'minion', side: 0, uid } })
  assert.ok(r3.ok)
  const m = r3.state.sides[0].board[0]
  assert.deepEqual([m.attack, m.health, m.maxHealth], [5, 4, 4])
})

test('胜负:英雄归零即结束,血量不会扣成负数;亡语打死对面也算赢', () => {
  let s = fresh(43)
  s = board(s, 0, ['scout'])
  s = setHp(s, 1, 3)
  const r = applyAction(s, { kind: 'attack', uid: s.sides[0].board[0].uid, target: enemyHero })
  assert.ok(r.ok)
  assert.equal(r.state.over?.winner, 0)
  assert.equal(r.state.over?.reason, 'hp')
  assert.equal(r.state.sides[1].hp, 0)
  // 攻击溢出不显示负数
  let t = fresh(45)
  t = board(t, 0, ['giant'])
  t = setHp(t, 1, 2)
  const r2 = applyAction(t, { kind: 'attack', uid: t.sides[0].board[0].uid, target: enemyHero })
  assert.ok(r2.ok)
  assert.equal(r2.state.sides[1].hp, 0)
  // 烬火傀儡撞死,亡语把只剩 2 血的对面英雄带走
  let u = fresh(47)
  u = board(u, 0, ['f_ash'])
  u = board(u, 1, ['scout'])
  u = setHp(u, 1, 2)
  const r3 = applyAction(u, { kind: 'attack', uid: u.sides[0].board[0].uid, target: { kind: 'minion', side: 1, uid: u.sides[1].board[0].uid } })
  assert.ok(r3.ok)
  assert.equal(r3.state.over?.winner, 0)
})

test('认输:对局结束、对方赢;已经结束的对局不能再操作', () => {
  const s = fresh(49)
  const r = surrender(s, 0)
  assert.ok(r.ok)
  assert.equal(r.state.over?.winner, 1)
  assert.equal(r.state.over?.reason, 'quit')
  assert.equal(applyAction(r.state, { kind: 'end' }).ok, false)
  assert.equal(canPlayCard(r.state, 1, 0).ok, false)
})

test('纯函数:动作不改传进来的对局,同样的输入得到同样的输出', () => {
  const s = fresh(51)
  s.sides[0].hand = ['f_bolt']
  s.sides[0].energy = 10
  const before = JSON.stringify(s)
  const r = applyAction(s, { kind: 'play', hand: 0, target: enemyHero })
  assert.ok(r.ok)
  assert.equal(JSON.stringify(s), before, '传进来的对局被改了')
  const same = applyAction(clone(s), { kind: 'play', hand: 0, target: enemyHero })
  assert.ok(same.ok)
  assert.deepEqual(r.state, same.state)
})

test('legalActions:当前能做的每个动作执行起来都合法(若干局面)', () => {
  const states: GameState[] = [fresh(61)]
  let b = fresh(63)
  b = board(b, 0, ['scout', 'pebble'])
  b = board(b, 1, ['spark'])
  b = hand(b, 0, ['f_bolt', 'r_bless', 's_dancer', 'starling', 'spark'], 10)
  states.push(b)
  let c = fresh(65)
  c = hand(c, 0, ['f_bolt', 'medic', 'guard'], 10)
  states.push(c)
  for (const s of states) {
    const acts = legalActions(s)
    assert.ok(acts.length > 0)
    assert.ok(acts.some((a) => a.kind === 'end'))
    for (const a of acts) {
      const r = applyAction(clone(s), a)
      assert.ok(r.ok, `动作不合法:${JSON.stringify(a)}:${r.ok ? '' : r.why}`)
      // 执行后的不变量
      assert.ok(r.state.sides.every((side) => side.board.length <= 7 && side.hand.length <= 10))
      for (const side of r.state.sides) {
        assert.ok(side.hp >= 0 && side.hp <= 30)
        assert.ok(side.energy >= 0 && side.energy <= side.maxEnergy)
        assert.ok(side.energy <= 10)
      }
      assert.ok(r.state.nextUid > 0)
    }
  }
})
