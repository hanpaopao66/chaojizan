import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  ACHIEVEMENTS, CARDS, COLLECTION, DAILY_COINS, LEVELS, LEVEL_BY_ID, MAX_LEVEL, STARTERS, UPGRADE_COST, replayCoins,
  spentOn, starCoins,
} from '../src/data'
import { hitsAir } from '../src/field'
import {
  BattleResult, DECK_SIZE, PROFILE_V, Profile, activeDeck, applyResult, canUpgrade, canon, claimAchievements, coins,
  dailyChallenge, isFuture, levelConfig, levelOpen, loadProfile, mergeProfile, migrate, newProfile, sanitize, setDeck,
  todayKey, towerLevelOf, unlocked, upgrade, useDeck, validDeck,
} from '../src/progress'

const win = (tag: string, stars: number, extra: Partial<BattleResult> = {}): BattleResult => ({
  tag, won: true, stars, kills: 10, refund: 2, towers: 1, base: false, lost: 1, allLanes: false, ...extra,
})
const lose = (tag: string): BattleResult => ({ tag, won: false, stars: 0, kills: 3, refund: 0, towers: 0, base: false, lost: 3, allLanes: false })

/** 从新档案开始,依次打这些结果 */
function playAll(results: BattleResult[], device = 'dev1', p0 = newProfile()): Profile {
  let p = p0
  for (const r of results) p = applyResult(p, r, device).profile
  return p
}

test('新档案:开局 8 张卡,三套卡组都是开局那套,没有金币', () => {
  const p = newProfile()
  assert.equal(p.v, PROFILE_V)
  assert.deepEqual(unlocked(p), COLLECTION.filter((id) => STARTERS.indexOf(id) >= 0))
  assert.equal(p.decks.length, 3)
  for (const d of p.decks) assert.deepEqual(d, STARTERS)
  assert.equal(coins(p), 0)
  assert.ok(levelOpen(p, '1-1'))
  assert.ok(!levelOpen(p, '1-2'))
})

test('第一次通关:解锁这一关的卡,给通关钱 + 每颗星的钱 + 达成的成就;下一关打开', () => {
  const p = newProfile()
  const { profile, reward } = applyResult(p, win('1-1', 2), 'dev1')
  const L = LEVEL_BY_ID['1-1']
  assert.equal(reward.firstClear, true)
  assert.deepEqual(reward.cards, [L.unlock])
  assert.equal(reward.newStars, 2)
  assert.ok(reward.achievements.indexOf('first') >= 0)
  const achCoins = reward.achievements.reduce((n, a) => n + ACHIEVEMENTS.find((x) => x.id === a)!.coins, 0)
  assert.equal(reward.coins, L.coins + 2 * starCoins(1) + achCoins)
  assert.equal(coins(profile), reward.coins)
  assert.ok(levelOpen(profile, '1-2'))
  assert.equal(profile.earn.dev1, undefined, '第一次通关的钱是从星数表推出来的,不记在设备格子里')
})

test('重复通关:星取最好的,新的星另给钱,重复赢的钱记在这台设备的格子里;输了什么都不给', () => {
  let p = playAll([win('1-1', 1)])
  const c1 = coins(p)
  let r = applyResult(p, win('1-1', 3), 'dev1')
  assert.equal(r.reward.newStars, 2)
  assert.equal(r.profile.stars['1-1'], 3)
  assert.equal(r.profile.earn.dev1, replayCoins(1, 3))
  p = r.profile
  r = applyResult(p, win('1-1', 1), 'dev1')
  assert.equal(r.profile.stars['1-1'], 3, '星不会变少')
  assert.equal(r.reward.newStars, 0)
  const lost = applyResult(p, lose('1-2'), 'dev1')
  assert.equal(lost.reward.coins, 0)
  assert.equal(lost.profile.stars['1-2'], undefined)
  assert.equal(lost.profile.stats.games, p.stats.games + 1)
  assert.ok(coins(p) > c1)
})

