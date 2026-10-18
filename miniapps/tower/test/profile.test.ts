// 档案单测:胜负记录、星级保存、成就判定、坏档兜底、两台设备合并、解锁进度。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  allCleared, claimAchievements, endlessUnlocked, hasSeen, levelName, levelStars, levelUnlocked,
  loadBest, markSeen, meets, mergeBest, newProfile, nextLevelId, recordResult, totalStars,
} from '../src/profile'
import { ACHIEVEMENTS } from '../src/data'
import { LEVELS } from '../src/levels'
import type { RunResult } from '../src/save'
import type { TowerKind } from '../src/types'

function result(over: Partial<RunResult> = {}): RunResult {
  return {
    levelId: 1, won: true, stars: 3, hp: 20, maxHp: 20, kills: 20, bossKills: 0, leaks: 0,
    goldEarned: 200, built: 10, waves: 6, time: 60, endlessWave: 0, towerKinds: ['pea'],
    ...over,
  }
}

/** 全成就需要的档案条件,逐项摆出来 */
function fulfilled(): ReturnType<typeof newProfile> {
  let p = newProfile()
  for (const level of LEVELS) p.stars[String(level.id)] = 3
  p = {
    ...p,
    endlessBest: 20,
    stats: { games: 20, wins: 20, kills: 1200, bossKills: 5, gold: 6000, maxTowers: 14 },
    usedTowers: ['pea', 'frost', 'pepper', 'vine', 'mushroom', 'bow', 'marigold'] as TowerKind[],
  }
  return p
}

test('新档案:没有星级、没有成就、声音开、1 倍速', () => {
  const p = newProfile()
  assert.equal(p.v, 1)
  assert.deepEqual(p.stars, {})
  assert.equal(p.endlessBest, 0)
  assert.deepEqual(p.achievements, [])
  assert.equal(p.sound, true)
  assert.equal(p.speed, 1)
  assert.deepEqual(p.stats, { games: 0, wins: 0, kills: 0, bossKills: 0, gold: 0, maxTowers: 0 })
  assert.deepEqual(p.usedTowers, [])
})

test('赢一局:星级、场次、胜场、击杀、金币、用过的塔都记上,并点亮第一批成就', () => {
  const { best, unlocked } = recordResult(newProfile(), result({ levelId: 2, stars: 3, kills: 20, goldEarned: 300, built: 10 }))
  assert.equal(best.stars['2'], 3)
  assert.equal(best.stats.games, 1)
  assert.equal(best.stats.wins, 1)
  assert.equal(best.stats.kills, 20)
  assert.equal(best.stats.gold, 300)
  assert.equal(best.stats.maxTowers, 10)
  assert.deepEqual(best.usedTowers, ['pea'])
  assert.ok(unlocked.includes('first_win'))
  assert.ok(unlocked.includes('first_build'))
  assert.ok(unlocked.includes('flawless'))
})

test('输一局:不动星级,但记场次和击杀', () => {
  let p = recordResult(newProfile(), result({ levelId: 3, stars: 3 })).best
  const before = p.stars['3']
  p = recordResult(p, result({ levelId: 3, won: false, stars: 0, kills: 5 })).best
  assert.equal(p.stars['3'], before, '输了不能把原来的星级改掉')
  assert.equal(p.stats.games, 2)
  assert.equal(p.stats.wins, 1)
  assert.equal(p.stats.kills, 25)
})

test('星级取历史最好:先 1 星再 3 星会更新,反过来不会降', () => {
  let p = recordResult(newProfile(), result({ levelId: 5, stars: 1 })).best
  assert.equal(p.stars['5'], 1)
  p = recordResult(p, result({ levelId: 5, stars: 3 })).best
  assert.equal(p.stars['5'], 3)
  p = recordResult(p, result({ levelId: 5, stars: 2 })).best
  assert.equal(p.stars['5'], 3)
})

test('成就判定逐条覆盖:全部满足时 12 个都能点亮', () => {
  const p = fulfilled()
  for (const a of ACHIEVEMENTS) assert.equal(meets(a.id, p), true, `${a.name} 应该判定通过`)
  const { best, unlocked } = claimAchievements(p)
  assert.equal(unlocked.length, ACHIEVEMENTS.length)
  assert.equal(best.achievements.length, ACHIEVEMENTS.length)
  // 已经点过的不重复给
  assert.equal(claimAchievements(best).unlocked.length, 0)
  // 不认识的成就 id 一律 false
  assert.equal(meets('does_not_exist', p), false)
  // 空档案一个成就都不该亮
  const fresh = newProfile()
  assert.equal(claimAchievements(fresh).unlocked.length, 0)
})

