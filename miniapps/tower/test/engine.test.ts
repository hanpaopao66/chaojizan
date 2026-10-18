// 引擎单测:移动/漏怪、索敌、伤害与护甲、持续伤害、减速/冻结、溅射、链电、
// 经济、波次调度、胜负星级、命令校验、帧率无关(dt 切分)。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  advance, applyBurn, applyFreeze, applyPoison, applySlow, command, dealDamage, newGame, posOf,
  spawnEnemy, starsOf,
} from '../src/engine'
import { loadGame, saveGame } from '../src/save'
import { STEP, pointAt } from '../src/data'
import { levelById, waveCount } from '../src/levels'
import { chainFrom, enemyPos, pickTarget, progressOf, slotPos } from '../src/targeting'
import { waveReward } from '../src/waves'
import type { GameState, Tower } from '../src/types'

function fresh(levelId: number | 'endless' = 1, seed = 1): GameState {
  return newGame(levelById(levelId), seed)
}

/** 把一局设成「正在打第 1 波」,方便直接测移动和攻击 */
function intoWave(state: GameState, wave = 1): void {
  state.phase = 'wave'
  state.wave = wave
  state.clock = 0
  state.spawns = []
  state.enemies = []
}

/** 找路线上离某个世界坐标最近的距离点(用来把虫放到塔旁边) */
function distNear(state: GameState, path: number, pos: { x: number; y: number }): number {
  const level = levelById(state.levelId)
  const poly = level.world.polys[path]
  const total = level.world.lens[path]
  let best = 0
  let bestD = Infinity
  for (let d = 0; d <= total; d += 6) {
    const p = pointAt(poly, d)
    const dd = Math.hypot(p.x - pos.x, p.y - pos.y)
    if (dd < bestD) {
      bestD = dd
      best = d
    }
  }
  return best
}

/** 造一座塔并返回它(测试里金钱给够) */
function build(state: GameState, slot: number, kind: Tower['kind']): Tower {
  state.gold = 5000
  const r = command(state, { kind: 'build', slot, tower: kind })
  assert.ok(r.ok, r.reason)
  const tower = state.towers[state.towers.length - 1]
  tower.cd = 0
  return tower
}

// ---------------------------------------------------------------- 移动 / 漏怪

test('地面虫沿路线走,走到西瓜就漏、扣 1 点 HP', () => {
  const state = fresh(1)
  intoWave(state)
  const level = levelById(1)
  const worm = spawnEnemy(state, 'worm', 0, level.world.lens[0] - 2)
  const hp = state.hp
  const progress = progressOf(worm)
  assert.ok(progress > 0.99)
  const events = advance(state, 0.2)
  assert.equal(state.enemies.length, 0, '走到终点的虫应该消失')
  assert.equal(state.hp, hp - 1)
  assert.equal(state.stats.leaks, 1)
  assert.ok(events.some((e) => e.e === 'leak'))
})

test('Boss 走到终点扣 5 点 HP', () => {
  const state = fresh(1)
  intoWave(state)
  spawnEnemy(state, 'boss', 0, levelById(1).world.lens[0] - 2)
  const hp = state.hp
  advance(state, 0.3)
  assert.equal(state.hp, hp - 5)
  assert.ok(state.stats.leaks >= 1)
})

test('飞行虫从入口直线飞向西瓜,进度按直线距离算', () => {
  const state = fresh(1)
  intoWave(state)
  const level = levelById(1)
  const moth = spawnEnemy(state, 'moth', 0, 0)
  const start = level.world.starts[0]
  assert.deepEqual(posOf(state, moth), start)
  advance(state, 0.5)
  const moved = posOf(state, moth)
  const straight = Math.hypot(level.world.target.x - start.x, level.world.target.y - start.y)
  assert.ok(Math.abs(moth.span - straight) < 1e-9, '飞行虫的总路程是直线距离')
  const t = moth.dist / straight
  assert.ok(Math.abs(moved.x - (start.x + (level.world.target.x - start.x) * t)) < 1e-6)
  assert.ok(Math.abs(moved.y - (start.y + (level.world.target.y - start.y) * t)) < 1e-6)
  assert.ok(progressOf(moth) > 0 && progressOf(moth) < 1)
})