test('每日挑战:当天第一次赢给一次钱,再赢不给;没有连胜奖励;只留最近 30 天', () => {
  let p = newProfile()
  let r = applyResult(p, win('daily:2026-09-15', 2), 'dev1')
  assert.equal(r.profile.earn.dev1, DAILY_COINS)
  assert.equal(r.profile.daily['2026-09-15'], 2)
  p = applyResult(r.profile, win('daily:2026-09-15', 3), 'dev1').profile
  assert.equal(p.earn.dev1, DAILY_COINS, '同一天再赢不再给')
  assert.equal(p.daily['2026-09-15'], 3)
  // 连着 40 天:每天一样多,只留 30 天
  for (let d = 1; d <= 40; d++) {
    const date = `2026-10-${String(d).padStart(2, '0')}`.replace('2026-10-3', '2026-11-0').replace('2026-10-4', '2026-11-1')
    r = applyResult(p, win(`daily:${date}`, 1), 'dev1')
    assert.equal(r.profile.earn.dev1 - p.earn.dev1, DAILY_COINS)
    p = r.profile
  }
  assert.ok(Object.keys(p.daily).length <= 30)
  assert.equal(p.stats.dailyWins, 41)
})

test('升级:扣对应的钱、加一级;钱不够、没解锁、满级都不行', () => {
  const p = playAll([win('1-1', 3), win('1-2', 3)])
  const before = coins(p)
  assert.ok(canUpgrade(p, 'bear'))
  const q = upgrade(p, 'bear')
  assert.equal(q.levels.bear, 2)
  assert.equal(coins(q), before - UPGRADE_COST[1])
  assert.equal(upgrade(p, 'elephant'), p, '没解锁')
  const poor = newProfile()
  assert.equal(upgrade(poor, 'bear'), poor, '没钱')
  const maxed: Profile = { ...p, levels: { ...p.levels, bear: MAX_LEVEL } }
  assert.equal(canUpgrade(maxed, 'bear'), false)
  assert.equal(spentOn(3), UPGRADE_COST[1] + UPGRADE_COST[2])
})

test('卡组:8 张不重复、都解锁了才能存;出战的那套有问题时退回开局那套', () => {
  const p = playAll([win('1-1', 1)])
  assert.ok(validDeck(STARTERS))
  assert.ok(!validDeck(STARTERS.slice(0, 7)))
  assert.ok(!validDeck([...STARTERS.slice(0, 7), 'chick']))
  assert.ok(!validDeck([...STARTERS.slice(0, 7), 'buffalo']), '电脑专用的卡不行')
  const d = ['fence', ...STARTERS.slice(1)]
  const q = setDeck(p, 1, d, 1000)
  assert.deepEqual(q.decks[1], d)
  assert.equal(q.deckAt, 1000)
  assert.equal(setDeck(p, 1, ['elephant', ...STARTERS.slice(1)], 1000), p, '没解锁的卡进不了卡组')
  const r = useDeck(q, 1, 2000)
  assert.deepEqual(activeDeck(r), d)
  const broken: Profile = { ...r, decks: [STARTERS, ['elephant', ...STARTERS.slice(1)], STARTERS] }
  assert.deepEqual(activeDeck(broken), STARTERS)
  assert.equal(DECK_SIZE, 8)
})

test('开一关:玩家的卡按自己的等级,塔按卡组平均等级;电脑按章节', () => {
  const p = upgrade(upgrade(playAll([win('1-1', 3), win('1-2', 3), win('1-3', 3)]), 'bear'), 'chick')
  const c = levelConfig(p, LEVEL_BY_ID['2-1'], 42)
  assert.equal(c.decks[0].levels.bear, 2)
  assert.equal(c.decks[0].levels.duck, 1)
  assert.equal(c.decks[1].levels[c.decks[1].cards[0]], 2)
  assert.equal(c.towerLevel[0], towerLevelOf(p, activeDeck(p)))
  assert.equal(c.towerLevel[1], 2)
  assert.equal(c.ai[0], null)
  assert.equal(c.tag, '2-1')
})

