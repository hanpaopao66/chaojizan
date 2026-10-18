import assert from 'node:assert/strict'
import { test } from 'node:test'
import { WORLD_H, WORLD_W, circleBlocked, parseMap, tileCenter, tileCol, tileRow } from '../src/map'
import { Difficulty } from '../src/combat'
import {
  BOMB_TIME, DEFUSE_TIME, FREEZE_TIME, GameEvent, PLAYER_HP, PlayerInput, ROUND_TIME, Round, accuracyOf, advance,
  canPlant, finishRound, newMatch, newRound, nextRound, playerSeesGuard,
} from '../src/match'

const map = parseMap()

const idle: PlayerInput = { moveX: 0, moveY: 0, aim: null, fire: false, reload: false, swap: false, interact: false }
const planting: PlayerInput = { ...idle, interact: true }

function run(round: Round, seconds: number, input: PlayerInput = idle, dt = 1 / 60): { round: Round; events: GameEvent[] } {
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

/** 跳过开场冻结,进入 live */
function liveRound(difficulty: Difficulty = 'normal', seed = 99): Round {
  const match = newMatch(difficulty, seed)
  return run(newRound(match, map), FREEZE_TIME + 0.2).round
}

function tileToColSafe(x: number): number { return tileCol(x) }

function clearGuards(round: Round): Round {
  for (const guard of round.guards) {
    guard.alive = false
    guard.hp = 0
  }
  return round
}

/** 玩家站在 A 点按住安放,直到炸弹安好 */
function plantedAtA(difficulty: Difficulty = 'normal', seed = 99): Round {
  const round = clearGuards(liveRound(difficulty, seed))
  round.player.pos = tileCenter(37, 4)
  const out = run(round, 3, planting).round
  assert.equal(out.bomb.state, 'planted')
  return out
}

test('回合流程:开场冻结 2 秒,之后 75 秒倒计时', () => {
  const round = newRound(newMatch('normal', 1), map)
  assert.equal(round.phase, 'freeze')
  assert.equal(round.clock, FREEZE_TIME)
  assert.equal(round.player.hp, PLAYER_HP)
  assert.equal(round.guards.length, 3)
  const frozen = run(round, 1).round
  assert.equal(frozen.phase, 'freeze', '1 秒时还动不了')
  const live = run(frozen, 1.2).round
  assert.equal(live.phase, 'live')
  assert.ok(live.clock < ROUND_TIME && live.clock > ROUND_TIME - 1, `活下来时还剩 ${live.clock} 秒`)
})

test('时间耗尽、炸弹没安放:守卫赢', () => {
  const round = clearGuards(liveRound())
  round.clock = 0.05
  const out = run(round, 0.2)
  assert.equal(out.round.phase, 'over')
  assert.deepEqual(out.round.over, { side: 'guard', reason: 'timeout' })
  assert.ok(out.events.some((e) => e.type === 'roundOver'))
})

test('安放炸弹:不在炸弹点安不了;在 A 点按住 2.5 秒才成;中途走开会重置', () => {
  // 不在点上的地方按住 3 秒
  const outside = clearGuards(liveRound())
  const no = run(outside, 3, planting).round
  assert.equal(no.bomb.state, 'carried')
  assert.equal(no.plants, 0)

  // 在 A 点按住:先有进度,满了才算安好
  const atA = clearGuards(liveRound())
  atA.player.pos = tileCenter(37, 4)
  const half = run(atA, 1.2, planting)
  assert.equal(half.round.bomb.state, 'planting')
  assert.ok(half.round.bomb.plant > 0.3 && half.round.bomb.plant < 0.7, `进度 ${half.round.bomb.plant}`)
  assert.ok(half.events.some((e) => e.type === 'planting'))
  const done = run(half.round, 0.3, planting)
  assert.equal(done.round.bomb.state, 'planting', '还差一点')
  assert.ok(done.round.bomb.plant > 0.55, `进度 ${done.round.bomb.plant}`)
  const fin = run(done.round, 1.4, planting)
  assert.equal(fin.round.bomb.state, 'planted')
  assert.equal(fin.round.plants, 1)
  assert.ok(fin.events.some((e) => e.type === 'plant'))
  assert.ok(fin.round.bomb.timer > BOMB_TIME - 1 && fin.round.bomb.timer <= BOMB_TIME, `炸弹计时 ${fin.round.bomb.timer}`)
  assert.ok(fin.round.bomb.pos)

  // 按住一半走开:进度清零
  const walkAway = clearGuards(liveRound())
  walkAway.player.pos = tileCenter(37, 4)
  const mid = run(walkAway, 1.2, planting).round
  assert.equal(mid.bomb.state, 'planting')
  mid.player.pos = { ...map.playerSpawn }
  const reset = run(mid, 0.2, planting).round
  assert.equal(reset.bomb.state, 'carried')
  assert.equal(reset.bomb.plant, 0)
})

test('能不能安放(canPlant):界面按钮和引擎共用同一个判断', () => {
  const round = liveRound()
  assert.equal(canPlant(round), false, '出生点不在炸弹点上')
  round.player.pos = tileCenter(37, 4)
  const onSite = run(round, 0.05).round
  assert.equal(onSite.player.site, 'A')
  assert.equal(canPlant(onSite), true)
  assert.equal(canPlant({ ...onSite, phase: 'freeze' }), false, '冻结阶段不能安')
  assert.equal(canPlant({ ...onSite, player: { ...onSite.player, alive: false } }), false, '死了不能安')
  assert.equal(canPlant({ ...onSite, bomb: { ...onSite.bomb, state: 'planting' } }), true, '正在安放时还成立')
  assert.equal(canPlant(plantedAtA()), false, '已经安好就不能再安')
})

test('炸弹 30 秒后爆炸:进攻方赢下这一回合', () => {
  const round = plantedAtA()
  const out = run(round, BOMB_TIME + 0.2, idle, 1 / 30)
  assert.equal(out.round.phase, 'over')
  assert.deepEqual(out.round.over, { side: 'player', reason: 'exploded' })
  assert.ok(out.events.some((e) => e.type === 'explode'))
  assert.ok(out.events.some((e) => e.type === 'beep'), '倒计时里有滴声')
  assert.equal(out.round.bomb.state, 'exploded')
})

test('守卫拆弹 5 秒成功:防守方赢下这一回合', () => {
  const round = plantedAtA()
  const bombPos = round.bomb.pos!
  // 玩家退回出生点,让一名守卫站到炸弹上拆
  round.player.pos = { ...map.playerSpawn }
  const guard = round.guards[0]
  guard.alive = true
  guard.hp = 100
  guard.pos = { ...bombPos }
  const out = run(round, DEFUSE_TIME + 4, idle, 1 / 30)
  assert.equal(out.round.phase, 'over')
  assert.deepEqual(out.round.over, { side: 'guard', reason: 'defused' })
  assert.ok(out.events.some((e) => e.type === 'defusing'))
  assert.equal(out.round.bomb.state, 'defused')
})

test('玩家阵亡:守卫赢;炸弹安放后的回合倒计时不再扣', () => {
  const dead = clearGuards(liveRound())
  dead.player.hp = 0
  const out = run(dead, 0.1)
  assert.equal(out.round.over?.side, 'guard')
  assert.equal(out.round.over?.reason, 'playerKilled')

  const planted = plantedAtA()
  const clock = planted.clock
  const later = run(planted, 3, idle).round
  assert.equal(later.clock, clock, '炸弹安放后回合计时停住')
})

test('守卫真的会开枪:同一间房里看见玩家,几秒内玩家掉血', () => {
  const round = run(newRound(newMatch('hard', 5), map), FREEZE_TIME + 0.2).round
  for (let i = 1; i < round.guards.length; i++) {
    round.guards[i].alive = false
    round.guards[i].hp = 0
  }
  const guard = round.guards[0]
  guard.pos = tileCenter(22, 12)
  guard.angle = Math.PI
  round.player.pos = tileCenter(18, 12)
  const out = run(round, 2.5, idle)
  const shots = out.events.filter((e) => e.type === 'shot' && e.team === 'guard')
  assert.ok(shots.length > 0, '守卫开过枪')
  assert.ok(out.round.player.hp < PLAYER_HP || out.round.over?.side === 'guard', '玩家挨了打')
})

test('比分:先赢 2 回合者获胜,数据累计;输了记 loss', () => {
  let match = newMatch('normal', 1)
  let round = newRound(match, map)
  round.over = { side: 'player', reason: 'exploded' }
  round.elapsed = 20
  round.player.kills = 2
  round.player.shots = 8
  round.player.hits = 4
  round.plants = 1
  match = finishRound(match, round)
  assert.equal(match.scorePlayer, 1)
  assert.equal(match.scoreGuard, 0)
  assert.equal(match.over, null)
  assert.deepEqual(match.stats, {
    kills: 2, shots: 8, hits: 4, plants: 1, seconds: 20, deaths: 0, pistolKills: 0, explodedWins: 1,
  })
  assert.deepEqual(match.lastRound, { side: 'player', reason: 'exploded', kills: 2, seconds: 20, planted: true })

  match = nextRound(match)
  assert.equal(match.round, 2)
  round = newRound(match, map)
  round.over = { side: 'player', reason: 'exploded' }
  match = finishRound(match, round)
  assert.equal(match.scorePlayer, 2)
  assert.equal(match.over, 'win')

  // 连输两回合就是 loss
  let lost = newMatch('hard', 9)
  for (let i = 0; i < 2; i++) {
    const r = newRound(lost, map)
    r.over = { side: 'guard', reason: 'defused' }
    lost = finishRound(lost, r)
    if (!lost.over) lost = nextRound(lost)
  }
  assert.equal(lost.over, 'loss')
  // 已经是结束的比赛再来一份结果也不会把比分弄乱
  const stale = { ...newRound(lost, map), over: { side: 'player' as const, reason: 'exploded' as const } }
  assert.equal(finishRound(lost, stale).scorePlayer, 0)
})

test('看得见才画:墙和视距决定玩家能不能发现守卫', () => {
  assert.equal(playerSeesGuard(map, map.playerSpawn, tileCenter(7, 13)), true, '同一间房里看得见')
  assert.equal(playerSeesGuard(map, tileCenter(10, 2), tileCenter(12, 2)), false, '隔着墙看不见')
  assert.equal(playerSeesGuard(map, tileCenter(10, 4), tileCenter(12, 4)), true, '从门里看得见')
  assert.equal(playerSeesGuard(map, map.playerSpawn, tileCenter(37, 4)), false, '太远 + 墙')
})

test('AI 合法性:推演 20 秒,人和守卫都不穿墙、不出界,而且同种子可复现', () => {
  const script = (i: number): PlayerInput => ({
    moveX: Math.sin(i / 45),
    moveY: Math.cos(i / 62),
    aim: (i % 97) / 97 * Math.PI * 2,
    fire: i % 25 < 5,
    reload: i === 500,
    swap: i === 700,
    interact: false,
  })
  const simulate = (): Round => {
    let round = liveRound('hard', 2024)
    for (let i = 0; i < 800; i++) {
      round = advance(round, 1 / 40, script(i)).round
      if (i % 10 === 0) {
        // 玩家:不在实心格子里,也在图内
        assert.equal(circleBlocked(map, round.player.pos.x, round.player.pos.y, 8), false, `第 ${i} 帧玩家卡进墙里`)
        for (const guard of round.guards) {
          if (!guard.alive) continue
          assert.equal(circleBlocked(map, guard.pos.x, guard.pos.y, 8), false, `第 ${i} 帧守卫 ${guard.id} 卡进墙里`)
          assert.ok(guard.pos.x > 0 && guard.pos.x < WORLD_W && guard.pos.y > 0 && guard.pos.y < WORLD_H)
          assert.ok(tileCol(guard.pos.x) >= 0 && tileToColSafe(guard.pos.x) < 44)
          assert.ok(tileRow(guard.pos.y) >= 0 && tileRow(guard.pos.y) < 26)
        }
      }
      if (round.phase === 'over') break
    }
    return round
  }
  const first = simulate()
  const second = simulate()
  assert.equal(first.phase, second.phase)
  assert.deepEqual(first.player.pos, second.player.pos)
  assert.deepEqual(first.guards.map((g) => g.pos), second.guards.map((g) => g.pos))
  assert.equal(first.rng, second.rng, '同种子、同操作,随机数状态一致')
})

test('三档难度:同一个站着不动、不开枪的假玩家,休闲档明显比困难档活得久', () => {
  /** 玩家站在中间走廊、守卫看得见的地方,不移动也不还手;返回活了多少秒(活满 40 秒算 40) */
  const survivalSeconds = (difficulty: Difficulty): number => {
    let round = run(newRound(newMatch(difficulty, 777), map), FREEZE_TIME + 0.2).round
    round.player.pos = tileCenter(18, 12)
    for (let i = 0; i < 40 * 40; i++) {
      round = advance(round, 1 / 40, idle).round
      if (round.phase === 'over') return round.elapsed
    }
    return 40
  }
  const casual = survivalSeconds('casual')
  const normal = survivalSeconds('normal')
  const hard = survivalSeconds('hard')
  assert.ok(hard < normal, `困难 ${hard.toFixed(1)}s 应该比标准 ${normal.toFixed(1)}s 更早出局`)
  assert.ok(casual > hard + 3, `休闲 ${casual.toFixed(1)}s 应该明显比困难 ${hard.toFixed(1)}s 活得久`)
  assert.ok(casual > 5, `休闲档也不该一露头就死:${casual.toFixed(1)}s`)
})

test('命中率:没开枪是 0,否则命中/开枪', () => {
  assert.equal(accuracyOf({ kills: 0, shots: 0, hits: 0, plants: 0, seconds: 0, deaths: 0, pistolKills: 0, explodedWins: 0 }), 0)
  assert.equal(accuracyOf({ kills: 0, shots: 10, hits: 4, plants: 0, seconds: 0, deaths: 0, pistolKills: 0, explodedWins: 0 }), 0.4)
})
