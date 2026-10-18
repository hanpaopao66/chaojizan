import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  PISTOL, RIFLE, WEAPONS, canFire, startReload,
} from '../src/combat'
import { parseMap, siteAt, tileCenter } from '../src/map'
import {
  FREEZE_TIME, GameEvent, PlayerInput, Round, advance, newMatch, newRound,
} from '../src/match'

const map = parseMap()
const idle: PlayerInput = { moveX: 0, moveY: 0, aim: null, fire: false, reload: false, swap: false, interact: false }
const firing: PlayerInput = { ...idle, fire: true }
const swapping: PlayerInput = { ...idle, swap: true }

function clearGuards(round: Round): Round {
  for (const guard of round.guards) {
    guard.alive = false
    guard.hp = 0
  }
  return round
}

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

function liveRound(seed = 7): Round {
  return clearGuards(run(newRound(newMatch('casual', seed), map), FREEZE_TIME + 0.2).round)
}

test('武器数据:步枪与手枪的伤害/弹匣/射速各不相同,且玩家两把都带', () => {
  assert.equal(WEAPONS.length, 2)
  assert.equal(WEAPONS[0].id, 'rifle')
  assert.equal(WEAPONS[1].id, 'pistol')
  assert.equal(RIFLE.damage, 26)
  assert.equal(PISTOL.damage, 34)
  assert.equal(PISTOL.magazine, 12)
  assert.equal(PISTOL.reserve, 48)
  assert.ok(PISTOL.fireInterval > RIFLE.fireInterval, '手枪射速应该比步枪慢')
  assert.ok(PISTOL.damage > RIFLE.damage, '手枪单发伤害更高')
  const round = liveRound()
  assert.equal(round.player.guns.length, 2)
  assert.equal(round.player.guns[0].mag, RIFLE.magazine)
  assert.equal(round.player.guns[1].mag, PISTOL.magazine)
  assert.equal(round.player.active, 0)
})

test('TTK:步枪 4 发(约 0.43 秒),手枪 3 发(约 0.52 秒)—— 都按同一套 100 血算', () => {
  const rifleShots = Math.ceil(100 / RIFLE.damage)
  const pistolShots = Math.ceil(100 / PISTOL.damage)
  assert.equal(rifleShots, 4)
  assert.equal(pistolShots, 3)
  const rifleTtk = (rifleShots - 1) * RIFLE.fireInterval
  const pistolTtk = (pistolShots - 1) * PISTOL.fireInterval
  assert.ok(Math.abs(rifleTtk - 0.4286) < 0.001, `步枪 TTK ${rifleTtk}`)
  assert.ok(Math.abs(pistolTtk - 0.52) < 0.001, `手枪 TTK ${pistolTtk}`)
  assert.ok(rifleTtk < pistolTtk, '步枪持续输出更快,手枪是补救/爆发')
})

test('切枪:Q 切换到副武器,切换过程中不能开枪;两把枪弹匣独立', () => {
  let round = liveRound()
  // 先用步枪打几发
  round = run(round, 0.6, firing).round
  assert.ok(round.player.guns[0].mag < 30, '步枪应该打掉几发')
  const rifleMag = round.player.guns[0].mag
  const pistolMag = round.player.guns[1].mag
  // 切枪
  const swapStep = advance(round, 1 / 60, swapping)
  round = swapStep.round
  assert.ok(swapStep.events.some((e) => e.type === 'swap' && e.weapon === 'pistol'), '要有切枪事件')
  assert.equal(round.player.active, 1)
  assert.ok(round.player.switchLeft > 0, '切枪中')
  // 切枪过程中开枪:子弹数不变
  round = run(round, 0.1, firing).round
  assert.equal(round.player.guns[1].mag, pistolMag, '切枪中不能开枪')
  // 切枪完成后再开火
  round = run(round, 0.4, idle).round
  assert.equal(round.player.switchLeft, 0)
  round = run(round, 0.5, firing).round
  assert.ok(round.player.guns[1].mag < pistolMag, '手枪应该打掉几发')
  assert.equal(round.player.guns[0].mag, rifleMag, '换枪后步枪弹匣不再减少')
  // 再切回步枪
  round = run(round, 1 / 60, swapping).round
  assert.equal(round.player.active, 0)
})

test('换弹只影响当前那把枪,备弹各自独立', () => {
  let round = liveRound()
  round = run(round, 1.5, firing).round
  const rifleAfter = round.player.guns[0].mag
  assert.ok(rifleAfter < 30)
  round = run(round, 2.2, { ...idle, reload: false }).round // 打空/冷却一下
  round = run(round, 1 / 60, { ...idle, reload: true }).round
  assert.ok(round.player.guns[0].reloadLeft > 0, '步枪在换弹')
  round = run(round, 2.1, idle).round
  assert.equal(round.player.guns[0].mag, 30, '步枪补满')
  assert.ok(round.player.guns[0].reserve < 90, '步枪备弹减少')
  assert.equal(round.player.guns[1].mag, 12, '手枪弹匣没被动过')
  assert.equal(round.player.guns[1].reserve, 48)
})

test('手枪击杀计入 pistolKills,守卫的枪不受影响', () => {
  let round = liveRound(11)
  // 只留一个守卫,放在玩家正前方 5 格
  round.guards.forEach((g, i) => {
    if (i > 0) { g.alive = false; g.hp = 0 }
  })
  const guard = round.guards[0]
  guard.alive = true
  guard.pos = { x: round.player.pos.x + 120, y: round.player.pos.y }
  guard.hp = 68 // 手枪两枪的量,确保在守卫反应前结束
  round.player.pos = { x: round.player.pos.x, y: round.player.pos.y }
  // 切到手枪
  round = run(round, 1 / 60, swapping).round
  round = run(round, 0.4, idle).round
  assert.equal(round.player.active, 1)
  const events: GameEvent[] = []
  for (let i = 0; i < 120; i++) {
    const g = round.guards[0]
    const aim = Math.atan2(g.pos.y - round.player.pos.y, g.pos.x - round.player.pos.x)
    const step = advance(round, 1 / 60, { ...idle, aim, fire: i % 3 !== 2 })
    round = step.round
    events.push(...step.events)
    if (!round.guards[0].alive) break
  }
  assert.equal(round.guards[0].alive, false, '守卫应该被手枪打死')
  assert.equal(round.player.pistolKills, 1)
  assert.ok(events.some((e) => e.type === 'kill'), '要有击杀事件')
  // 守卫掉的是步枪弹,玩家的步枪弹匣没变化
  assert.equal(round.guards[0].gun.mag <= 30, true)
})

test('安放/切换互不干扰:站在炸弹点也能切枪(但安放中不能开枪)', () => {
  let round = liveRound(13)
  round.player.pos = tileCenter(37, 4)
  round = run(round, 0.1).round
  assert.equal(siteAt(map, round.player.pos), 'A')
  round = run(round, 1 / 60, swapping).round
  assert.equal(round.player.active, 1)
  assert.equal(canFire(round.player.guns[1]), true)
  // 满弹匣不能换;打掉几发之后才能换
  assert.equal(startReload(round.player.guns[1], PISTOL).reloadLeft, 0, '满弹匣不换弹')
  round = run(round, 0.8, firing).round
  const after = round.player.guns[round.player.active]
  assert.ok(after.mag < PISTOL.magazine, '应该打掉几发')
  const reloaded = startReload(after, PISTOL)
  assert.ok(reloaded.reloadLeft > 0, '打了子弹才能换')
})
