// 存档单测:对局状态能整份来回、坏档当作没有、召唤物不能混进牌库、
// 战绩档案 v2(含成就累计数)的统计/合并/v1 升级、以及存档大小不超过云端的 64 KB。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { aiNext } from '../src/ai'
import { applyAction, loadGame, newGame, placeMinion, saveGame } from '../src/engine'
import {
  loadProfile, mergeProfile, newProfile, recordResult, rememberChoice, withAchievements, markTutorialSeen,
  type Outcome,
} from '../src/profile'
import type { GameState, Level } from '../src/types'
import { clone, fresh, hand, setTurn } from './helpers'

/** 用 AI 把对局往前推几步,得到一份「打到一半」的真实存档 */
function midGame(seed: number): GameState {
  let s = newGame({ seed, hero0: 'forge', hero1: 'dusk' }).state
  for (let i = 0; i < 14; i++) {
    if (s.over) break
    const a = aiNext(s, i % 2 === 0 ? 'normal' : 'hard')
    const r = applyAction(s, a)
    assert.ok(r.ok)
    s = r.state
  }
  return s
}

const outcome = (over: Partial<Outcome> = {}): Outcome => ({
  won: true, draw: false, hero: 'forge', level: 'normal', reason: 'hp', myHp: 30, dealt: 12, played: 6,
  ...over,
})

test('对局存档往返:写进去、读回来一模一样,接着打的结果也一致', () => {
  const s = midGame(11)
  const raw = JSON.parse(JSON.stringify(saveGame(s)))
  const back = loadGame(raw)
  assert.deepEqual(back, s)
  // 从存档接着打和从原状态接着打,结果一样(洗好的牌库顺序存进去了,不用重放随机数)
  const a1 = applyAction(s, { kind: 'end' })
  const a2 = applyAction(back as GameState, { kind: 'end' })
  assert.ok(a1.ok && a2.ok)
  assert.deepEqual(a1.state, a2.state)
})

test('坏档:结构不对、版本不对、数值越界的存档当作没有', () => {
  const good = midGame(13)
  const bads: unknown[] = [
    null, undefined, 42, 'x', {}, { ...good, v: 2 }, { ...good, turn: 0 }, { ...good, active: 3 },
    { ...good, sides: [] }, { ...good, sides: [good.sides[0]] },
  ]
  // 英雄血量越界
  const hpBad = clone(good)
  hpBad.sides[0].hp = 99
  bads.push(hpBad)
  // 牌库里塞一张不存在的卡
  const idBad = clone(good)
  idBad.sides[0].deck[0] = 'not_a_card'
  bads.push(idBad)
  // 场上超过 7 个
  const boardBad = clone(good)
  const spare = { uid: 900, card: 'spark', attack: 1, health: 2, maxHealth: 2, taunt: false, shield: false, sick: false, attacks: 1 }
  while (boardBad.sides[0].board.length < 8) {
    boardBad.sides[0].board.push({ ...spare, uid: 900 + boardBad.sides[0].board.length })
  }
  bads.push(boardBad)
  // 能量超过上限(后手幸运币那回合允许 +1,所以这里 +2 才是坏档)
  const energyBad = clone(good)
  energyBad.sides[0].energy = energyBad.sides[0].maxEnergy + 2
  bads.push(energyBad)
  // 幸运币字段不合法
  const coinBad = clone(good)
  coinBad.sides[0].coin = 3
  bads.push(coinBad)
  for (const raw of bads) assert.equal(loadGame(raw), null, `这个存档应该被拒绝:${JSON.stringify(raw)?.slice(0, 60)}`)
  // 正常档仍然读得出来
  assert.ok(loadGame(clone(good)))
})

test('召唤物(灯苗)不能出现在牌库或手牌里:这种档是坏的', () => {
  const s = midGame(15)
  const bad = clone(s)
  bad.sides[0].deck.push('wisp')
  assert.equal(loadGame(bad), null)
  const bad2 = clone(s)
  bad2.sides[1].hand.push('wisp')
  assert.equal(loadGame(bad2), null)
  // 场上可以,存档正常
  let ok = fresh(17)
  ok = placeMinion(ok, 0, 'wisp')
  assert.ok(loadGame(JSON.parse(JSON.stringify(ok))))
})

