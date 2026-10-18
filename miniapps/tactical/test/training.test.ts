import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseMap, siteAt, tileCenter } from '../src/map'
import {
  GameEvent, PlayerInput, Round, advance, canPlant, newMatch, newRound,
} from '../src/match'

const map = parseMap()
const idle: PlayerInput = { moveX: 0, moveY: 0, aim: null, fire: false, reload: false, swap: false, interact: false }
const planting: PlayerInput = { ...idle, interact: true }

function run(round: Round, seconds: number, input: PlayerInput = idle, dt = 1 / 30): { round: Round; events: GameEvent[] } {
  let r = round
  const events: GameEvent[] = []
  const steps = Math.ceil(seconds / dt)
  for (let i = 0; i < steps; i++) {
    const step = advance(r, dt, input)
    r = step.round
    events.push(...step.events)
  }
  return { round: r, events }
}

function trainingRound(seed = 5): Round {
  const match = newMatch('casual', seed, { training: true })
  return newRound(match, map)
}

test('训练场:直接开打、没有回合倒计时和胜负,也不能安放炸弹', () => {
  const round = trainingRound()
  assert.equal(round.training, true)
  assert.equal(round.phase, 'live')
  assert.equal(round.clock, 0)
  // 站到炸弹点上也安不了
  round.player.pos = tileCenter(37, 4)
  const step = run(round, 1)
  assert.equal(step.round.player.site, 'A')
  assert.equal(canPlant(step.round), false)
  const held = run(step.round, 3, planting).round
  assert.equal(held.bomb.state, 'carried')
  assert.equal(held.plants, 0)
})

test('训练场:守卫倒下 2.5 秒后在出生点满血复活', () => {
  let round = trainingRound()
  const guard = round.guards[0]
  const spawn = { ...guard.pos }
  guard.hp = 0
  guard.alive = false
  round = run(round, 0.1).round
  assert.ok(round.guards[0].respawnAt > round.elapsed, '安排复活时间')
  round = run(round, 3).round
  assert.equal(round.guards[0].alive, true)
  assert.equal(round.guards[0].hp, 100)
  assert.deepEqual(round.guards[0].pos, spawn)
  assert.equal(round.guards[0].respawnAt, 0)
})

test('训练场:玩家被击倒后 2 秒复活,比赛不会结束、不记阵亡到比赛', () => {
  const round = trainingRound()
  round.player.hp = 0
  const died = run(round, 0.2).round
  assert.equal(died.player.alive, false)
  assert.equal(died.player.deaths, 1)
  assert.equal(died.phase, 'live')
  assert.equal(died.over, null)
  const alive = run(died, 2.2).round
  assert.equal(alive.player.alive, true)
  assert.equal(alive.player.hp, 100)
  assert.deepEqual(alive.player.pos, map.playerSpawn)
})

test('训练场:推演 45 秒也不会出现回合结算,玩家/守卫位置始终合法', () => {
  let round = trainingRound()
  round.player.pos = tileCenter(20, 13)
  let sawDeath = false
  for (let i = 0; i < 45 * 30; i++) {
    const step = advance(round, 1 / 30, { ...idle, aim: 0, fire: i % 40 < 8 })
    round = step.round
    if (step.events.some((e) => e.type === 'death')) sawDeath = true
    if (i % 30 === 0) {
      assert.equal(round.phase, 'live')
      assert.equal(round.over, null)
      for (const g of round.guards) {
        if (!g.alive) continue
        const tile = siteAt(round.map, g.pos)
        assert.equal(tile === null || tile === 'A' || tile === 'B', true)
      }
    }
  }
  assert.equal(round.phase, 'live')
  assert.equal(round.over, null)
  assert.equal(round.bomb.state, 'carried')
  void sawDeath
})

test('普通模式不是训练场:newMatch 的 training 默认 false,回合会正常结束', () => {
  const match = newMatch('casual', 1)
  assert.equal(match.training, false)
  const round = newRound(match, map)
  assert.equal(round.training, false)
  assert.equal(round.phase, 'freeze')
})