test('两台设备合并:星、等级、设备格子取大,成就取并集;金币按合并后的账重新算,不多也不少', () => {
  const base = playAll([win('1-1', 3), win('1-2', 3), win('1-3', 2)])
  // A 这台:升级了大熊
  const a = upgrade(base, 'bear')
  // B 这台:把 1-3 重打到三星,又赢了一次每日挑战
  let b = applyResult(base, win('1-3', 3), 'devB').profile
  b = applyResult(b, win('daily:2026-09-15', 1), 'devB').profile
  const m = mergeProfile(a, b)
  assert.equal(m.levels.bear, 2)
  assert.equal(m.stars['1-3'], 3)
  assert.equal(m.earn.devB, b.earn.devB)
  const expected = coins(base) - UPGRADE_COST[1] + (coins(b) - coins(base))
  assert.equal(coins(m), expected)
  // 顺序无关、合并两次和一次一样
  assert.deepEqual(JSON.stringify(mergeProfile(b, a).stars), JSON.stringify(m.stars))
  assert.equal(coins(mergeProfile(b, a)), coins(m))
  assert.equal(JSON.stringify(mergeProfile(m, m)), JSON.stringify(m))
  assert.equal(JSON.stringify(mergeProfile(m, a)), JSON.stringify(m))
  // 卡组谁后改用谁的
  const a2 = setDeck(a, 0, ['fence', ...STARTERS.slice(1)], 5000)
  assert.deepEqual(mergeProfile(a2, b).decks[0], a2.decks[0])
  assert.deepEqual(mergeProfile(b, a2).decks[0], a2.decks[0])
})

test('存档版本:按迁移表一步步升;缺一步读不出;新版本写的原样保留、只读,合并时不被旧格式盖掉', () => {
  const steps = {
    0: (r: Record<string, unknown>) => ({ ...r, stars: r.progress }),
    1: (r: Record<string, unknown>) => ({ ...r, renamed: true }),
  }
  const m = migrate({ v: 0, progress: { '1-1': 2 } }, steps, 2)!
  assert.equal(m.v, 2)
  assert.deepEqual(m.stars, { '1-1': 2 })
  assert.equal(m.renamed, true)
  assert.equal(migrate({ v: 0 }, {}, 1), null, '缺迁移')
  // 现在的第 1 版读出来
  const p = playAll([win('1-1', 3)])
  const back = loadProfile(JSON.parse(JSON.stringify(p)))!
  assert.deepEqual(back, p)
  // 未来的版本
  const future = loadProfile({ v: PROFILE_V + 1, stars: { x: 'y' }, brandNew: [1, 2] })!
  assert.ok(isFuture(future))
  assert.equal(mergeProfile(p, future), future, '合并时留新版本的,不拿旧格式去合')
  assert.equal(applyResult(future, win('1-1', 3), 'dev1').profile, future, '只读:不记战绩')
  assert.equal(loadProfile({ v: 0 }), null)
  assert.equal(loadProfile('garbage'), null)
  assert.equal(loadProfile([1, 2]), null)
})

test('洗存档:不认识的关、卡、越界的数、坏卡组都丢掉,缺的补默认值', () => {
  const s = sanitize({
    v: 1, stars: { '1-1': 3, '9-9': 3, '1-2': 7 }, levels: { bear: 3, buffalo: 5, nope: 2, duck: 99 },
    earn: { dev1: 50, 'bad id!': 10 }, decks: [['x']], deck: 5, daily: { '2026-09-15': 2, yesterday: 1 },
    ach: ['first', 'fake'], stats: { wins: 3, 'bad-key': 1 }, seen: ['drag'],
  })
  assert.deepEqual(s.stars, { '1-1': 3 })
  assert.deepEqual(s.levels, { bear: 3 })
  assert.deepEqual(s.earn, { dev1: 50 })
  assert.deepEqual(s.decks[0], STARTERS)
  assert.equal(s.deck, 0)
  assert.deepEqual(s.daily, { '2026-09-15': 2 })
  assert.deepEqual(s.ach, ['first'])
  assert.deepEqual(s.stats, { wins: 3 })
  assert.deepEqual(s.seen, ['drag'])
})

