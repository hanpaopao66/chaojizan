// 波次调度单测:出怪时间表、奖励、准备时间、血量成长、无尽模式生成。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  buildSpawns, endlessTotalUnits, endlessWave, hasBoss, hpScaleOf, prepForNext, prepOf,
  waveAt, waveReward, waveUnits, wavesOf,
} from '../src/waves'
import { bossHealthScale, endlessHealthScale, enemyDef, healthScale } from '../src/data'
import { ENDLESS, LEVELS, levelById, waveCount } from '../src/levels'
import type { WaveDef } from '../src/types'

test('出怪时间表:按延迟和间隔排好,数量对得上', () => {
  const wave: WaveDef = {
    groups: [
      { kind: 'worm', count: 3, gap: 1, delay: 0, path: 0 },
      { kind: 'flea', count: 2, gap: 0.5, delay: 2, path: 1 },
    ],
  }
  const spawns = buildSpawns(wave)
  assert.equal(spawns.length, 5)
  assert.deepEqual(spawns.map((s) => s.kind), ['worm', 'worm', 'worm', 'flea', 'flea'])
  const near = (a: number, b: number): void => { assert.ok(Math.abs(a - b) < 1e-3, `${a} 应该接近 ${b}`) }
  near(spawns[0].at, 0)
  near(spawns[1].at, 1)
  near(spawns[2].at, 2)
  near(spawns[3].at, 2)
  near(spawns[4].at, 2.5)
  assert.deepEqual(spawns.map((s) => s.path), [0, 0, 0, 1, 1])
  // 时间必须单调
  for (let i = 1; i < spawns.length; i++) assert.ok(spawns[i].at >= spawns[i - 1].at)
  assert.equal(waveUnits(wave), 5)
})

test('波次奖励 = 10 + 波次 × 2;清完一波的收益随波次涨', () => {
  assert.equal(waveReward(1), 12)
  assert.equal(waveReward(5), 20)
  assert.equal(waveReward(10), 30)
  assert.ok(waveReward(10) > waveReward(1))
})

test('准备时间:默认 3 秒,关卡可以单独写;Boss 波多给 1 秒', () => {
  assert.equal(prepOf(undefined), 3)
  assert.equal(prepOf({ groups: [] }), 3)
  assert.equal(prepOf({ groups: [], prep: 8 }), 8)
  const boss = levelById(4)
  const last = boss.waves[boss.waves.length - 1]
  assert.ok(prepForNext(boss, boss.waves.length) >= prepOf(last) + 1, 'Boss 波之前多留一点时间')
  assert.ok(prepForNext(boss, 1) >= 3)
  assert.equal(prepForNext(boss, boss.waves.length + 1), 0, '没有下一波了')
})

test('hasBoss 能认出 Boss 波;waveAt 按波次取数据,无尽模式现场生成', () => {
  assert.equal(hasBoss({ groups: [{ kind: 'boss', count: 1, gap: 1 }] }), true)
  assert.equal(hasBoss({ groups: [{ kind: 'worm', count: 5, gap: 1 }] }), false)
  for (const level of LEVELS) {
    assert.equal(waveAt(level, 1), level.waves[0])
    assert.equal(waveAt(level, level.waves.length), level.waves[level.waves.length - 1])
    assert.equal(waveAt(level, level.waves.length + 1).groups.length, 0, '越界波次是空波')
  }
  const e1 = waveAt(ENDLESS, 1)
  assert.ok(e1.groups.length > 0)
  assert.deepEqual(waveAt(ENDLESS, 1), waveAt(ENDLESS, 1))
})

test('血量成长:第 1 波 ×1;关卡越后、波次越后越硬;无尽模式更快', () => {
  assert.equal(hpScaleOf(1, 1), 1)
  assert.ok(hpScaleOf(1, 11) > hpScaleOf(1, 1))
  assert.ok(hpScaleOf(12, 11) > hpScaleOf(1, 11))
  assert.equal(hpScaleOf('endless', 1), 1)
  assert.equal(hpScaleOf('endless', 10), endlessHealthScale(10))
  assert.ok(hpScaleOf('endless', 20) > healthScale(20, 12))
  assert.equal(bossHealthScale(1), 1)
  for (const level of LEVELS) {
    for (let w = 1; w <= waveCount(level); w++) {
      const wave = waveAt(level, w)
      assert.ok(wave.groups.length > 0, `第 ${level.id} 关第 ${w} 波没有怪`)
    }
  }
})

test('无尽模式:每 5 波有 Boss,第 10 波起双入口,数量随波次增长', () => {
  const w1 = endlessWave(1)
  assert.ok(w1.groups.every((g) => g.kind === 'worm'), '第 1 波只有青虫')
  assert.equal(hasBoss(w1), false)
  assert.equal(hasBoss(endlessWave(5)), true)
  assert.equal(hasBoss(endlessWave(10)), true)
  assert.equal(hasBoss(endlessWave(6)), false)
  // 第 10 波起两条路都用上
  const w10 = endlessWave(10)
  assert.equal(new Set(w10.groups.map((g) => g.path || 0)).size, 2)
  assert.ok(waveUnits(w10) > waveUnits(w1))
  // 普通波(非 Boss 波)的出怪数量随波次增长
  let prev = 0
  for (let i = 2; i <= 20; i++) {
    if (hasBoss(endlessWave(i))) continue
    const units = waveUnits(endlessWave(i))
    assert.ok(units > prev, `第 ${i} 波比上一个普通波少`)
    prev = units
  }
  assert.ok(waveUnits(endlessWave(20)) > waveUnits(endlessWave(1)))
  // 出怪都还是认识的虫
  for (let i = 1; i <= 20; i++) {
    for (const g of endlessWave(i).groups) {
      assert.ok(enemyDef(g.kind))
      assert.ok(g.path === 0 || g.path === 1)
    }
  }
})

test('无尽模式 20 波的累计出怪量、波次列表可复现', () => {
  assert.ok(endlessTotalUnits(20) > endlessTotalUnits(10))
  const all = wavesOf(ENDLESS, 20)
  assert.equal(all.length, 20)
  all.forEach((wave, i) => {
    assert.equal(waveUnits(wave), waveUnits(endlessWave(i + 1)))
  })
  assert.deepEqual(wavesOf(ENDLESS, 20), wavesOf(ENDLESS, 20))
  // 普通关就取前 n 波
  assert.equal(wavesOf(levelById(1), 3).length, 3)
  assert.equal(wavesOf(levelById(1)).length, levelById(1).waves.length)
})