// ---------------------------------------------------------------- 索敌 / 链电

test('索敌:打射程里走得最靠前的那只;同进度按 id 小的', () => {
  const state = fresh(1)
  intoWave(state)
  const a = spawnEnemy(state, 'worm', 0, 100)
  const b = spawnEnemy(state, 'worm', 0, 700)
  const c = spawnEnemy(state, 'worm', 0, 400)
  const level = levelById(1)
  const from = { x: level.world.target.x, y: level.world.target.y }
  const picked = pickTarget(level, state.enemies, from, 9999)
  assert.equal(picked?.id, b.id)
  const near = pickTarget(level, state.enemies, enemyPos(level, a), 30)
  assert.equal(near?.id, a.id)
  // 进度相同时按 id 小的
  const d = spawnEnemy(state, 'worm', 0, 200)
  const e = spawnEnemy(state, 'worm', 0, 200)
  assert.equal(pickTarget(level, [e, d], enemyPos(level, d), 10)?.id, d.id)
  void c
})

test('链电:从主目标跳向最近的、还没打过的虫', () => {
  const state = fresh(1)
  intoWave(state)
  const first = spawnEnemy(state, 'worm', 0, 300)
  spawnEnemy(state, 'worm', 0, 302)
  spawnEnemy(state, 'worm', 0, 304)
  spawnEnemy(state, 'worm', 0, 900)
  const level = levelById(1)
  const chained = chainFrom(level, state.enemies, first, 3, 80)
  assert.equal(chained.length, 2, '射程外的第四只不该被链到')
  assert.ok(chained[0].dist > first.dist)
})

// ---------------------------------------------------------------- 伤害 / 状态

test('普通伤害先减护甲(最少 1),穿甲无视护甲', () => {
  const state = fresh(1)
  intoWave(state)
  const beetle = spawnEnemy(state, 'beetle', 0, 200)
  const hp = beetle.hp
  dealDamage(state, beetle, 12, [])
  assert.equal(beetle.hp, hp - 8, '12 点伤害对 4 点护甲应该打 8')
  dealDamage(state, beetle, 12, [], { pierce: true })
  assert.equal(beetle.hp, hp - 20, '穿甲应该打满 12')
  dealDamage(state, beetle, 2, [])
  assert.equal(beetle.hp, hp - 21, '再小的伤害也至少打 1 点')
})

test('持续伤害(毒/灼烧)无视护甲', () => {
  const state = fresh(1)
  intoWave(state)
  const beetle = spawnEnemy(state, 'beetle', 0, 200)
  const hp = beetle.hp
  applyPoison(beetle, 6, state.time + 4)
  applyBurn(beetle, 4, state.time + 4)
  advance(state, 1)
  const lost = hp - beetle.hp
  assert.ok(lost > 9 && lost < 11, `毒 6 + 灼烧 4 一秒该掉 10 左右,实际 ${lost}`)
})

test('减速取最强,重复施加刷新持续时间', () => {
  const state = fresh(1)
  intoWave(state)
  const worm = spawnEnemy(state, 'worm', 0, 0)
  applySlow(worm, 0.3, state.time + 1)
  assert.ok(Math.abs(worm.slowFactor - 0.3) < 1e-9)
  applySlow(worm, 0.45, state.time + 2)
  assert.ok(Math.abs(worm.slowFactor - 0.45) < 1e-9)
  applySlow(worm, 0.2, state.time + 5)
  assert.ok(Math.abs(worm.slowFactor - 0.45) < 1e-9, '弱减速不能盖掉强减速')
  assert.ok(worm.slowUntil >= state.time + 5, '持续时间要刷新')
})

test('冻结期间不移动,解冻后继续走', () => {
  const state = fresh(1)
  intoWave(state)
  const worm = spawnEnemy(state, 'worm', 0, 100)
  applyFreeze(worm, state.time + 0.5)
  advance(state, 0.3)
  assert.equal(worm.dist, 100, '冻结时不该移动')
  advance(state, 0.5)
  assert.ok(worm.dist > 100, '解冻后要继续走')
})

