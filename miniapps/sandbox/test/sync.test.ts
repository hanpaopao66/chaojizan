// 存档对账回归:P1/P2 修过的三条语义。
//  1) 云对账后写回必须合并,本机旧档不能盖掉云端较新的统计/成就;
//  2) v1 旧档的挖/放统计能迁进档案且幂等;
//  3) 迁移/写回不把本机存档的 at 提到 now(否则会盖掉另一台设备较新的云档)。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { SaveSlot, type CloudLike, type LocalLike, type Timers } from '../../shared/src/save'
import { emptyProfile, loadProfile, mergeProfile, profileOf, copyProfile, type Profile } from '../src/profile'
import { loadSave, newSave, saveOf, type GameSave } from '../src/save'
import { legacyOf, mergeLegacy, migrateLegacy, profileForWrite } from '../src/sync'
import { spawnForTest } from './helpers'

const spawn = spawnForTest(12, 10.5, 20.5)

function fakeCloud(store: Map<string, string>): CloudLike {
  return {
    async getItems(keys) {
      const out: Record<string, string | null> = {}
      for (const k of keys) out[k] = store.get(k) ?? null
      return out
    },
    async setItem(k, v) {
      store.set(k, v)
      return {}
    },
  }
}
function fakeLocal(store: Map<string, string>): LocalLike {
  return {
    getItem: (k) => store.get(k) ?? null,
    setItem: (k, v) => { store.set(k, v) },
  }
}
function fakeTimers(): Timers & { pending: number } {
  const handles: number[] = []
  let next = 1
  return {
    pending: 0,
    set(fn) {
      const h = next++
      handles.push(h)
      this.pending = handles.length
      void fn
      return h
    },
    clear(h) {
      const i = handles.indexOf(h as number)
      if (i >= 0) handles.splice(i, 1)
      this.pending = handles.length
    },
  }
}

function makeSlot(cloudStore: Map<string, string>, localStore: Map<string, string>, now: number, timers: Timers): SaveSlot<GameSave, Profile> {
  return new SaveSlot<GameSave, Profile>({
    cacheKey: 'k',
    cloud: fakeCloud(cloudStore),
    local: fakeLocal(localStore),
    loadState: loadSave,
    saveState: saveOf,
    loadBest: loadProfile,
    mergeBest: mergeProfile,
    emptyBest: emptyProfile(),
    now: () => now,
    timers,
  })
}

function profile(mined: number, placed: number, achievements: Record<string, number>): Profile {
  return { v: 2, mined, placed, walked: mined * 2, seconds: mined, achievements: { ...achievements } }
}

test('云对账:本机旧档写回不会盖掉云端较新的统计/成就', async () => {
  const stateA = newSave(111, spawn, 0)
  const stateB = newSave(222, spawn, 0)
  const profileA = profile(10, 0, { first_mine: 500 })
  const profileB = profile(900, 3, { first_mine: 300, mine_100: 800 })
  const localStore = new Map<string, string>()
  const cloudStore = new Map<string, string>()
  localStore.set('k', JSON.stringify({ state: saveOf(stateA), best: profileOf(profileA), at: 3000, seen: true }))
  cloudStore.set('state', JSON.stringify({ at: 5000, state: saveOf(stateB) }))
  cloudStore.set('best', JSON.stringify(profileOf(profileB)))
  const slot = makeSlot(cloudStore, localStore, 6000, fakeTimers())

  assert.equal(slot.restoreLocal(), true)
  assert.equal(slot.state!.seed, 111)
  const restored = await slot.restoreCloud()
  assert.equal(restored, 'cloud', '云端世界更新,应该用云档')
  assert.equal(slot.state!.seed, 222)
  assert.equal(slot.at, 5000, '云档时间戳保留,不能被本机现在时间顶掉')
  assert.equal(slot.best.mined, 900)
  assert.equal(slot.best.placed, 3)
  assert.equal(slot.best.achievements.first_mine, 300, '同一成就取更早的解锁时间')
  assert.equal(slot.best.achievements.mine_100, 800)

  // 模拟「云还没返回就点了继续」:游戏里拿的是云对账前的旧档案
  const stale = copyProfile(profileA)
  slot.setBest(profileForWrite(slot.best, stale))
  assert.equal(slot.best.mined, 900, '旧档案不能把云端统计改小')
  assert.equal(slot.best.achievements.mine_100, 800)
  await slot.flush()
  const cloudBest = loadProfile(JSON.parse(cloudStore.get('best')!))!
  assert.equal(cloudBest.mined, 900, '写回云端的也是合并后的值')
  assert.equal(cloudBest.achievements.first_mine, 300)
})

