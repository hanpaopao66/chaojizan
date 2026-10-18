import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  DEG, RIFLE, SKILLS, aimWithSpread, canFire, fireGun, hitscan, newGun, reloading, spreadOf, startReload, tickGun,
} from '../src/combat'
import { angleTo, parseMap, tileCenter } from '../src/map'

const map = parseMap()
/** 中间那间房第 14 行走廊:左边到第 31 列墙之前都是通的(第 12 行在 31 列有一道门) */
const lane = (col: number) => tileCenter(col, 14)

test('枪:30 发弹匣、90 发备弹;打空、换弹 2 秒、从备弹补满', () => {
  let gun = newGun(RIFLE)
  assert.equal(gun.mag, 30)
  assert.equal(gun.reserve, 90)
  assert.equal(canFire(gun), true)
  for (let i = 0; i < 30; i++) gun = fireGun(gun, RIFLE)
  assert.equal(gun.mag, 0)
  assert.equal(canFire(gun), false, '空仓不能开')
  const same = startReload(gun, RIFLE)
  assert.equal(reloading(same), true)
  assert.equal(same.reloadLeft, 2)
  gun = tickGun(same, 2.5, RIFLE)
  assert.equal(gun.mag, 30, '换满')
  assert.equal(gun.reserve, 60, '备弹扣掉 30')
  assert.equal(reloading(gun), false)
  // 满弹匣不换弹
  assert.equal(startReload(gun, RIFLE), gun)
})

test('散布:连射越大越散,上限封顶;停火 0.25 秒后才恢复', () => {
  let gun = newGun(RIFLE)
  const base = spreadOf(gun, RIFLE)
  assert.ok(base > 0)
  for (let i = 0; i < 6; i++) gun = fireGun(gun, RIFLE)
  const hot = spreadOf(gun, RIFLE)
  assert.ok(hot > base + 3, `连射后 ${hot}° > 基础 ${base}°`)
  // 立刻走一小帧:还不恢复
  gun = tickGun(gun, 0.1, RIFLE)
  assert.equal(spreadOf(gun, RIFLE), hot)
  // 停 1 秒:恢复一部分
  gun = tickGun(gun, 1, RIFLE)
  assert.ok(spreadOf(gun, RIFLE) < hot)
  // 打空换弹之后散布也不会超过上限
  for (let i = 0; i < 40; i++) gun = fireGun(gun, RIFLE)
  assert.ok(spreadOf(gun, RIFLE) <= RIFLE.maxSpread)
})

test('hitscan:人挡在人前面先打人;墙在人前面先打墙;射程不够是空气', () => {
  const from = lane(20)
  const target = { id: 3, pos: lane(24), radius: 8 }
  // 第 31 列是墙,第 24 列在墙前面
  assert.equal(hitscan(map, from, 0, [], 2000).kind, 'wall')
  const hitTarget = hitscan(map, from, 0, [target], 2000)
  assert.equal(hitTarget.kind, 'target')
  if (hitTarget.kind === 'target') {
    assert.equal(hitTarget.id, 3)
    assert.ok(hitTarget.distance > 80 && hitTarget.distance < 100, `命中距离 ${hitTarget.distance}(打到圆边缘,比圆心近一个半径)`)
  }
  // 目标放到墙后面:先撞墙
  const behind = { id: 4, pos: tileCenter(33, 14), radius: 8 }
  const wall = hitscan(map, from, 0, [behind], 2000)
  assert.equal(wall.kind, 'wall')
  // 射程只有 50:还没到墙就停了
  assert.equal(hitscan(map, from, 0, [], 50).kind, 'air')
  // 背后的目标打不到
  assert.equal(hitscan(map, from, 0, [{ id: 5, pos: tileCenter(18, 14), radius: 8 }], 2000).kind, 'wall')
})

test('散布随机数:同种子可复现,落点在 ±spread 以内', () => {
  const a = aimWithSpread(0.5, 3, 123)
  const b = aimWithSpread(0.5, 3, 123)
  assert.equal(a.angle, b.angle)
  assert.equal(a.rng, b.rng, '随机数状态也一致')
  for (let seed = 1; seed < 200; seed++) {
    const shot = aimWithSpread(0, 4, seed)
    assert.ok(Math.abs(shot.angle) <= 4 * DEG + 1e-9)
  }
})

test('三档难度:反应/瞄准误差/视距/移动单调,固定种子下命中率 休闲 < 标准 < 困难', () => {
  const tiers = [SKILLS.casual, SKILLS.normal, SKILLS.hard]
  for (let i = 1; i < tiers.length; i++) {
    const low = tiers[i - 1]
    const high = tiers[i]
    assert.ok(high.reaction < low.reaction, `${high.id} 反应应该更快`)
    assert.ok(high.aimError < low.aimError, `${high.id} 应该更准`)
    assert.ok(high.viewRange > low.viewRange, `${high.id} 应该看得更远`)
    assert.ok(high.speed > low.speed, `${high.id} 应该走得更快`)
    assert.ok(high.turnSpeed > low.turnSpeed, `${high.id} 应该转身更快`)
  }
  // 三档共用同一把枪:玩家和守卫的伤害/弹匣/射速都不随难度变
  assert.equal(SKILLS.casual.id, 'casual')
  assert.equal(SKILLS.normal.id, 'normal')
  assert.equal(SKILLS.hard.id, 'hard')
  const shooter = lane(20)
  const target = lane(28)
  const aim = angleTo(shooter, target)
  const rate = (aimError: number, seed: number): number => {
    let rng = seed
    let hits = 0
    for (let i = 0; i < 400; i++) {
      const aimed = aimWithSpread(aim, RIFLE.baseSpread + aimError, rng)
      rng = aimed.rng
      const shot = hitscan(map, shooter, aimed.angle, [{ id: 0, pos: target, radius: 8 }], RIFLE.range)
      if (shot.kind === 'target') hits++
    }
    return hits / 400
  }
  const casual = rate(SKILLS.casual.aimError, 7)
  const normal = rate(SKILLS.normal.aimError, 7)
  const hard = rate(SKILLS.hard.aimError, 7)
  assert.ok(casual < normal, `休闲命中率 ${casual} 应低于标准 ${normal}`)
  assert.ok(normal < hard, `标准命中率 ${normal} 应低于困难 ${hard}`)
  assert.equal(hard, rate(SKILLS.hard.aimError, 7), '同种子结果一样')
})