test('溅射:火焰椒一发打到目标周围一圈', () => {
  const state = fresh(3)
  intoWave(state)
  const tower = build(state, 0, 'pepper')
  const from = slotPos(levelById(3), tower.slot)
  const d = distNear(state, 0, from)
  const a = spawnEnemy(state, 'worm', 0, d)
  const b = spawnEnemy(state, 'worm', 0, d + 4)
  const c = spawnEnemy(state, 'worm', 0, d - 4)
  const hp = [a.hp, b.hp, c.hp]
  advance(state, 0.05)
  assert.equal(a.hp, hp[0] - 14, '主目标吃满 14')
  assert.equal(b.hp, hp[1] - 14, '溅射到的也吃 14')
  assert.equal(c.hp, hp[2] - 14)
})

test('链电塔:闪电藤一发打三只,每跳伤害递减', () => {
  const state = fresh(7)
  intoWave(state)
  const tower = build(state, 0, 'vine')
  const from = slotPos(levelById(7), tower.slot)
  const d = distNear(state, 0, from)
  const targets = [0, 3, 6].map((off) => spawnEnemy(state, 'worm', 0, d + off))
  const hp = targets.map((e) => e.hp)
  advance(state, 0.05)
  // 主目标是走得最靠前的那只,链电每跳伤害 ×0.8
  const lost = targets.map((e, i) => hp[i] - e.hp).sort((a, b) => b - a)
  assert.ok(Math.abs(lost[0] - 20) < 1e-6)
  assert.ok(Math.abs(lost[1] - 16) < 1e-6)
  assert.ok(Math.abs(lost[2] - 12.8) < 1e-6)
})

test('毒蘑菇:孢子让目标周围的虫一起中毒', () => {
  const state = fresh(5)
  intoWave(state)
  const tower = build(state, 0, 'mushroom')
  const from = slotPos(levelById(5), tower.slot)
  const d = distNear(state, 0, from)
  const targets = [0, 6, 12].map((off) => spawnEnemy(state, 'worm', 0, d + off))
  advance(state, 0.05)
  for (const e of targets) assert.ok(e.poisonUntil > state.time, '溅射范围内都该中毒')
  const state2 = fresh(5)
  intoWave(state2)
  const tower2 = build(state2, 0, 'mushroom')
  const from2 = slotPos(levelById(5), tower2.slot)
  const d2 = distNear(state2, 0, from2)
  const far = spawnEnemy(state2, 'worm', 0, d2 + 200)
  advance(state2, 0.05)
  assert.ok(!(far.poisonUntil > state2.time), '离得太远的不该中毒')
})

test('治疗蛹给周围的虫回血', () => {
  const state = fresh(5)
  intoWave(state)
  const pupa = spawnEnemy(state, 'pupa', 0, 400)
  const worm = spawnEnemy(state, 'worm', 0, 402)
  worm.hp = 10
  advance(state, 0.5)
  assert.ok(worm.hp > 10, '治疗蛹应该把旁边的虫奶起来')
  assert.ok(worm.hp <= worm.maxHp)
  void pupa
})

test('分裂蚁死后分成两只小蚁;小蚁不会再分裂', () => {
  const state = fresh(1)
  intoWave(state)
  const ant = spawnEnemy(state, 'ant', 0, 400)
  dealDamage(state, ant, 999, [])
  assert.equal(state.enemies.length, 2)
  assert.ok(state.enemies.every((e) => e.kind === 'antling'))
  for (const e of state.enemies) dealDamage(state, e, 999, [])
  assert.equal(state.enemies.length, 0)
})

test('毒蘑菇 3 级:击杀时留一片毒云,让旁边的虫中毒', () => {
  const state = fresh(5)
  intoWave(state)
  const tower = build(state, 0, 'mushroom')
  state.gold = 5000
  command(state, { kind: 'upgrade', id: tower.id })
  command(state, { kind: 'upgrade', id: tower.id })
  assert.equal(tower.level, 3)
  const from = slotPos(levelById(5), tower.slot)
  const d = distNear(state, 0, from)
  const a = spawnEnemy(state, 'worm', 0, d)
  const b = spawnEnemy(state, 'worm', 0, d + 20)
  const events: Parameters<typeof dealDamage>[3] = []
  dealDamage(state, a, 999, events, { source: tower })
  assert.ok(events.some((e) => e.e === 'cloud'))
  assert.ok(b.poisonUntil > state.time, '旁边的虫该中毒')
})