test('每个成就都有一个「差一点就满足」的反例', () => {
  const almost = fulfilled()
  const cases: Array<[string, ReturnType<typeof newProfile>]> = []
  cases.push(['first_win', { ...almost, stats: { ...almost.stats, wins: 0 } }])
  cases.push(['first_build', { ...almost, stats: { ...almost.stats, maxTowers: 0 } }])
  cases.push(['flawless', { ...almost, stars: {} }])
  cases.push(['garden_full', { ...almost, stars: { ...almost.stars, '2': 2 } }])
  cases.push(['orchard_guard', { ...almost, stars: { ...almost.stars, '8': 0 } }])
  cases.push(['night_walker', { ...almost, stars: { ...almost.stars, '12': 0 } }])
  cases.push(['boss_hunter', { ...almost, stats: { ...almost.stats, bossKills: 2 } }])
  cases.push(['tower_master', { ...almost, stats: { ...almost.stats, maxTowers: 11 } }])
  cases.push(['all_towers', { ...almost, usedTowers: ['pea'] }])
  cases.push(['endless_10', { ...almost, endlessBest: 9 }])
  cases.push(['endless_20', { ...almost, endlessBest: 19 }])
  cases.push(['rich_farmer', { ...almost, stats: { ...almost.stats, gold: 4999 } }])
  for (const [id, p] of cases) assert.equal(meets(id, p), false, `${id} 的反例应该不满足`)
})

test('读档:正常档案能往返;坏的、版本不对的当作全新', () => {
  const p = fulfilled()
  assert.deepEqual(loadBest(JSON.parse(JSON.stringify(p))), p)
  assert.equal(loadBest(null), null)
  assert.equal(loadBest({ ...p, v: 2 }), null)
  assert.equal(loadBest({ ...p, stars: { 99: 3 } }), null)
  assert.equal(loadBest({ ...p, stars: { 1: 4 } }), null)
  assert.equal(loadBest({ ...p, stars: { 1: 0 } }), null)
  assert.equal(loadBest({ ...p, endlessBest: -1 }), null)
  assert.equal(loadBest({ ...p, achievements: ['fake'] }), null)
  assert.equal(loadBest({ ...p, usedTowers: ['laser'] }), null)
  assert.equal(loadBest({ ...p, speed: 3 }), null)
  assert.equal(loadBest({ ...p, stats: { ...p.stats, wins: 99 } }), null)
})

test('两台设备合并:星级取高、无尽取高、成就和提示取并集、统计取大', () => {
  const a: ReturnType<typeof newProfile> = {
    ...newProfile(), stars: { 1: 3, 2: 2 }, endlessBest: 8,
    achievements: ['first_win'], seen: ['hint-1'], stats: { games: 5, wins: 4, kills: 100, bossKills: 1, gold: 800, maxTowers: 8 },
    usedTowers: ['pea', 'frost'],
  }
  const b: ReturnType<typeof newProfile> = {
    ...newProfile(), stars: { 1: 1, 3: 3 }, endlessBest: 12,
    achievements: ['flawless'], seen: ['hint-2'], sound: false, speed: 2,
    stats: { games: 9, wins: 6, kills: 300, bossKills: 2, gold: 500, maxTowers: 12 },
    usedTowers: ['pea', 'bow'],
  }
  const m = mergeBest(a, b)
  assert.deepEqual(m.stars, { 1: 3, 2: 2, 3: 3 })
  assert.equal(m.endlessBest, 12)
  assert.deepEqual([...m.achievements].sort(), ['first_win', 'flawless'])
  assert.deepEqual([...m.seen].sort(), ['hint-1', 'hint-2'])
  assert.deepEqual(m.stats, { games: 9, wins: 6, kills: 300, bossKills: 2, gold: 800, maxTowers: 12 })
  assert.deepEqual([...m.usedTowers].sort(), ['bow', 'frost', 'pea'])
  assert.equal(m.sound, false, '设置跟场次多的那台走')
  assert.equal(m.speed, 2)
  // 合并是可交换的(取大/取并集;塔的顺序不保证,先排序再比)
  const swapped = mergeBest(b, a)
  assert.deepEqual([...swapped.usedTowers].sort(), [...m.usedTowers].sort())
  assert.deepEqual(swapped.stars, m.stars)
  assert.deepEqual(swapped.stats, m.stats)
})

test('解锁进度:先通关前一关才开下一关;第 12 关通关才开无尽', () => {
  let p = newProfile()
  assert.equal(levelUnlocked(p, 1), true)
  assert.equal(levelUnlocked(p, 2), false)
  assert.equal(endlessUnlocked(p), false)
  p = recordResult(p, result({ levelId: 1 })).best
  assert.equal(levelUnlocked(p, 2), true)
  assert.equal(levelUnlocked(p, 3), false)
  assert.equal(nextLevelId(p), 2)
  assert.equal(totalStars(p), 3)
  for (const level of LEVELS) p = recordResult(p, result({ levelId: level.id, stars: 3 })).best
  assert.equal(allCleared(p), true)
  assert.equal(endlessUnlocked(p), true)
  assert.equal(totalStars(p), 36)
  assert.equal(nextLevelId(p), 12, '全通了就回最后一关')
  assert.equal(levelStars(p, 12), 3)
  assert.equal(levelName(12), '虫巢母体')
  assert.equal(levelName('endless'), '无尽瓜田')
})

test('新手提示只记一次;没记过返回原对象', () => {
  const p = newProfile()
  assert.equal(hasSeen(p, 'build'), false)
  const q = markSeen(p, 'build')
  assert.ok(q !== p)
  assert.equal(hasSeen(q, 'build'), true)
  assert.equal(markSeen(q, 'build'), q, '已经记过就返回同一个对象')
})