test('v1 旧档:统计迁移进档案且幂等;迁移不动存档 at(不会顶掉较新云档)', async () => {
  const base = saveOf(newSave(333, spawn, 1)) as Record<string, unknown>
  const rawV1 = { ...base, v: 1, mined: 42, placed: 7 }
  const localStore = new Map<string, string>()
  const cloudStore = new Map<string, string>()
  localStore.set('k', JSON.stringify({ state: rawV1, best: profileOf(emptyProfile()), at: 2500, seen: true }))
  // 另一台设备已经升级到 v2:世界更新,但还没有统计(best 空)
  const cloudState = newSave(444, spawn, 0)
  cloudStore.set('state', JSON.stringify({ at: 8000, state: saveOf(cloudState) }))
  const slot = makeSlot(cloudStore, localStore, 9000, fakeTimers())

  slot.restoreLocal()
  // 1.0 存档读成 v2,挖/放进 legacy
  const legacy = legacyOf(slot.state)
  assert.deepEqual(legacy, { mined: 42, placed: 7 })
  await slot.restoreCloud()
  assert.equal(slot.state!.seed, 444, '云档较新,世界应该用云端的')
  assert.equal(slot.at, 8000, '不能因为迁移把 at 提到 now')

  const migrated = migrateLegacy(slot.best, legacy)
  assert.equal(migrated.changed, true)
  assert.equal(migrated.profile.mined, 42)
  assert.equal(migrated.profile.placed, 7)
  slot.setBest(migrated.profile)
  // 再迁一次(比如又读到旧本机缓存):不会重复计数
  const again = migrateLegacy(slot.best, legacy)
  assert.equal(again.changed, false)
  assert.equal(again.profile.mined, 42)
  await slot.flush()
  assert.equal(loadProfile(JSON.parse(cloudStore.get('best')!))!.mined, 42)
  // at 仍然是云档时间
  assert.equal(slot.at, 8000)
})

test('迁移细节:档案已有统计就不覆盖;本机和云端的 v1 统计取较大值', () => {
  const empty = emptyProfile()
  const first = migrateLegacy(empty, { mined: 42, placed: 7 })
  assert.equal(first.changed, true)
  assert.equal(first.profile.mined, 42)
  assert.equal(first.profile.placed, 7)
  assert.equal(empty.mined, 0, '不改原对象')
  // 已有挖数量:不重复加;放数量还是 0:可以补
  const partial: Profile = { ...emptyProfile(), mined: 500 }
  const second = migrateLegacy(partial, { mined: 42, placed: 7 })
  assert.equal(second.profile.mined, 500)
  assert.equal(second.profile.placed, 7)
  // 两边都是 v1 存档:取较大值
  assert.deepEqual(mergeLegacy({ mined: 42, placed: 7 }, { mined: 50, placed: 3 }), { mined: 50, placed: 7 })
  assert.equal(mergeLegacy(null, { mined: 1, placed: 2 })!.mined, 1)
  assert.equal(mergeLegacy({ mined: 1, placed: 2 }, null)!.placed, 2)
  assert.equal(mergeLegacy(null, null), null)
  // 坏 legacy 当没有
  assert.equal(legacyOf({ legacy: { mined: Number.NaN, placed: 1 } }), null)
  assert.equal(legacyOf(null), null)
  assert.equal(legacyOf({}), null)
})

test('profileForWrite 等价于 merge:统计取大、成就并集', () => {
  const slotBest = profile(900, 3, { mine_100: 100 })
  const gameOld = profile(10, 0, { first_mine: 50 })
  const merged = profileForWrite(slotBest, gameOld)
  assert.equal(merged.mined, 900)
  assert.equal(merged.placed, 3)
  assert.equal(merged.achievements.mine_100, 100)
  assert.equal(merged.achievements.first_mine, 50)
  // 游戏里离线玩得更多时取游戏的值
  const gameMore = profile(1200, 9, { mine_100: 90 })
  const merged2 = profileForWrite(slotBest, gameMore)
  assert.equal(merged2.mined, 1200)
  assert.equal(merged2.achievements.mine_100, 90, '同一成就取更早时间')
})
