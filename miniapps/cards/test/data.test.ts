// 卡牌 / 英雄 / 卡组数据自检:数值合法、关键字和效果对得上、三套卡组各 30 张、没有侵权名字。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  CARDS, HEROES, card, copiesIn, hero, keywordsOf, targetKindOf,
} from '../src/data'
import { DECK_SIZE, MAX_COPIES, type CardDef, type Effect } from '../src/types'

const collectible = CARDS.filter((c) => !c.token)
const minions = collectible.filter((c) => c.type === 'minion')
const spells = collectible.filter((c) => c.type === 'spell')

test('卡牌 id 唯一、名字唯一,可收集卡一共 36 张', () => {
  const ids = CARDS.map((c) => c.id)
  assert.equal(new Set(ids).size, ids.length, 'id 有重复')
  const names = CARDS.map((c) => c.name)
  assert.equal(new Set(names).size, names.length, '名字有重复')
  assert.equal(collectible.length, 36, `可收集卡应该是 36 张,实际 ${collectible.length}`)
  assert.equal(minions.length + spells.length, 36)
  assert.equal(CARDS.length, 37, '36 张可收集 + 1 张召唤物')
})

test('费用和身材合法:费用 0–10,随从攻击/生命都是正整数,法术没有身材', () => {
  for (const c of CARDS) {
    assert.ok(Number.isInteger(c.cost) && c.cost >= 0 && c.cost <= 10, `${c.name} 费用不合法`)
    assert.ok(c.text !== undefined && typeof c.text === 'string')
    assert.ok(c.flavor.length > 0, `${c.name} 缺风味文案`)
    if (c.type === 'minion') {
      assert.ok(Number.isInteger(c.attack) && (c.attack as number) >= 0, `${c.name} 攻击不合法`)
      assert.ok(Number.isInteger(c.health) && (c.health as number) >= 1, `${c.name} 生命不合法`)
      assert.equal(c.spell, undefined, `${c.name} 是随从却带了法术效果`)
    } else {
      assert.equal(c.attack, undefined, `${c.name} 是法术却带了攻击`)
      assert.equal(c.health, undefined, `${c.name} 是法术却带了生命`)
      assert.ok(c.spell, `${c.name} 是法术却没有效果`)
      assert.equal(c.battlecry, undefined)
      assert.equal(c.deathrattle, undefined)
    }
    // 关键字和文本要对得上,卡面才不会被玩家说「字和效果不一样」
    if (c.taunt) assert.match(c.text, /嘲讽/)
    if (c.charge) assert.match(c.text, /冲锋/)
    if (c.shield) assert.match(c.text, /圣盾/)
    if (c.battlecry) assert.match(c.text, /战吼/)
    if (c.deathrattle) assert.match(c.text, /亡语/)
  }
})

function checkEffect(e: Effect, where: string): void {
  switch (e.kind) {
    case 'damage':
    case 'aoe':
    case 'heal':
    case 'heroDamage':
      assert.ok(Number.isInteger(e.amount) && e.amount > 0, `${where}:伤害/治疗量不合法`)
      break
    case 'draw':
      assert.ok(Number.isInteger(e.count) && e.count > 0 && e.count <= 3, `${where}:抽牌数不合法`)
      break
    case 'buff':
    case 'buffSelf':
      assert.ok(e.attack > 0 && e.health > 0, `${where}:buff 数值不合法`)
      break
    case 'summon': {
      const c = card(e.card)
      assert.equal(c.type, 'minion', `${where}:召唤的不是随从`)
      assert.ok(c.token, `${where}:召唤的应该是召唤物`)
      assert.ok(Number.isInteger(e.count) && e.count >= 1 && e.count <= 3, `${where}:召唤数不合法`)
      break
    }
  }
}

