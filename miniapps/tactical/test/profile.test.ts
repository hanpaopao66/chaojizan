import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  EMPTY_PROFILE, Profile, accuracy, loadProfile, mergeProfile, recordMatch, saveProfile, withSettings,
} from '../src/profile'

test('战绩存档:写出去再读回来,字段一个不少', () => {
  const profile: Profile = {
    ...EMPTY_PROFILE,
    games: 9, wins: 6, losses: 3, streak: 2, bestStreak: 4,
    kills: 21, plants: 7, shots: 120, hits: 55, difficulty: 'hard', sound: false,
  }
  const back = loadProfile(JSON.parse(JSON.stringify(saveProfile(profile))))
  assert.deepEqual(back, profile)
})

test('坏存档:不是对象、版本不对就是 null;乱七八糟的字段当 0', () => {
  assert.equal(loadProfile(null), null)
  assert.equal(loadProfile('garbage'), null)
  assert.equal(loadProfile({ v: 2 }), null)
  assert.equal(loadProfile({}), null)
  const weird = loadProfile({ v: 1, games: 'x', wins: -5, bestStreak: Number.NaN, difficulty: 'god', sound: 'yes' })
  assert.ok(weird)
  assert.equal(weird.games, 0)
  assert.equal(weird.wins, 0)
  assert.equal(weird.bestStreak, 0)
  assert.equal(weird.difficulty, 'normal')
  assert.equal(loadProfile({ v: 1, difficulty: 'casual' })!.difficulty, 'casual', '第三档难度要能读回来')
  assert.equal(weird.sound, true)
})

test('两台设备合并:累计数据取大的;本机没打过就听云端的设置', () => {
  const local: Profile = { ...EMPTY_PROFILE, games: 3, wins: 2, bestStreak: 2, kills: 9, difficulty: 'normal', sound: true }
  const cloud: Profile = {
    ...EMPTY_PROFILE, games: 8, wins: 5, losses: 3, bestStreak: 6, kills: 20, plants: 4, difficulty: 'hard', sound: false,
  }
  const merged = mergeProfile(local, cloud)
  assert.equal(merged.games, 8)
  assert.equal(merged.wins, 5)
  assert.equal(merged.losses, 3)
  assert.equal(merged.bestStreak, 6)
  assert.equal(merged.kills, 20)
  assert.equal(merged.plants, 4)
  assert.equal(merged.difficulty, 'normal', '本地玩过的设备保留自己的设置')
  // 本地是全新的:云端的设置跟过来
  const fresh = mergeProfile(EMPTY_PROFILE, cloud)
  assert.equal(fresh.difficulty, 'hard')
  assert.equal(fresh.sound, false)
})

test('一场比赛:赢了加连胜、输了清零、最佳连胜取最大', () => {
  let p = EMPTY_PROFILE
  const win = { won: true, kills: 3, plants: 1, shots: 10, hits: 5 }
  const lose = { won: false, kills: 0, plants: 0, shots: 4, hits: 1 }
  p = recordMatch(p, win)
  p = recordMatch(p, win)
  assert.equal(p.games, 2)
  assert.equal(p.wins, 2)
  assert.equal(p.streak, 2)
  assert.equal(p.bestStreak, 2)
  p = recordMatch(p, lose)
  assert.equal(p.losses, 1)
  assert.equal(p.streak, 0)
  assert.equal(p.bestStreak, 2, '输了不清历史最佳')
  assert.equal(p.kills, 6)
  assert.equal(p.plants, 2)
  assert.equal(p.shots, 24)
  assert.equal(p.hits, 11)
})

test('设置:难度和声音不会把战绩弄丢', () => {
  const p = recordMatch(EMPTY_PROFILE, { won: true, kills: 2, plants: 1, shots: 8, hits: 3 })
  const next = withSettings(p, 'hard', false)
  assert.equal(next.difficulty, 'hard')
  assert.equal(next.sound, false)
  assert.equal(next.wins, 1)
  assert.equal(next.kills, 2)
  assert.equal(withSettings(next, 'hard', false), next, '没变就不产生新对象')
})

test('命中率', () => {
  assert.equal(accuracy({ hits: 0, shots: 0 }), 0)
  assert.equal(accuracy({ hits: 50, shots: 200 }), 0.25)
})
