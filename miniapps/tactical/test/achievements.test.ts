import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ACHIEVEMENTS, evaluateAchievements, newlyUnlocked } from '../src/achievements'
import { MatchState, MatchStats, newMatch } from '../src/match'
import {
  EMPTY_PROFILE, Profile, loadProfile, mergeProfile, saveProfile, unlockAchievements, withMap,
} from '../src/profile'

function makeMatch(over: 'win' | 'loss' | null, stats: Partial<MatchStats> = {}, extra: Partial<MatchState> = {}): MatchState {
  const base = newMatch('normal', 1)
  return { ...base, over, stats: { ...base.stats, ...stats }, ...extra }
}

test('成就定义:6 个、id 不重复、都有名字和说明', () => {
  assert.equal(ACHIEVEMENTS.length, 6)
  assert.equal(new Set(ACHIEVEMENTS.map((a) => a.id)).size, 6)
  for (const a of ACHIEVEMENTS) {
    assert.ok(a.name.length > 0)
    assert.ok(a.desc.length > 0)
    assert.equal(a.icon.length, 1)
  }
})

test('成就判定:首胜 / 零阵亡 / 安放并守住 / 手枪五杀 / 横扫 / 困难首胜', () => {
  assert.deepEqual(evaluateAchievements(makeMatch(null)), [], '还没打完不判')
  const loss = evaluateAchievements(makeMatch('loss', { kills: 9, pistolKills: 8 }))
  assert.equal(loss.includes('first-win'), false, '输了没有首胜')
  assert.equal(loss.includes('pistol-five'), true, '手枪五杀不看输赢')
  assert.ok(evaluateAchievements(makeMatch('win')).includes('first-win'))
  assert.ok(evaluateAchievements(makeMatch('win', { deaths: 0 })).includes('flawless'))
  assert.equal(evaluateAchievements(makeMatch('win', { deaths: 1 })).includes('flawless'), false)
  assert.ok(evaluateAchievements(makeMatch('loss', { explodedWins: 1 })).includes('plant-hold'))
  assert.ok(evaluateAchievements(makeMatch('loss', { pistolKills: 5 })).includes('pistol-five'))
  assert.equal(evaluateAchievements(makeMatch('loss', { pistolKills: 4 })).includes('pistol-five'), false)
  const sweep = makeMatch('win', {}, { scoreGuard: 0 })
  assert.ok(evaluateAchievements(sweep).includes('sweep'))
  const notSweep = makeMatch('win', {}, { scoreGuard: 1 })
  assert.equal(evaluateAchievements(notSweep).includes('sweep'), false)
  const hard = makeMatch('win', {}, { difficulty: 'hard' })
  assert.ok(evaluateAchievements(hard).includes('hard-win'))
  // 训练模式不参与成就
  assert.deepEqual(evaluateAchievements(makeMatch('win', { kills: 9 }, { training: true })), [])
})

test('新解锁 = 这局达成的成就里还没解锁的', () => {
  assert.deepEqual(newlyUnlocked([], ['first-win', 'sweep']), ['first-win', 'sweep'])
  assert.deepEqual(newlyUnlocked(['first-win'], ['first-win', 'sweep']), ['sweep'])
  assert.deepEqual(newlyUnlocked(['first-win', 'sweep'], ['first-win']), [])
})

test('存档:地图与成就写出去能读回来,坏字段容错;换图/解锁是纯函数', () => {
  const p: Profile = { ...EMPTY_PROFILE, mapId: 'market', achievements: ['first-win', 'sweep'], games: 3, wins: 2 }
  const back = loadProfile(JSON.parse(JSON.stringify(saveProfile(p))))
  assert.ok(back)
  assert.equal(back.mapId, 'market')
  assert.deepEqual(back.achievements, ['first-win', 'sweep'])
  const bad = loadProfile({ v: 1, mapId: 'nope', achievements: 'x' })
  assert.ok(bad)
  assert.equal(bad.mapId, 'warehouse')
  assert.deepEqual(bad.achievements, [])
  const unlocked = unlockAchievements(EMPTY_PROFILE, ['first-win', 'first-win', 'sweep'])
  assert.deepEqual(unlocked.achievements, ['first-win', 'sweep'])
  assert.equal(unlockAchievements(unlocked, ['first-win']), unlocked, '没有新成就返回原对象')
  assert.equal(withMap(unlocked, 'market').mapId, 'market')
  assert.equal(withMap(unlocked, 'warehouse'), unlocked, '地图没变返回原对象')
})

test('两台设备合并:成就取并集,地图/难度听本地,战绩取大的且不自相矛盾', () => {
  const local: Profile = { ...EMPTY_PROFILE, games: 4, wins: 3, losses: 1, mapId: 'market', achievements: ['first-win'] }
  const cloud: Profile = {
    ...EMPTY_PROFILE, games: 6, wins: 4, losses: 3, mapId: 'warehouse', achievements: ['sweep', 'first-win'],
  }
  const merged = mergeProfile(local, cloud)
  assert.deepEqual(merged.achievements, ['first-win', 'sweep'])
  assert.equal(merged.mapId, 'market')
  assert.equal(merged.games, Math.max(6, 4 + 3), '场次至少是胜负并集')
  assert.ok(merged.wins + merged.losses <= merged.games)
})
