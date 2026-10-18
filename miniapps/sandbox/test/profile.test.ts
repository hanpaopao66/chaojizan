// 玩家档案(累计统计 + 成就):读写、合并语义、格式化。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  addStat, copyProfile, emptyProfile, formatDistance, formatDuration, isUnlocked, loadProfile, mergeProfile,
  profileOf, totalAchievements, unlock, unlockedCount,
} from '../src/profile'
import { ACHIEVEMENTS } from '../src/data'

test('空档案 / 读写往返 / 坏档返回 null', () => {
  const p = emptyProfile()
  assert.equal(p.v, 2)
  assert.equal(unlockedCount(p), 0)
  assert.deepEqual(loadProfile(JSON.parse(JSON.stringify(profileOf(p)))), p)
  assert.equal(loadProfile(null), null)
  assert.equal(loadProfile({ v: 9 }), null)
  assert.equal(loadProfile({ v: 2, mined: -1, placed: 0, walked: 0, seconds: 0, achievements: {} }), null)
  assert.equal(loadProfile({ v: 2, mined: 1, placed: 0, walked: 0, seconds: 0, achievements: [] }), null)
  // 旧版空的 best = {v:1} 当空档案
  assert.deepEqual(loadProfile({ v: 1 }), emptyProfile())
})

test('合并语义:统计取大、成就取并集且解锁时间取更早', () => {
  const a = emptyProfile()
  a.mined = 10
  a.placed = 3
  a.walked = 20
  a.seconds = 60
  unlock(a, 'first_mine', 5000)
  unlock(a, 'mine_100', 9000)
  const b = emptyProfile()
  b.mined = 7
  b.placed = 9
  b.walked = 100
  b.seconds = 30
  unlock(b, 'first_mine', 3000)
  unlock(b, 'first_place', 7000)
  const m = mergeProfile(a, b)
  assert.equal(m.mined, 10)
  assert.equal(m.placed, 9)
  assert.equal(m.walked, 100)
  assert.equal(m.seconds, 60)
  assert.equal(m.achievements.first_mine, 3000, '同一成就取更早的解锁时间')
  assert.equal(m.achievements.first_place, 7000)
  assert.equal(m.achievements.mine_100, 9000)
  assert.equal(unlockedCount(m), 3)
  // 合并不会改原对象
  assert.equal(unlockedCount(a), 2)
})

test('解锁与统计:重复解锁返回 false、不覆盖时间;统计不会负增长或溢出', () => {
  const p = emptyProfile()
  assert.equal(unlock(p, 'first_mine', 1000), true)
  assert.equal(unlock(p, 'first_mine', 2000), false)
  assert.equal(p.achievements.first_mine, 1000)
  assert.equal(unlock(p, 'not_a_real_achievement', 1), false)
  assert.equal(isUnlocked(p, 'first_mine'), true)
  addStat(p, 'mined', 3)
  addStat(p, 'walked', 1.2345)
  addStat(p, 'seconds', 0.1)
  addStat(p, 'mined', -5)
  assert.equal(p.mined, 3)
  assert.ok(Math.abs(p.walked - 1.2345) < 1e-9, '浮点先原样累计')
  addStat(p, 'mined', 1e12)
  assert.ok(p.mined <= 1e9)
  assert.equal(totalAchievements(), ACHIEVEMENTS.length)
})

test('拷贝是深拷贝:改副本不影响原件', () => {
  const a = emptyProfile()
  a.mined = 5
  unlock(a, 'first_mine', 1)
  const b = copyProfile(a)
  b.mined = 99
  unlock(b, 'first_place', 2)
  assert.equal(a.mined, 5)
  assert.equal(unlockedCount(a), 1)
  assert.equal(unlockedCount(b), 2)
})

test('统计文案:时长和距离的格式化读起来顺', () => {
  assert.equal(formatDuration(45), '45 秒')
  assert.equal(formatDuration(65), '1 分 5 秒')
  assert.equal(formatDuration(3600 + 125), '1 小时 2 分')
  assert.equal(formatDistance(999), '999 米')
  assert.equal(formatDistance(1234), '1.2 公里')
  assert.equal(formatDistance(-3), '0 米')
})