test('存档大小:打到中后期也远小于云端每键 64 KB', () => {
  const s = midGame(19)
  // 手牌和场面塞满(最坏情况):牌库 26 张 + 手牌 10 张 + 双方各 7 个随从
  let fat = clone(s)
  const all = fat.sides[0].deck.concat(fat.sides[1].deck)
  fat.sides[0].hand = all.slice(0, 10)
  fat.sides[1].hand = all.slice(10, 20)
  fat.sides[0].deck = all.slice(20)
  fat.sides[1].deck = []
  for (const side of [0, 1] as const) {
    while (fat.sides[side].board.length < 7) fat = placeMinion(fat, side, side === 0 ? 'spark' : 'scout')
  }
  const json = JSON.stringify(saveGame(fat))
  assert.ok(json.length < 64 * 1024, `存档 ${json.length} 字节,超过 64 KB`)
  assert.ok(loadGame(JSON.parse(json)), '压满的状态也要能读回来')
})

test('战绩档案 v2:胜负/连胜/每套牌胜场/斩杀/疲劳/满血/困难/单局纪录都记对', () => {
  let p = newProfile()
  assert.deepEqual([p.games, p.wins, p.streak, p.bestStreak], [0, 0, 0, 0])
  p = recordResult(p, outcome())
  p = recordResult(p, outcome({ hero: 'frost', level: 'hard', myHp: 30, dealt: 31, played: 15 }))
  p = recordResult(p, outcome({ hero: 'dusk', reason: 'fatigue', myHp: 8, dealt: 20 }))
  assert.deepEqual([p.games, p.wins, p.streak, p.bestStreak], [3, 3, 3, 3])
  assert.deepEqual(p.winsByHero, { forge: 1, frost: 1, dusk: 1 })
  assert.equal(p.lethals, 2) // 两局 hp 收尾,疲劳那局不算
  assert.equal(p.fatigueWins, 1)
  assert.equal(p.flawlessWins, 2) // 前两局都是满血
  assert.equal(p.hardWins, 1)
  assert.equal(p.maxDealt, 31)
  assert.equal(p.maxPlayed, 15)
  // 输一局:连胜清零,但累计纪录保留
  p = recordResult(p, outcome({ won: false, myHp: 0, dealt: 5, played: 2 }))
  assert.deepEqual([p.games, p.wins, p.streak, p.bestStreak], [4, 3, 0, 3])
  assert.equal(p.lethals, 2)
  assert.equal(p.lastHero, 'forge')
  // 上次的选择记得住;新手提示看过就记住
  assert.equal(rememberChoice(p, 'forge', 'normal'), p)
  assert.equal(rememberChoice(p, 'dusk', 'easy').lastHero, 'dusk')
  const seen = markTutorialSeen(p)
  assert.equal(seen.tutorialSeen, true)
  assert.equal(markTutorialSeen(seen), seen)
  // 成就写进档案不重复
  const withAch = withAchievements(p, ['first_win', 'first_win'])
  assert.deepEqual(withAch.achievements, ['first_win'])
  assert.equal(withAchievements(withAch, []), withAch)
})

test('读档:坏档当作全新;v1 旧档升级到 v2(不丢场次);两设备合并取大的、成就取并集', () => {
  assert.equal(loadProfile(null), null)
  assert.equal(loadProfile({}), null)
  const p = recordResult(newProfile(), outcome())
  assert.equal(loadProfile({ ...p, v: 3 }), null)
  assert.equal(loadProfile({ ...p, wins: 99 }), null)
  assert.equal(loadProfile({ ...p, lastHero: 'nobody' }), null)
  assert.equal(loadProfile({ ...p, lastLevel: 'nightmare' as Level }), null)
  // v1 旧档(只有基础字段)能读,成就累计数补 0
  const v1 = { v: 1, games: 7, wins: 4, streak: 1, bestStreak: 3, lastHero: 'frost', lastLevel: 'hard' }
  const upgraded = loadProfile(v1)
  assert.ok(upgraded)
  assert.deepEqual([upgraded.games, upgraded.wins, upgraded.bestStreak], [7, 4, 3])
  assert.equal(upgraded.lethals, 0)
  assert.deepEqual(upgraded.achievements, [])
  assert.equal(loadProfile(JSON.parse(JSON.stringify(p)))?.wins, p.wins)
  // 两台设备:场次/胜场/累计取大的,成就并集,新手提示看过就算看过
  const a = withAchievements({ ...recordResult(newProfile(), outcome()), games: 5, wins: 3 }, ['first_win'])
  const b = withAchievements({ ...recordResult(newProfile(), outcome({ hero: 'frost' })), games: 9, wins: 2 }, ['streak3'])
  const m = mergeProfile(a, b)
  assert.equal(m.games, 9)
  assert.equal(m.wins, Math.max(a.wins, b.wins))
  assert.deepEqual(m.achievements.slice().sort(), ['first_win', 'streak3'])
  assert.equal(m.lastHero, b.lastHero)
  // 合并后的档案仍然能读
  assert.ok(loadProfile(m))
})

