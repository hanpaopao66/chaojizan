import assert from 'node:assert/strict'
import { test } from 'node:test'
import { GuardBrain, GuardContext, decideGuard, guardSeesPlayer, newBrain } from '../src/ai'
import { SKILLS } from '../src/combat'
import { parseMap, tileCenter } from '../src/map'

const map = parseMap()
const skill = SKILLS.normal

function makeBrain(col: number, row: number, face = Math.PI): GuardBrain {
  return newBrain(tileCenter(col, row), face, 42, 0)
}

function context(col: number, row: number, over: Partial<GuardContext> = {}): GuardContext {
  return {
    now: 10,
    pos: tileCenter(col, row),
    angle: Math.PI,
    seesPlayer: false,
    playerPos: tileCenter(5, 13),
    heard: null,
    bomb: { planted: false, pos: null, plantedFor: 0 },
    skill,
    ...over,
  }
}

test('守卫的视野:朝向 + 视距 + 墙;贴脸三格内背后也能感觉到', () => {
  // 中间走廊:守卫朝左,玩家在左边同一行
  assert.equal(guardSeesPlayer(map, tileCenter(25, 12), Math.PI, skill, tileCenter(22, 12)), true)
  // 朝右却站在背后远处:看不见
  assert.equal(guardSeesPlayer(map, tileCenter(25, 12), 0, skill, tileCenter(20, 12)), false)
  // 贴着背站着(3 格内)能感觉到
  assert.equal(guardSeesPlayer(map, tileCenter(25, 12), 0, skill, tileCenter(23, 12)), true)
  // 隔着第 11 列的墙
  assert.equal(guardSeesPlayer(map, tileCenter(10, 2), 0, skill, tileCenter(13, 2)), false)
  // 太远
  assert.equal(guardSeesPlayer(map, tileCenter(25, 12), Math.PI, skill, tileCenter(5, 13)), false)
})

test('看见玩家:先进交火状态,反应时间过了才扣扳机', () => {
  const brain = makeBrain(25, 12)
  const first = decideGuard(brain, context(25, 12, {
    seesPlayer: true, playerPos: tileCenter(22, 12),
  }), 7)
  assert.equal(first.intent.mode, 'engage')
  assert.equal(first.intent.fire, false, '刚看见不能立刻开枪')
  assert.ok(first.brain.alertAt > 10, '反应时间还没到')
  // 反应时间过了:想开火
  const later = decideGuard(first.brain, context(25, 12, {
    now: first.brain.alertAt + 0.01, seesPlayer: true, playerPos: tileCenter(22, 12),
  }), first.rng)
  assert.equal(later.intent.fire, true)
  assert.equal(later.intent.mode, 'engage')
  // 离得近就不压上,免得贴脸绕圈
  assert.equal(later.intent.moveTo, null)
})

test('听见枪声:去声音的位置调查', () => {
  const brain = makeBrain(25, 12)
  const noise = { pos: tileCenter(15, 12), kind: 'shot' as const, team: 'player' as const, at: 9.5 }
  const decision = decideGuard(brain, context(25, 12, { heard: noise }), 7)
  assert.equal(decision.intent.mode, 'investigate')
  assert.deepEqual(decision.intent.moveTo, noise.pos)
  assert.equal(decision.intent.fire, false)
  // 到了就原地扫视
  const arrived = decideGuard(decision.brain, context(15, 12, { heard: noise }), decision.rng)
  assert.equal(arrived.intent.mode, 'investigate')
  assert.equal(arrived.intent.moveTo, null)
})

test('炸弹安放:1–2 秒内决定去拆;玩家露头会先交火', () => {
  const brain = makeBrain(25, 12)
  const bomb = { planted: true, pos: tileCenter(37, 4), plantedFor: 2 }
  const first = decideGuard(brain, context(25, 12, { bomb }), 7)
  assert.ok(first.brain.defuseAt >= 11 && first.brain.defuseAt <= 12, `决定拆弹时间 ${first.brain.defuseAt}`)
  assert.notEqual(first.intent.mode, 'defuse', '还在反应延迟里')
  const later = decideGuard(first.brain, context(25, 12, { bomb, now: first.brain.defuseAt + 0.01 }), first.rng)
  assert.equal(later.intent.mode, 'defuse')
  assert.equal(later.intent.defuse, true)
  assert.deepEqual(later.intent.moveTo, bomb.pos)
  // 去拆的路上看见玩家:先交火
  const sees = decideGuard(later.brain, context(25, 12, {
    bomb, now: later.brain.defuseAt + 0.5, seesPlayer: true, playerPos: tileCenter(22, 12),
  }), later.rng)
  assert.equal(sees.intent.mode, 'engage')
  assert.equal(sees.intent.defuse, false)
})

test('刚看不见:去最后看见的位置找,4 秒后放弃回岗位', () => {
  const brain = makeBrain(25, 12)
  const spotted = decideGuard(brain, context(25, 12, {
    seesPlayer: true, playerPos: tileCenter(22, 12),
  }), 7)
  const hunt = decideGuard(spotted.brain, context(25, 12, { now: 10.5 }), spotted.rng)
  assert.equal(hunt.intent.mode, 'engage')
  assert.deepEqual(hunt.intent.moveTo, tileCenter(22, 12))
  // 超过 4 秒:回岗位
  const giveUp = decideGuard(hunt.brain, context(25, 12, { now: 15 }), hunt.rng)
  assert.equal(giveUp.intent.mode, 'hold')
})

test('啥也没发生:守点,原地左右看;同一局面决策可复现', () => {
  const brain = makeBrain(25, 12)
  const decision = decideGuard(brain, context(25, 12), 7)
  assert.equal(decision.intent.mode, 'hold')
  assert.equal(decision.intent.moveTo, null)
  assert.ok(Math.abs(decision.intent.lookAngle - Math.PI) <= 0.9 + 1e-9, '在岗位朝向附近扫视')
  const again = decideGuard(makeBrain(25, 12), context(25, 12), 7)
  assert.deepEqual(again.intent, decision.intent)
  assert.equal(again.rng, decision.rng)
})