// ---------------------------------------------------------------- 经济

test('击杀赏金进金币和统计', () => {
  const state = fresh(1)
  intoWave(state)
  const gold = state.gold
  const worm = spawnEnemy(state, 'worm', 0, 100)
  const events: Parameters<typeof dealDamage>[3] = []
  dealDamage(state, worm, 999, events)
  assert.equal(state.gold, gold + 6)
  assert.equal(state.stats.kills, 1)
  assert.equal(state.stats.goldEarned, 6)
  assert.ok(events.some((e) => e.e === 'kill' && e.bounty === 6))
})

test('清完一波:发波次奖励 + 金盏花产出', () => {
  const state = fresh(3)
  state.gold = 1000
  intoWave(state, 2)
  const tower = build(state, 0, 'marigold')
  assert.equal(tower.kind, 'marigold')
  const gold = state.gold
  advance(state, 0.1)
  assert.equal(state.wave, 2, '清完第 2 波,波次号等下一波真正开始才 +1')
  assert.equal(state.phase, 'prep')
  assert.ok(state.prep > 0)
  assert.equal(state.gold, gold + waveReward(2) + 30)
})

test('提前召唤:准备期一键开波,奖励 +5 金币', () => {
  const state = fresh(1)
  assert.equal(state.phase, 'prep')
  assert.equal(state.wave, 0)
  const gold = state.gold
  const r = command(state, { kind: 'summon' })
  assert.ok(r.ok)
  assert.equal(state.phase, 'wave')
  assert.equal(state.wave, 1)
  assert.equal(state.gold, gold + 5)
  assert.ok(state.spawns.length > 0, '开波后要排好出怪时间表')
})

test('卖塔返还总投入的 70%', () => {
  const state = fresh(1)
  state.gold = 500
  const r1 = command(state, { kind: 'build', slot: 0, tower: 'pea' })
  assert.ok(r1.ok)
  const tower = state.towers[0]
  state.gold = 200
  assert.ok(command(state, { kind: 'upgrade', id: tower.id }).ok)
  assert.equal(tower.invested, 130)
  const gold = state.gold
  assert.ok(command(state, { kind: 'sell', id: tower.id }).ok)
  assert.equal(state.gold, gold + 91)
  assert.equal(state.towers.length, 0)
  assert.equal(state.stats.sold, 1)
})

test('建塔/升级的校验:钱不够、塔没解锁、位置被占、满级都给出原因', () => {
  const state = fresh(1)
  state.gold = 10
  assert.equal(command(state, { kind: 'build', slot: 0, tower: 'pea' }).ok, false)
  assert.match(command(state, { kind: 'build', slot: 0, tower: 'pea' }).reason || '', /还差/)
  assert.match(command(state, { kind: 'build', slot: 0, tower: 'frost' }).reason || '', /解锁/)
  state.gold = 500
  assert.ok(command(state, { kind: 'build', slot: 0, tower: 'pea' }).ok)
  assert.match(command(state, { kind: 'build', slot: 0, tower: 'pea' }).reason || '', /已经有塔/)
  assert.equal(command(state, { kind: 'build', slot: 999, tower: 'pea' }).ok, false)
  const tower = state.towers[0]
  assert.ok(command(state, { kind: 'upgrade', id: tower.id }).ok)
  assert.ok(command(state, { kind: 'upgrade', id: tower.id }).ok)
  assert.equal(tower.level, 3)
  assert.match(command(state, { kind: 'upgrade', id: tower.id }).reason || '', /满级/)
  assert.equal(command(state, { kind: 'upgrade', id: 9999 }).ok, false)
  assert.equal(command(state, { kind: 'sell', id: 9999 }).ok, false)
})