test('读档后还能继续操作(存档与引擎对同一个状态达成一致)', () => {
  const s = midGame(21)
  const back = loadGame(JSON.parse(JSON.stringify(saveGame(s)))) as GameState
  assert.ok(back)
  const t = setTurn(back, 1)
  const a = aiNext(t, 'hard')
  const r = applyAction(t, a)
  assert.ok(r.ok)
  assert.ok(loadGame(JSON.parse(JSON.stringify(r.state))), '打完之后仍然是一份合法存档')
  const u = hand(back, 1, ['spark'], 10)
  const play = applyAction(setTurn(u, 1), { kind: 'play', hand: 0, target: null })
  assert.ok(play.ok)
})

test('后手幸运币那一回合的存档:能量比上限多 1 也能原样读回来', () => {
  let s = newGame({ seed: 88, hero0: 'forge', hero1: 'frost' }).state
  const r1 = applyAction(s, { kind: 'end' })
  assert.ok(r1.ok)
  s = r1.state
  // 后手第一回合开始:1 点水晶 + 幸运币,能量 2(比上限多 1),coin 已用掉
  assert.equal(s.sides[1].maxEnergy, 1)
  assert.equal(s.sides[1].energy, 2)
  assert.equal(s.sides[1].coin, 0)
  const back = loadGame(JSON.parse(JSON.stringify(saveGame(s))))
  assert.ok(back, '后手幸运币当回合的存档不应该被判成坏档')
  assert.deepEqual(back, s)
})

test('1.0 旧档兼容:没有 coin 字段也能读回来,局面一点不丢', () => {
  // 模拟 1.0(1.1 之前)的存档:整份 JSON 里没有 coin 字段
  const cur = midGame(31)
  const old = JSON.parse(JSON.stringify(saveGame(cur))) as Record<string, unknown>
  for (const side of old.sides as Array<Record<string, unknown>>) delete side.coin
  for (const side of (old.sides as Array<Record<string, unknown>>)) assert.equal('coin' in side, false)
  const back = loadGame(old)
  assert.ok(back, '1.0 形态的存档不应该被判成坏档')
  // 局面完全一致:回合/先后手/双方英雄血量/手牌/牌库/场面/疲劳
  assert.equal(back.turn, cur.turn)
  assert.equal(back.active, cur.active)
  assert.equal(back.nextUid, cur.nextUid)
  for (const side of [0, 1] as const) {
    const a = back.sides[side]
    const b = cur.sides[side]
    assert.equal(a.hp, b.hp)
    assert.equal(a.energy, b.energy)
    assert.equal(a.maxEnergy, b.maxEnergy)
    assert.equal(a.coin, 0, '缺失的 coin 应该补成 0')
    assert.deepEqual(a.hand, b.hand)
    assert.deepEqual(a.deck, b.deck)
    assert.deepEqual(a.board, b.board)
    assert.equal(a.fatigue, b.fatigue)
  }
  // 读回来还能继续打,而且再存一次就是带 coin 的新格式
  const play = applyAction(back, aiNext(setTurn(back, back.active), 'normal'))
  assert.ok(play.ok)
  const re = JSON.parse(JSON.stringify(saveGame(play.state))) as { sides: Array<Record<string, unknown>> }
  assert.equal(typeof re.sides[0].coin, 'number')
  assert.ok(loadGame(re))
  // 旧版随从身材是当时快照(比如冰壳卫士 1.0 是 4/6、1.1 改成 4/5),读档不能被新数值推翻
  const snap = clone(cur)
  snap.sides[0].board.push({ uid: 9999, card: 'r_shell', attack: 4, health: 6, maxHealth: 6, taunt: false, shield: true, sick: false, attacks: 1 })
  const oldBoard = JSON.parse(JSON.stringify(saveGame(snap))) as Record<string, unknown>
  for (const side of oldBoard.sides as Array<Record<string, unknown>>) delete side.coin
  const restored = loadGame(oldBoard)
  assert.ok(restored)
  const shell = restored.sides[0].board.find((m) => m.uid === 9999)
  assert.ok(shell)
  assert.equal(shell.health, 6)
  assert.equal(shell.maxHealth, 6)
})