test('同样的内容永远是同样的 JSON(存档层按 JSON 判断有没有改过)', () => {
  const a = canon({ ...newProfile(), stars: { '1-2': 1, '1-1': 3 }, ach: ['first', 'star3', 'first'] })
  const b = canon({ ...newProfile(), stars: { '1-1': 3, '1-2': 1 }, ach: ['star3', 'first'] })
  assert.equal(JSON.stringify(a), JSON.stringify(b))
})

test('存档大小:玩到头的档案也只有几 KB(云存储单个值上限 64 KB)', () => {
  let p = newProfile()
  for (const L of LEVELS) p = applyResult(p, win(L.id, 3, { kills: 50, refund: 15, towers: 3, allLanes: true, lost: 0 }), 'dev0').profile
  for (let d = 0; d < 40; d++) p = applyResult(p, win(`daily:2026-${String(10 + Math.floor(d / 28)).padStart(2, '0')}-${String(1 + (d % 28)).padStart(2, '0')}`, 3), `dev${d % 6}`).profile
  const levels: Record<string, number> = {}
  for (const id of COLLECTION) levels[id] = MAX_LEVEL
  p = canon({ ...p, levels })
  const size = JSON.stringify(p).length
  assert.ok(size < 4096, `最大的档案 ${size} 字节`)
})

test('每日挑战:同一天人人一样,换一天就不一样;两边卡组 8 张不重复、都有能打空中的', () => {
  assert.equal(JSON.stringify(dailyChallenge('2026-09-15')), JSON.stringify(dailyChallenge('2026-09-15')))
  const seen = new Set<string>()
  for (let d = 1; d <= 28; d++) {
    const date = `2026-09-${String(d).padStart(2, '0')}`
    const c = dailyChallenge(date)
    seen.add(JSON.stringify(c.cfg.decks[0].cards))
    for (const side of [0, 1]) {
      const cards = c.cfg.decks[side].cards
      assert.equal(cards.length, 8)
      assert.equal(new Set(cards).size, 8, `${date} 有重复`)
      assert.ok(cards.every((id) => CARDS[id] && !CARDS[id].boss))
      assert.ok(cards.some((id) => CARDS[id].unit && hitsAir(CARDS[id].unit!)), `${date} 没有能打空中的`)
    }
    assert.ok(c.cfg.decks[0].cards.every((id) => !CARDS[id].aiOnly), '玩家的卡组里不会有电脑专用的')
    assert.equal(c.cfg.tag, `daily:${date}`)
  }
  assert.ok(seen.size > 20, '换一天卡组基本都不一样')
})

test('每日挑战按北京时间换关', () => {
  assert.equal(todayKey(Date.UTC(2026, 8, 14, 15, 59)), '2026-09-14')
  assert.equal(todayKey(Date.UTC(2026, 8, 14, 16, 0)), '2026-09-15')
})

test('成就:达成的自动记上、金币到账;升级到 5 级的成就在升级时记', () => {
  let p = playAll([win('1-1', 3), win('1-2', 3), win('1-3', 3), win('1-4', 3), win('1-5', 3)])
  assert.ok(p.ach.indexOf('ch1') >= 0)
  assert.ok(p.ach.indexOf('star3') >= 0)
  // 攒够钱把小鸡升到 5 级
  p = { ...p, earn: { dev1: 5000 } }
  for (let i = 0; i < 4; i++) p = upgrade(p, 'chick')
  assert.equal(p.levels.chick, 5)
  const { profile, got } = claimAchievements(p)
  assert.deepEqual(got, ['level5'])
  assert.ok(profile.ach.indexOf('level5') >= 0)
  assert.equal(claimAchievements(profile).got.length, 0)
})
