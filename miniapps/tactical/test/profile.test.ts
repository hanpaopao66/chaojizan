import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  EMPTY_PROFILE, Profile, accuracy, isFuture, loadProfile, mergeProfile, recordMatch, saveProfile, withSettings,
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
  // v2 是当前版本:空的也该解析成默认档;v3 是未来版本:只读
  assert.ok(loadProfile({ v: 2 }))
  assert.equal(loadProfile({ v: 3 })!.future, true)
  assert.equal(loadProfile({}), null)
  assert.equal(loadProfile({ v: 0 }), null)
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

test('合并战绩不会自相矛盾:wins + losses 永远不超过 games', () => {
  const mk = (games: number, wins: number, losses: number): Profile => ({ ...EMPTY_PROFILE, games, wins, losses })
  const pairs: Array<[Profile, Profile]> = [
    [mk(4, 3, 1), mk(4, 1, 3)], // 两台设备各赢 3/1 场:并集是 3 胜 3 负,至少 6 场
    [mk(10, 8, 2), mk(2, 0, 2)],
    [mk(0, 0, 0), mk(7, 4, 3)],
    [mk(1, 0, 1), mk(1, 1, 0)],
  ]
  for (const [a, b] of pairs) {
    const m = mergeProfile(a, b)
    assert.ok(m.wins + m.losses <= m.games, `合并出 ${m.games} 场 ${m.wins} 胜 ${m.losses} 负`)
    assert.ok(m.wins >= Math.max(a.wins, b.wins), '胜场不会比任何一台设备少')
    assert.ok(m.losses >= Math.max(a.losses, b.losses), '负场不会比任何一台设备少')
    assert.ok(m.games >= Math.max(a.games, b.games), '场次不会比任何一台设备少')
  }
  const pairsA = mk(4, 3, 1)
  const pairsB = mk(4, 1, 3)
  assert.equal(mergeProfile(pairsA, pairsB).games, 6, '4 场 3 胜 + 4 场 3 负 至少是 6 场')
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

test('1.0 的 v1 存档迁移到 v2:战绩/难度保留,v1 没有的地图/成就补默认', () => {
  const v1 = {
    v: 1, games: 7, wins: 5, losses: 2, streak: 1, bestStreak: 3,
    kills: 18, plants: 4, shots: 90, hits: 40, difficulty: 'hard', sound: false,
  }
  const p = loadProfile(v1)
  assert.ok(p)
  assert.equal(p.v, 2)
  assert.equal(p.games, 7)
  assert.equal(p.wins, 5)
  assert.equal(p.losses, 2)
  assert.equal(p.bestStreak, 3)
  assert.equal(p.kills, 18)
  assert.equal(p.difficulty, 'hard')
  assert.equal(p.sound, false)
  assert.equal(p.mapId, 'warehouse', 'v1 没有地图字段,补默认')
  assert.deepEqual(p.achievements, [], 'v1 没有成就字段,补空')
  assert.equal(p.future, undefined)
  // 迁移后写出去的是 v2,字段都在
  const saved = saveProfile(p) as Record<string, unknown>
  assert.equal(saved.v, 2)
  const back = loadProfile(saved)
  assert.ok(back)
  assert.equal(back.wins, 5)
  assert.equal(back.mapId, 'warehouse')
})

test('比客户端更新的存档只读:能显示已知字段,但不合并、不回写', () => {
  const futureRaw = {
    v: 3, games: 12, wins: 9, losses: 3, mapId: 'market',
    achievements: ['future-one'], futureField: 'x',
  }
  const p = loadProfile(futureRaw)
  assert.ok(p)
  assert.equal(isFuture(p), true)
  assert.equal(p.games, 12)
  assert.equal(p.mapId, 'market')
  assert.deepEqual(p.achievements, ['future-one'])
  assert.equal(isFuture(mergeProfile(EMPTY_PROFILE, p)), true, '云端未来版本不会和本地合并')
  assert.equal(isFuture(mergeProfile(p, EMPTY_PROFILE)), true, '本地未来版本原样保留')
  const saved = saveProfile(p) as Record<string, unknown>
  assert.equal(saved.v, 2, '只读档就算被序列化也不会写成当前版本以外的样子')
  assert.equal(saved.future, undefined, '只读标记不落盘')
})
