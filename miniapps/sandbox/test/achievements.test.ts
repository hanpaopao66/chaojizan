// 成就判定:统计型阈值、条件型(高度/地形/连击/满热栏/夜挖/游泳)、只解锁一次。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  BIOME_ALL, BIOME_GRASS, BIOME_SAND, BIOME_STONE, achievementProgress, checkAchievements, emptyContext, met,
} from '../src/achievements'
import { ACHIEVEMENTS } from '../src/data'
import { emptyProfile, unlockedCount } from '../src/profile'

const def = (id: string) => ACHIEVEMENTS.find((a) => a.id === id)!

function ctx(over: Partial<ReturnType<typeof emptyContext>> = {}): ReturnType<typeof emptyContext> {
  return { ...emptyContext(), inv: new Array(9).fill(0), ...over }
}

test('统计型:第一次挖/放、100/1000 块阈值是「达到就解锁」', () => {
  const p = emptyProfile()
  const c = ctx()
  assert.deepEqual(checkAchievements(p, c, 1000).map((a) => a.id), [], '还没挖就不解锁')
  p.mined = 1
  let got = checkAchievements(p, c, 2000).map((a) => a.id)
  assert.deepEqual(got, ['first_mine'])
  assert.equal(p.achievements.first_mine, 2000)
  p.mined = 99
  assert.deepEqual(checkAchievements(p, c, 3000).map((a) => a.id), [], '99 块还差一点')
  p.mined = 100
  assert.deepEqual(checkAchievements(p, c, 4000).map((a) => a.id), ['mine_100'])
  p.mined = 1000
  assert.deepEqual(checkAchievements(p, c, 5000).map((a) => a.id), ['mine_1000'])
  assert.equal(unlockedCount(p), 3)
  // 已解锁的不会重复解锁
  assert.deepEqual(checkAchievements(p, c, 6000).map((a) => a.id), [])
})

test('统计型:放 1 / 500、走 500 米、玩 30 分钟', () => {
  const p = emptyProfile()
  const c = ctx()
  p.placed = 1
  assert.deepEqual(checkAchievements(p, c, 1).map((a) => a.id), ['first_place'])
  p.placed = 500
  assert.deepEqual(checkAchievements(p, c, 2).map((a) => a.id), ['place_500'])
  p.walked = 500
  assert.deepEqual(checkAchievements(p, c, 3).map((a) => a.id), ['walk_500'])
  p.seconds = 1800
  assert.deepEqual(checkAchievements(p, c, 4).map((a) => a.id), ['time_30'])
})

test('条件型:站到 40 格高、三种地形、满热栏', () => {
  const p = emptyProfile()
  assert.equal(met(def('tower40'), p, ctx({ maxY: 39 })), false)
  assert.equal(met(def('tower40'), p, ctx({ maxY: 40 })), true)
  assert.deepEqual(checkAchievements(p, ctx({ maxY: 40 }), 10).map((a) => a.id), ['tower40'])
  assert.equal(met(def('biomes3'), p, ctx({ biomeMask: BIOME_GRASS | BIOME_SAND })), false)
  assert.equal(met(def('biomes3'), p, ctx({ biomeMask: BIOME_ALL })), true)
  const inv = new Array(9).fill(1)
  const full = ctx({ inv })
  assert.equal(met(def('hotbar_full'), p, full), true)
  inv[4] = 0
  assert.equal(met(def('hotbar_full'), p, full), false)
  // 已经站到过高处:maxY 是历史最大值,不会因为下来就不算(用干净档案测,前面已经解锁过 tower40)
  const fresh = emptyProfile()
  assert.deepEqual(checkAchievements(fresh, ctx({ biomeMask: BIOME_ALL, inv: new Array(9).fill(2), maxY: 41 }), 20)
    .map((a) => a.id).sort(), ['biomes3', 'hotbar_full', 'tower40'])
})

test('条件型:连续挖 50、夜里挖 10、水里待 10 秒', () => {
  const p = emptyProfile()
  assert.equal(met(def('streak50'), p, ctx({ streak: 49 })), false)
  assert.equal(met(def('streak50'), p, ctx({ streak: 50 })), true)
  assert.equal(met(def('night_mine10'), p, ctx({ nightMined: 9 })), false)
  assert.equal(met(def('night_mine10'), p, ctx({ nightMined: 10 })), true)
  assert.equal(met(def('swim10'), p, ctx({ swimSeconds: 9.9 })), false)
  assert.equal(met(def('swim10'), p, ctx({ swimSeconds: 10 })), true)
  const got = checkAchievements(p, ctx({ streak: 50, nightMined: 10, swimSeconds: 10 }), 30)
  assert.equal(got.length, 3)
})

test('进度显示:统计型显示当前/目标,条件型有各自的进度', () => {
  const p = emptyProfile()
  p.mined = 42
  const c = ctx({ maxY: 12, biomeMask: BIOME_GRASS | BIOME_STONE, inv: [1, 1, 0, 0, 0, 0, 0, 0, 0], streak: 7, nightMined: 3, swimSeconds: 4 })
  assert.deepEqual(achievementProgress(def('mine_100'), p, c), { current: 42, goal: 100, done: false })
  assert.deepEqual(achievementProgress(def('tower40'), p, c), { current: 12, goal: 40, done: false })
  assert.deepEqual(achievementProgress(def('biomes3'), p, c), { current: 2, goal: 3, done: false })
  assert.deepEqual(achievementProgress(def('hotbar_full'), p, c), { current: 2, goal: 9, done: false })
  assert.deepEqual(achievementProgress(def('swim10'), p, c), { current: 4, goal: 10, done: false })
  p.mined = 500
  p.achievements.mine_100 = 1
  const done = achievementProgress(def('mine_100'), p, c)
  assert.equal(done.done, true)
  assert.equal(done.current, 100, '已完成时进度条是满的')
})

test('解锁时间用传入的 now,不用 Date.now(可测试、可复现)', () => {
  const p = emptyProfile()
  p.mined = 1
  checkAchievements(p, ctx(), 123456)
  assert.equal(p.achievements.first_mine, 123456)
})
