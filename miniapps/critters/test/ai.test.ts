import assert from 'node:assert/strict'
import { test } from 'node:test'
import { newBattle, place, run, step } from '../src/battle'
import { AI_EASY, AI_HARD, AI_NORMAL, AiParams, LANE_X, LEVEL_BY_ID, STARTERS, TOWER_Y, ZONE } from '../src/data'
import { Battle, BattleConfig } from '../src/field'
import { levelConfig, newProfile } from '../src/progress'

const lv = (ids: string[], n = 1) => Object.fromEntries(ids.map((i) => [i, n]))

function cfg(ai: [AiParams | null, AiParams | null], over: Partial<BattleConfig> = {}): BattleConfig {
  return {
    seed: 11, duration: 150, objective: 'siege', target: 0,
    decks: [{ cards: STARTERS, levels: lv(STARTERS) }, { cards: STARTERS, levels: lv(STARTERS) }],
    ai, regen: [1, 1], startEnergy: [5, 5], towerHp: [1, 1], towerLevel: [1, 1], closed: [], speed: 1,
    stars: [{ kind: 'win' }, { kind: 'lost', n: 1 }, { kind: 'lost', n: 0 }], tag: 'test', theme: 'meadow', ...over,
  }
}

/** 走到结束(或走满 max 步),顺手收集所有出牌事件 */
function playOut(b: Battle, max = 20 * 400): { end: Battle; plays: Array<{ side: number; card: string; x: number; y: number; t: number }> } {
  const plays: Array<{ side: number; card: string; x: number; y: number; t: number }> = []
  let s = b
  for (let i = 0; i < max && !s.over; i++) {
    const r = step(s)
    s = r.state
    for (const e of r.events) if (e.e === 'play') plays.push({ side: e.side, card: e.card, x: e.x, y: e.y, t: s.t })
  }
  return { end: s, plays }
}

test('电脑会出牌,出的都合法:能量从不为负,单位都放在自己半场', () => {
  let b = newBattle(cfg([null, AI_NORMAL]))
  let played = 0
  for (let i = 0; i < 20 * 60; i++) {
    const r = step(b)
    b = r.state
    assert.ok(b.sides[1].energy >= -1e-9, `能量 ${b.sides[1].energy}`)
    for (const e of r.events) {
      if (e.e !== 'play' || e.side !== 1) continue
      played++
      if (e.card !== 'fire') assert.ok(e.y >= ZONE[1][0] - 1e-9 && e.y <= ZONE[1][1] + 1e-9, `落在 y=${e.y}`)
    }
  }
  assert.ok(played >= 5, `一分钟只出了 ${played} 张`)
})

test('敌人压到塔下,电脑会在那一路守', () => {
  let b = newBattle(cfg([null, { ...AI_NORMAL, react: 0.5, skill: 1 }]))
  b = { ...b, sides: [b.sides[0], { ...b.sides[1], energy: 10 }] }
  b = place(b, 'bear', 0, 2, LANE_X[2], TOWER_Y[1] + 2.4)
  const { plays } = playOut(b, 20 * 4)
  const mine = plays.filter((p) => p.side === 1)
  assert.ok(mine.some((p) => Math.abs(p.x - LANE_X[2]) < 1), `四秒内没在右路出牌:${JSON.stringify(mine)}`)
})

test('手里有 Boss:攒够能量先上 Boss', () => {
  const enemy = ['buffalo', 'chick', 'rabbit', 'pig', 'duck', 'dog', 'cow', 'fence']
  const b = newBattle(cfg([null, AI_NORMAL], { decks: [{ cards: STARTERS, levels: lv(STARTERS) }, { cards: enemy, levels: lv(enemy) }] }))
  assert.ok(b.sides[1].hand.indexOf('buffalo') >= 0, 'Boss 开局就在手里')
  const { plays } = playOut(b, 20 * 40)
  const first = plays.find((p) => p.side === 1)
  assert.equal(first?.card, 'buffalo')
})

test('电脑对电脑:每一局都在规定时间里分出结果', () => {
  for (const id of ['1-3', '2-2', '3-3', '4-4', '5-2']) {
    const L = LEVEL_BY_ID[id]
    const c = levelConfig(newProfile(), L, 5)
    c.ai = [AI_NORMAL, L.ai]
    const { end } = playOut(newBattle(c))
    assert.ok(end.over, `${id} 没结束`)
    assert.ok(end.over!.t <= L.duration + 1e-9)
  }
})

test('难的电脑打得过简单的(同样的卡、同样的等级)', () => {
  let hard = 0
  for (let seed = 1; seed <= 10; seed++) {
    const end = run(newBattle(cfg([AI_HARD, AI_EASY], { seed })), 20 * 400)
    if (end.over?.winner === 0) hard++
  }
  assert.ok(hard >= 7, `十局只赢了 ${hard} 局`)
})

test('第一关:普通水平的「玩家」(电脑代打,1 级卡)大多能赢', () => {
  let won = 0
  for (let seed = 1; seed <= 12; seed++) {
    const c = levelConfig(newProfile(), LEVEL_BY_ID['1-1'], seed * 7919)
    c.ai = [AI_NORMAL, c.ai[1]]
    if (run(newBattle(c), 20 * 400).over?.winner === 0) won++
  }
  assert.ok(won >= 9, `12 局只赢了 ${won} 局`)
})