test('效果数据合法:战吼/亡语/法术的数值和召唤目标都对得上', () => {
  for (const c of CARDS) {
    if (c.battlecry) checkEffect(c.battlecry, `${c.name} 战吼`)
    if (c.deathrattle) checkEffect(c.deathrattle, `${c.name} 亡语`)
    if (c.spell) checkEffect(c.spell, `${c.name} 法术`)
  }
  // 亡语不能要求选目标(死亡结算时没人给它点目标)
  for (const c of CARDS) {
    if (!c.deathrattle) continue
    const k = c.deathrattle.kind
    assert.ok(k === 'aoe' || k === 'draw' || k === 'summon' || k === 'heroDamage', `${c.name} 的亡语不该要目标`)
  }
  // 战吼/法术要选目标时,目标类型只有「敌方」「友方」「友方随从」三种
  for (const c of CARDS) {
    const k = targetKindOf(c)
    assert.ok(['none', 'enemy', 'friendly', 'friendlyMinion'].includes(k))
    if (c.type === 'minion' && k !== 'none') {
      assert.ok(k === 'enemy' || k === 'friendly', `${c.name}:随从战吼的目标类型不合法`)
    }
  }
})

test('效果种类够用:战吼 ≥3 种、亡语 ≥3 种、法术覆盖伤害/群伤/治疗/抽牌/加攻', () => {
  const battlecries = new Set(CARDS.filter((c) => c.battlecry).map((c) => (c.battlecry as Effect).kind))
  const rattles = new Set(CARDS.filter((c) => c.deathrattle).map((c) => (c.deathrattle as Effect).kind))
  const spellKinds = new Set(spells.map((c) => (c.spell as Effect).kind))
  assert.ok(battlecries.size >= 3, `战吼只有 ${battlecries.size} 种`)
  assert.ok(rattles.size >= 3, `亡语只有 ${rattles.size} 种`)
  for (const k of ['damage', 'aoe', 'heal', 'draw', 'buff'] as const) {
    assert.ok(spellKinds.has(k), `法术缺少 ${k}`)
  }
  const keywords = new Set(collectible.flatMap((c) => keywordsOf(c)))
  for (const k of ['嘲讽', '冲锋', '圣盾', '战吼', '亡语']) assert.ok(keywords.has(k), `卡牌缺少关键字 ${k}`)
})

test('三套预组卡组各 30 张、同一张最多 2 份、只带本职业 + 中立卡', () => {
  assert.equal(HEROES.length, 3)
  for (const h of HEROES) {
    assert.equal(h.deck.length, DECK_SIZE, `${h.name} 的卡组不是 30 张`)
    const seen = new Map<string, number>()
    for (const id of h.deck) {
      const c = card(id)
      assert.ok(!c.token, `${h.name} 的卡组里出现了召唤物 ${id}`)
      assert.ok(c.cls === 'neutral' || c.cls === h.cls, `${h.name} 带了别的职业的卡 ${c.name}`)
      seen.set(id, (seen.get(id) || 0) + 1)
    }
    for (const [id, n] of seen) {
      assert.ok(n <= MAX_COPIES, `${h.name} 的 ${card(id).name} 带了 ${n} 份`)
    }
    // 7 张职业卡 ×2 + 8 张中立卡 ×2 = 15 种 30 张
    assert.equal(seen.size, 15, `${h.name} 卡组只有 ${seen.size} 种卡`)
    assert.equal(copiesIn(h.deck, h.deck[0]), 2, '每种卡都应该带 2 份')
    assert.equal(hero(h.id).deck.length, 30)
  }
  // 三套卡组都能正常开局
  const heroes = HEROES.map((h) => h.id)
  assert.equal(new Set(heroes).size, 3)
})

test('原创性:名字和文案里没有别家卡牌游戏的名字', () => {
  const banned = ['炉石', '暴雪', '魔兽', 'hearthstone', 'blizzard', 'warcraft', '影之诗', 'shadowverse',
    '万智牌', 'magic: the gathering', '游戏王', 'yu-gi-oh', 'artifact', 'lor', '符文之地']
  const text = [
    ...CARDS.flatMap((c: CardDef) => [c.name, c.text, c.flavor]),
    ...HEROES.flatMap((h) => [h.name, h.title, h.style, h.desc]),
  ].join('\n').toLowerCase()
  for (const word of banned) assert.equal(text.includes(word), false, `文案里出现了 ${word}`)
  // 也不能出现现实商标/名人
  for (const word of ['麦当劳', '可口可乐', '马斯克', '特朗普', '米老鼠', '宝可梦', 'pokemon']) {
    assert.equal(text.includes(word), false, `文案里出现了 ${word}`)
  }
})
