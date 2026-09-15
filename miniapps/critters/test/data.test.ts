import assert from 'node:assert/strict'
import { test } from 'node:test'
import { SOUNDS, UNITS, WORLD } from '../src/art'
import {
  ACHIEVEMENTS, CARDS, CHAPTERS, COLLECTION, LEVELS, STARTERS, Theme, UPGRADE_COST, card,
} from '../src/data'

test('每关:电脑卡组 8 张、卡都存在;第一颗星都是「赢」;时长合理', () => {
  assert.equal(LEVELS.length, 25)
  for (const L of LEVELS) {
    assert.equal(L.enemy.length, 8, L.id)
    for (const id of L.enemy) assert.ok(CARDS[id], `${L.id} 的 ${id} 不存在`)
    assert.equal(L.stars[0].kind, 'win', L.id)
    assert.ok(L.duration >= 90 && L.duration <= 180, L.id)
    if (L.objective === 'blitz') assert.ok((L.target || 0) >= 1, L.id)
    for (const l of L.closed || []) assert.ok(l >= 0 && l <= 2)
    assert.ok((L.closed || []).length < 3)
  }
})

test('收藏 = 开局 8 张 + 各关第一次通关解锁的,每张只在一关解锁,不抽卡', () => {
  const unlocks = LEVELS.filter((L) => L.unlock).map((L) => L.unlock as string)
  assert.equal(new Set(unlocks).size, unlocks.length, '同一张卡在两关解锁')
  for (const id of unlocks) assert.ok(!CARDS[id].aiOnly && STARTERS.indexOf(id) < 0, id)
  assert.deepEqual([...STARTERS, ...unlocks].sort(), COLLECTION.slice().sort())
  assert.equal(STARTERS.length, 8)
})

test('每章最后一关是 Boss 关,Boss 在电脑的卡组里;Boss 只给电脑用', () => {
  for (const ch of CHAPTERS) {
    const L = LEVELS.find((x) => x.id === `${ch.n}-5`)!
    assert.ok(L.boss, `${ch.n}-5 不是 Boss 关`)
    assert.ok(L.enemy.indexOf(ch.boss) >= 0, `${ch.n}-5 的卡组里没有 ${ch.boss}`)
    assert.ok(card(ch.boss).boss && card(ch.boss).aiOnly)
  }
  for (const id of COLLECTION) assert.ok(!card(id).boss && !card(id).aiOnly, id)
})

test('每张卡的数值说得通', () => {
  for (const c of Object.values(CARDS)) {
    assert.ok(c.cost >= 1 && c.cost <= 9, `${c.id} 费用`)
    assert.ok(c.name && c.desc && c.tags.length, c.id)
    if (c.kind === 'spell') {
      assert.ok(c.spell && c.spell.radius > 0, c.id)
      continue
    }
    const u = c.unit!
    assert.ok(u.hp > 0 && u.radius > 0 && u.rate > 0, c.id)
    if (c.kind === 'building') assert.ok(u.speed === 0 && (u.life || 0) > 0, `${c.id} 建筑要有寿命`)
    else assert.ok(u.speed > 0 && u.atk > 0, c.id)
    if (u.spawn) assert.ok(CARDS[u.spawn.card], c.id)
  }
  // 升级越来越贵
  for (let i = 2; i < UPGRADE_COST.length; i++) assert.ok(UPGRADE_COST[i] > UPGRADE_COST[i - 1])
})

test('美术齐全:每张卡的画都在图集里,每个主题的草地、土路、树都在,塔和废墟都在', () => {
  for (const c of Object.values(CARDS)) assert.ok(UNITS.frames[c.art], `缺 ${c.art} 的画`)
  const trees: Record<Theme, string> = { meadow: 'green', swamp: 'dark', snow: 'snow', jungle: 'dark', highland: 'orange' }
  for (const ch of CHAPTERS) {
    for (const k of [`grass-${ch.theme}-0`, `grass-${ch.theme}-1`, `dirt-${ch.theme}`, `tree-${trees[ch.theme]}-0`]) {
      assert.ok(WORLD.frames[k], `缺 ${k}`)
    }
  }
  for (const k of ['tower-0', 'tower-1', 'base-0', 'base-1', 'ruin-tower-0', 'ruin-tower-1', 'ruin-base-0', 'ruin-base-1']) {
    assert.ok(WORLD.frames[k], `缺 ${k}`)
  }
  assert.ok(SOUNDS.length >= 20)
})

test('成就:id 不重复,目标都是正数', () => {
  assert.equal(new Set(ACHIEVEMENTS.map((a) => a.id)).size, ACHIEVEMENTS.length)
  for (const a of ACHIEVEMENTS) assert.ok(a.n > 0 && a.coins > 0, a.id)
})