// ---------------------------------------------------------------- 胜负 / 星级

test('星级:满血 3 星、剩余 60% 2 星、其余 1 星', () => {
  const state = fresh(1)
  state.hp = state.maxHp
  assert.equal(starsOf(state), 3)
  state.hp = Math.ceil(state.maxHp * 0.6)
  assert.equal(starsOf(state), 2)
  state.hp = 5
  assert.equal(starsOf(state), 1)
})

test('撑完最后一波就赢,星级写进状态', () => {
  const state = fresh(1)
  intoWave(state, waveCount(levelById(1)))
  state.hp = state.maxHp
  const events = advance(state, 0.1)
  assert.equal(state.over, 'win')
  assert.equal(state.phase, 'over')
  assert.equal(state.stars, 3)
  assert.ok(events.some((e) => e.e === 'win'))
})

test('大西瓜 HP 归零就输,之后不再推进', () => {
  const state = fresh(1)
  intoWave(state)
  state.hp = 1
  spawnEnemy(state, 'worm', 0, levelById(1).world.lens[0] - 2)
  advance(state, 0.3)
  assert.equal(state.over, 'lose')
  assert.equal(state.hp, 0)
  assert.equal(state.stars, 0)
  const time = state.time
  const events = advance(state, 1)
  assert.equal(events.length, 0)
  assert.equal(state.time, time)
})

// ---------------------------------------------------------------- 时间 / 暂停 / 倍速

test('暂停时不推进,取消暂停继续', () => {
  const state = fresh(1)
  command(state, { kind: 'pause', paused: true })
  const time = state.time
  assert.equal(advance(state, 1).length, 0)
  assert.equal(state.time, time)
  command(state, { kind: 'pause', paused: false })
  advance(state, 0.2)
  assert.ok(state.time > time)
})

test('2 倍速:同样的一帧推进双倍时间', () => {
  const a = fresh(1)
  const b = fresh(1)
  command(b, { kind: 'speed', speed: 2 })
  advance(a, 0.1)
  advance(b, 0.1)
  assert.ok(Math.abs(b.time - a.time * 2) < STEP, `2 倍速应该推进两倍:${b.time} vs ${a.time}`)
})

test('dt 切分一致:一次 0.6 秒和六次 0.1 秒结果一样(帧率无关)', () => {
  const a = fresh(1)
  const b = fresh(1)
  command(a, { kind: 'summon' })
  command(b, { kind: 'summon' })
  advance(a, 0.6)
  for (let i = 0; i < 6; i++) advance(b, 0.1)
  assert.equal(a.enemies.length, b.enemies.length)
  assert.ok(Math.abs(a.time - b.time) < 1e-9)
  const ea = a.enemies[0]
  const eb = b.enemies[0]
  assert.ok(ea && eb)
  assert.ok(Math.abs(ea.dist - eb.dist) < 1e-6, `位置应该一致:${ea.dist} vs ${eb.dist}`)
  assert.equal(a.gold, b.gold)
  assert.equal(a.hp, b.hp)
})

test('波次调度:开波后按时间表陆续出怪', () => {
  const state = fresh(1)
  command(state, { kind: 'summon' })
  assert.ok(state.spawns.length >= 5)
  const total = state.spawns.length
  advance(state, 0.5)
  assert.ok(state.enemies.length >= 1, '第一只应该已经出来了')
  assert.ok(state.spawns.length < total, '剩下的怪还在时间表里')
})

test('存档后再读档继续打:状态定死,两份读档结果完全一致', () => {
  const state = fresh(2)
  command(state, { kind: 'summon' })
  state.gold = 1000
  command(state, { kind: 'build', slot: 0, tower: 'pea' })
  advance(state, 3)
  const raw = JSON.parse(JSON.stringify(saveGame(state)))
  const a = loadGame(raw)
  const b = loadGame(raw)
  assert.ok(a && b)
  for (let i = 0; i < 15; i++) {
    const eventsA = advance(a, 0.2)
    const eventsB = advance(b, 0.2)
    assert.equal(eventsA.length, eventsB.length)
    assert.deepEqual(a, b)
  }
})
