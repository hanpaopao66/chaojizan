// 存档单测:对局状态能整份来回、坏档当作没有、召唤物不能混进牌库、
// 战绩档案的胜负/连胜/两台设备合并、以及存档大小不超过云端的 64 KB。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { aiNext } from '../src/ai'
import { applyAction, loadGame, newGame, placeMinion, saveGame } from '../src/engine'
import {
  loadProfile, mergeProfile, newProfile, recordResult, rememberChoice,
} from '../src/profile'
import type { GameState } from '../src/types'
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
  // 能量超过上限
  const energyBad = clone(good)
  energyBad.sides[0].energy = energyBad.sides[0].maxEnergy + 1
  bads.push(energyBad)
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

test('战绩档案:记录胜负和连胜、最佳连胜;坏档当作全新;两设备合并取大的', () => {
  let p = newProfile()
  assert.deepEqual([p.games, p.wins, p.streak, p.bestStreak], [0, 0, 0, 0])
  p = recordResult(p, true, 'forge', 'normal')
  p = recordResult(p, true, 'forge', 'normal')
  p = recordResult(p, true, 'forge', 'hard')
  assert.deepEqual([p.games, p.wins, p.streak, p.bestStreak], [3, 3, 3, 3])
  p = recordResult(p, false, 'frost', 'hard')
  assert.deepEqual([p.games, p.wins, p.streak, p.bestStreak], [4, 3, 0, 3])
  assert.equal(p.lastHero, 'frost')
  assert.equal(p.lastLevel, 'hard')
  // 上次的选择记得住
  assert.equal(rememberChoice(p, 'frost', 'hard'), p)
  const q = rememberChoice(p, 'dusk', 'normal')
  assert.equal(q.lastHero, 'dusk')
  // 读档:全新的、坏的都当作没有
  assert.equal(loadProfile(null), null)
  assert.equal(loadProfile({ ...p, v: 2 }), null)
  assert.equal(loadProfile({ ...p, wins: 99 }), null)
  assert.equal(loadProfile({ ...p, lastHero: 'nobody' }), null)
  assert.deepEqual(loadProfile(JSON.parse(JSON.stringify(p))), p)
  // 两台设备:各打了 3 局 / 5 局,取大的 5 局;连胜取大的;上次选择跟局数多的
  const a = recordResult(newProfile(), true, 'forge', 'normal')
  const b = { ...recordResult({ ...newProfile(), games: 4, wins: 1 }, false, 'dusk', 'hard') }
  const m = mergeProfile(a, b)
  assert.equal(m.games, b.games)
  assert.equal(m.wins, Math.max(a.wins, b.wins))
  assert.equal(m.bestStreak, Math.max(a.bestStreak, b.bestStreak))
  assert.equal(m.lastHero, b.lastHero)
})

test('读档后还能继续操作(存档与引擎对同一个状态达成一致)', () => {
  const s = midGame(21)
  const back = loadGame(JSON.parse(JSON.stringify(saveGame(s)))) as GameState
  assert.ok(back)
  // 换到电脑行动,读回来的档也能让 AI 接着算
  const t = setTurn(back, 1)
  const a = aiNext(t, 'hard')
  const r = applyAction(t, a)
  assert.ok(r.ok)
  assert.ok(loadGame(JSON.parse(JSON.stringify(r.state))), '打完之后仍然是一份合法存档')
  // 手里有牌时能正常出牌(存档没有破坏手牌结构)
  const u = hand(back, 1, ['spark'], 10)
  const play = applyAction(setTurn(u, 1), { kind: 'play', hand: 0, target: null })
  assert.ok(play.ok)
})
