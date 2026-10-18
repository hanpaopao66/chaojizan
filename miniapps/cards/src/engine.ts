// 星火牌局的规则引擎:开局、回合、出牌、攻击、死亡结算、胜负、存档校验。
//
// 全部是纯函数:传进来的对局不改,返回新的一份;同一步发生的事放在 events 里给界面放动画、给读屏播报。
// 规则(和「关于」里写的一致):
// - 双方英雄 30 点生命,能量上限每回合 +1(最多 10 点),回合开始回满;手牌上限 10,牌库 30 张,
//   牌库抽空后每次抽牌受到 1、2、3… 递增的疲劳伤害;
// - 每方场上最多 7 个随从;随从上场当回合不能攻击(召唤失调),「冲锋」除外;每个随从每回合攻击一次;
// - 攻击时双方同时互相造成等于攻击力的伤害;「圣盾」免疫第一次伤害;对面有「嘲讽」必须先打嘲讽;
// - 「战吼」从手里打出时触发,「亡语」死亡时触发;死亡结算顺序固定:先玩家方(按从左到右),
//   再电脑方(按从左到右),每处理完一个就从头重新扫描,保证同样的局面结果永远一样。
import { shuffle } from '../../shared/src/rand'
import { card, cardOrNull, hero, heroOrNull, targetKindOf } from './data'
import {
  Action, ActionResult, Check, DECK_SIZE, Effect, Ev, GameState, MAX_BOARD, MAX_ENERGY, MAX_HAND, Minion,
  NewGameOptions, OverReason, Side, SideState, START_HP, TargetRef, foe,
} from './types'

// ---------------------------------------------------------------- 小工具

const cloneSide = (s: SideState): SideState => ({
  ...s, deck: s.deck.slice(), hand: s.hand.slice(), board: s.board.map((m) => ({ ...m })),
})

/** 深拷一份对局(状态里全是可 JSON 的数据,手动拷比 JSON 往返快得多) */
function clone(s: GameState): GameState {
  return {
    ...s,
    sides: [cloneSide(s.sides[0]), cloneSide(s.sides[1])],
    over: s.over ? { ...s.over } : null,
  }
}

/** 找场上的随从 */
export function findMinion(s: GameState, side: Side, uid: number): Minion | undefined {
  return s.sides[side].board.find((m) => m.uid === uid)
}

const sameTarget = (a: TargetRef, b: TargetRef): boolean =>
  a.kind === b.kind && a.side === b.side && (a.kind === 'hero' || (b.kind === 'minion' && a.uid === b.uid))

const targetFor = (side: Side, uid: number): TargetRef => ({ kind: 'minion', side, uid })
const heroTarget = (side: Side): TargetRef => ({ kind: 'hero', side })

// ---------------------------------------------------------------- 开局

export function newGame(o: NewGameOptions): { state: GameState; events: Ev[] } {
  const h0 = hero(o.hero0)
  const h1 = hero(o.hero1)
  let seed = o.seed >>> 0
  let deck0: string[]
  let deck1: string[]
  ;[deck0, seed] = shuffle(h0.deck, seed)
  ;[deck1, seed] = shuffle(h1.deck, seed)
  const side = (id: string, deck: string[], handN: number): SideState => ({
    hero: id, hp: START_HP, energy: 0, maxEnergy: 0, deck: deck.slice(handN), hand: deck.slice(0, handN),
    board: [], fatigue: 0, coin: 0, played: 0, dealt: 0, lost: 0,
  })
  // 先手 3 张、后手 4 张;开局的第一回合会再各抽 1 张(和一般卡牌对战的手牌数对得上)
  const first = o.first ?? 0
  const s0 = side(h0.id, deck0, first === 0 ? 3 : 4)
  const s1 = side(h1.id, deck1, first === 1 ? 3 : 4)
  const state: GameState = { v: 1, seed, turn: 1, active: first, sides: [s0, s1], nextUid: 1, over: null }
  // 后手补偿(约等于别家卡牌的「幸运币」):后手的第一回合额外多 1 点能量,只多这一回合。
  // 先手天然占主动(先下随从、先攻击),不补一点会滚雪球;补成永久 +1 又太强,所以做成一次性的。
  state.sides[foe(first)].coin = 1
  const events: Ev[] = []
  beginTurn(state, events)
  return { state, events }
}

// ---------------------------------------------------------------- 抽牌 / 伤害 / 治疗

/** 抽一张。牌库空了就受疲劳伤害;手牌满了就烧掉(牌离开牌库,不进手牌) */
function drawOne(n: GameState, side: Side, ev: Ev[]): void {
  const s = n.sides[side]
  if (s.deck.length === 0) {
    s.fatigue += 1
    const dmg = s.fatigue
    s.hp -= dmg
    ev.push({ e: 'fatigue', side, amount: dmg })
    ev.push({ e: 'damage', target: heroTarget(side), amount: dmg, shielded: false })
    checkOver(n, ev, 'fatigue')
    return
  }
  const id = s.deck.shift() as string
  if (s.hand.length >= MAX_HAND) {
    ev.push({ e: 'burn', side, card: id })
    return
  }
  s.hand.push(id)
  ev.push({ e: 'draw', side, card: id })
}

/**
 * 扣血。by 是造成伤害的一方(统计用;疲劳算自己打自己)。返回实际扣掉的数字。
 * 圣盾挡下整次伤害并破盾;英雄生命不会扣成负数(界面好显示)。
 */
function dealDamage(n: GameState, target: TargetRef, amount: number, by: Side, ev: Ev[]): number {
  if (amount <= 0) return 0
  if (target.kind === 'hero') {
    const s = n.sides[target.side]
    const d = Math.min(amount, Math.max(0, s.hp))
    if (d > 0) {
      s.hp -= d
      if (foe(target.side) === by) n.sides[by].dealt += d
      ev.push({ e: 'damage', target, amount: d, shielded: false })
    }
    checkOver(n, ev, 'hp')
    return d
  }
  const m = findMinion(n, target.side, target.uid)
  if (!m || m.health <= 0) return 0
  if (m.shield) {
    m.shield = false
    ev.push({ e: 'damage', target, amount: 0, shielded: true })
    ev.push({ e: 'shield', target })
    return 0
  }
  const d = Math.min(amount, m.health)
  m.health -= d
  if (foe(target.side) === by) n.sides[by].dealt += d
  ev.push({ e: 'damage', target, amount: d, shielded: false })
  return d
}

function healTarget(n: GameState, target: TargetRef, amount: number, ev: Ev[]): void {
  if (amount <= 0) return
  if (target.kind === 'hero') {
    const s = n.sides[target.side]
    const d = Math.min(amount, Math.max(0, START_HP - s.hp))
    if (d <= 0) return
    s.hp += d
    ev.push({ e: 'heal', target, amount: d })
    return
  }
  const m = findMinion(n, target.side, target.uid)
  if (!m || m.health <= 0) return
  const d = Math.min(amount, m.maxHealth - m.health)
  if (d <= 0) return
  m.health += d
  ev.push({ e: 'heal', target, amount: d })
}

/** 往场上放一个随从。从手里打出的随从按规则处理召唤失调和冲锋 */
function addMinion(n: GameState, side: Side, id: string, fromHand: boolean, ev: Ev[]): Minion | null {
  const def = card(id)
  if (def.type !== 'minion') return null
  const s = n.sides[side]
  if (s.board.length >= MAX_BOARD) return null
  const hp = Math.max(1, def.health ?? 1)
  const charge = !!def.charge
  const m: Minion = {
    uid: n.nextUid++, card: id, attack: def.attack ?? 0, health: hp, maxHealth: hp,
    taunt: !!def.taunt, shield: !!def.shield, sick: !(fromHand && charge), attacks: fromHand && charge ? 1 : 0,
  }
  s.board.push(m)
  ev.push({ e: 'summon', side, uid: m.uid, card: id })
  return m
}

/** 测试/开发用:直接往场上放一个随从(不触发战吼)。纯函数,返回新状态 */
export function placeMinion(s: GameState, side: Side, id: string): GameState {
  const n = clone(s)
  addMinion(n, side, id, false, [])
  return n
}

// ---------------------------------------------------------------- 效果

/** 执行一个效果(战吼 / 亡语 / 法术共用)。target 是提前校验过的合法目标 */
function applyEffect(n: GameState, side: Side, effect: Effect, target: TargetRef | null, ev: Ev[]): void {
  switch (effect.kind) {
    case 'damage':
      if (target) dealDamage(n, target, effect.amount, side, ev)
      break
    case 'aoe': {
      // 先记下 uid 再逐个打:中途死掉的随从由 resolveDeaths 统一结算
      const uids = n.sides[foe(side)].board.map((m) => m.uid)
      for (const uid of uids) dealDamage(n, targetFor(foe(side), uid), effect.amount, side, ev)
      break
    }
    case 'heal':
      if (target) healTarget(n, target, effect.amount, ev)
      break
    case 'draw':
      for (let i = 0; i < effect.count; i++) drawOne(n, side, ev)
      break
    case 'buff': {
      if (!target || target.kind !== 'minion') break
      const m = findMinion(n, side, target.uid)
      if (!m || m.health <= 0) break
      m.attack += effect.attack
      m.maxHealth += effect.health
      m.health += effect.health
      ev.push({ e: 'buff', target, attack: effect.attack, health: effect.health })
      break
    }
    case 'buffSelf':
      break // 由 playCard 处理(它知道刚上场的是哪一只)
    case 'buffAll':
      for (const m of n.sides[side].board) {
        if (m.health <= 0) continue
        m.attack += effect.attack
        m.maxHealth += effect.health
        m.health += effect.health
        ev.push({ e: 'buff', target: targetFor(side, m.uid), attack: effect.attack, health: effect.health })
      }
      break
    case 'summon':
      for (let i = 0; i < effect.count; i++) addMinion(n, side, effect.card, false, ev)
      break
    case 'heroDamage':
      dealDamage(n, heroTarget(foe(side)), effect.amount, side, ev)
      break
  }
}

// ---------------------------------------------------------------- 死亡与胜负

/** 死亡结算:顺序固定 —— 玩家方最左边先、电脑方最左边先,处理一个后从头扫描 */
function resolveDeaths(n: GameState, ev: Ev[]): void {
  for (let guard = 0; guard < 60; guard++) {
    let died = false
    for (const side of [0, 1] as Side[]) {
      const board = n.sides[side].board
      const i = board.findIndex((m) => m.health <= 0)
      if (i < 0) continue
      const [dead] = board.splice(i, 1)
      n.sides[side].lost += 1
      ev.push({ e: 'death', side, uid: dead.uid, card: dead.card })
      const def = card(dead.card)
      if (def.deathrattle) applyEffect(n, side, def.deathrattle, null, ev)
      died = true
      break
    }
    if (!died) return
    if (n.over) return
    checkOver(n, ev, 'hp')
    if (n.over) return
  }
}

function checkOver(n: GameState, ev: Ev[], reason: OverReason): void {
  if (n.over) return
  const dead0 = n.sides[0].hp <= 0
  const dead1 = n.sides[1].hp <= 0
  if (!dead0 && !dead1) return
  const winner: Side | -1 = dead0 && dead1 ? -1 : dead0 ? 1 : 0
  n.over = { winner, reason }
  ev.push({ e: 'over', winner, reason })
}

// ---------------------------------------------------------------- 回合

function beginTurn(n: GameState, ev: Ev[]): void {
  const s = n.sides[n.active]
  s.maxEnergy = Math.min(MAX_ENERGY, s.maxEnergy + 1)
  s.energy = Math.min(MAX_ENERGY, s.maxEnergy + s.coin)
  s.coin = 0
  for (const m of s.board) {
    m.sick = false
    m.attacks = 1
  }
  ev.push({ e: 'turn', side: n.active, turn: n.turn })
  drawOne(n, n.active, ev)
}

export function endTurn(s: GameState): ActionResult {
  if (s.over) return { ok: false, why: '对局已经结束' }
  const n = clone(s)
  const ev: Ev[] = []
  n.active = foe(n.active)
  n.turn += 1
  beginTurn(n, ev)
  return { ok: true, state: n, events: ev }
}

// ---------------------------------------------------------------- 目标与合法性

/** 出这张牌能选哪些目标;不需要选就是空数组(不是 null) */
export function playTargets(s: GameState, side: Side, hand: number): TargetRef[] {
  const ss = s.sides[side]
  const id = ss.hand[hand]
  if (!id) return []
  const req = targetKindOf(card(id))
  if (req === 'none') return []
  if (req === 'enemy') {
    const out: TargetRef[] = [heroTarget(foe(side))]
    for (const m of s.sides[foe(side)].board) if (m.health > 0) out.push(targetFor(foe(side), m.uid))
    return out
  }
  if (req === 'friendly') {
    const out: TargetRef[] = [heroTarget(side)]
    for (const m of ss.board) if (m.health > 0) out.push(targetFor(side, m.uid))
    return out
  }
  return ss.board.filter((m) => m.health > 0).map((m) => targetFor(side, m.uid))
}

/** 目标是不是符合这张牌的要求 */
function targetAllowed(s: GameState, side: Side, req: 'none' | 'enemy' | 'friendly' | 'friendlyMinion',
  target: TargetRef | null): boolean {
  if (req === 'none') return target === null
  if (!target) return false
  const want = req === 'enemy' ? foe(side) : side
  if (target.side !== want) return false
  if (req === 'friendlyMinion' && target.kind !== 'minion') return false
  if (target.kind === 'hero') return true
  const m = findMinion(s, target.side, target.uid)
  return !!m && m.health > 0
}

/** 这张牌现在能不能打出去(不选目标时调用;要选目标的还要再挑目标) */
export function canPlayCard(s: GameState, side: Side, hand: number): Check {
  if (s.over) return { ok: false, why: '对局已经结束' }
  if (s.active !== side) return { ok: false, why: '还没轮到你' }
  const ss = s.sides[side]
  if (!Number.isInteger(hand) || hand < 0 || hand >= ss.hand.length) return { ok: false, why: '手里没有这张牌' }
  const c = card(ss.hand[hand])
  if (ss.energy < c.cost) return { ok: false, why: '能量不够' }
  if (c.type === 'minion' && ss.board.length >= MAX_BOARD) return { ok: false, why: '场上最多 7 个随从' }
  if (targetKindOf(c) !== 'none' && playTargets(s, side, hand).length === 0) return { ok: false, why: '没有可以选的目标' }
  return { ok: true, why: '' }
}

/** 这个随从这回合能打谁(直接给界面画高亮 / AI 用);空数组表示不能攻击 */
export function attackTargets(s: GameState, side: Side, uid: number): TargetRef[] {
  if (s.over || s.active !== side) return []
  const m = findMinion(s, side, uid)
  if (!m || m.health <= 0 || m.attacks <= 0) return []
  const enemy = s.sides[foe(side)]
  const taunts = enemy.board.filter((x) => x.health > 0 && x.taunt)
  if (taunts.length > 0) return taunts.map((x) => targetFor(foe(side), x.uid))
  const out: TargetRef[] = [heroTarget(foe(side))]
  for (const x of enemy.board) if (x.health > 0) out.push(targetFor(foe(side), x.uid))
  return out
}

/** 这个随从能不能攻击;不能的话给一句原因(界面点它时提示) */
export function canAttackWith(s: GameState, side: Side, uid: number): Check {
  if (s.over) return { ok: false, why: '对局已经结束' }
  if (s.active !== side) return { ok: false, why: '还没轮到你' }
  const m = findMinion(s, side, uid)
  if (!m || m.health <= 0) return { ok: false, why: '没有这个随从' }
  if (m.attacks > 0) return { ok: true, why: '' }
  if (m.sick) return { ok: false, why: '刚上场的随从这回合不能攻击(冲锋除外)' }
  return { ok: false, why: '这个随从这回合已经攻击过了' }
}

// ---------------------------------------------------------------- 执行动作

function playCard(s: GameState, hand: number, target: TargetRef | null): ActionResult {
  const side = s.active
  const chk = canPlayCard(s, side, hand)
  if (!chk.ok) return { ok: false, why: chk.why }
  const n = clone(s)
  const ss = n.sides[side]
  const id = ss.hand[hand]
  const c = card(id)
  const req = targetKindOf(c)
  const aim = req === 'none' ? null : target
  if (!targetAllowed(n, side, req, aim)) return { ok: false, why: req === 'none' ? '这张牌不用选目标' : '要选一个合法的目标' }
  ss.energy -= c.cost
  ss.hand.splice(hand, 1)
  ss.played += 1
  const ev: Ev[] = [{ e: 'play', side, card: id, target: aim }]
  if (c.type === 'minion') {
    const m = addMinion(n, side, id, true, ev)
    if (m && c.battlecry) {
      if (c.battlecry.kind === 'buffSelf') {
        m.attack += c.battlecry.attack
        m.maxHealth += c.battlecry.health
        m.health += c.battlecry.health
        ev.push({ e: 'buff', target: targetFor(side, m.uid), attack: c.battlecry.attack, health: c.battlecry.health })
      } else {
        applyEffect(n, side, c.battlecry, aim, ev)
      }
    }
  } else if (c.spell) {
    applyEffect(n, side, c.spell, aim, ev)
  }
  resolveDeaths(n, ev)
  return { ok: true, state: n, events: ev }
}

function attackWith(s: GameState, uid: number, target: TargetRef): ActionResult {
  const side = s.active
  if (s.over) return { ok: false, why: '对局已经结束' }
  const m = findMinion(s, side, uid)
  if (!m || m.health <= 0) return { ok: false, why: '没有这个随从' }
  const chk = canAttackWith(s, side, uid)
  if (!chk.ok) return { ok: false, why: chk.why }
  const legal = attackTargets(s, side, uid)
  if (!legal.some((t) => sameTarget(t, target))) {
    const taunts = s.sides[foe(side)].board.some((x) => x.health > 0 && x.taunt)
    return { ok: false, why: taunts ? '对面有嘲讽随从,必须先打它' : '不能攻击这个目标' }
  }
  const n = clone(s)
  const me = findMinion(n, side, uid) as Minion
  me.attacks -= 1
  const ev: Ev[] = [{ e: 'attack', side, uid, target, toTarget: me.attack, toSelf: 0 }]
  if (target.kind === 'hero') {
    dealDamage(n, target, me.attack, side, ev)
    resolveDeaths(n, ev)
    return { ok: true, state: n, events: ev }
  }
  const defender = findMinion(n, foe(side), target.uid)
  if (!defender) return { ok: false, why: '没有这个随从' }
  const toSelf = defender.attack
  ev[0] = { e: 'attack', side, uid, target, toTarget: me.attack, toSelf }
  // 同时结算:先打目标,再由目标反击(顺序固定,圣盾/死亡结果可测)
  dealDamage(n, target, me.attack, side, ev)
  dealDamage(n, targetFor(side, uid), toSelf, foe(side), ev)
  resolveDeaths(n, ev)
  return { ok: true, state: n, events: ev }
}

/** 认输 */
export function surrender(s: GameState, side: Side): ActionResult {
  if (s.over) return { ok: false, why: '对局已经结束' }
  const n = clone(s)
  const ev: Ev[] = []
  n.over = { winner: foe(side), reason: 'quit' }
  ev.push({ e: 'over', winner: foe(side), reason: 'quit' })
  return { ok: true, state: n, events: ev }
}

/** 执行一个动作;不合法就返回原因(界面提示用,AI 只会从 legalActions 里挑) */
export function applyAction(s: GameState, a: Action): ActionResult {
  if (a.kind === 'end') return endTurn(s)
  if (s.over) return { ok: false, why: '对局已经结束' }
  if (a.kind === 'play') return playCard(s, a.hand, a.target)
  return attackWith(s, a.uid, a.target)
}

/** 当前行动方所有合法动作(出牌 × 每个目标、攻击 × 每个目标、结束回合)。AI 和单测用 */
export function legalActions(s: GameState): Action[] {
  const out: Action[] = []
  if (s.over) return out
  const side = s.active
  const ss = s.sides[side]
  for (let h = 0; h < ss.hand.length; h++) {
    if (!canPlayCard(s, side, h).ok) continue
    const targets = playTargets(s, side, h)
    if (targets.length === 0) out.push({ kind: 'play', hand: h, target: null })
    else for (const t of targets) out.push({ kind: 'play', hand: h, target: t })
  }
  for (const m of ss.board) {
    if (m.health <= 0 || m.attacks <= 0) continue
    for (const t of attackTargets(s, side, m.uid)) out.push({ kind: 'attack', uid: m.uid, target: t })
  }
  out.push({ kind: 'end' })
  return out
}

// ---------------------------------------------------------------- 存档

/** 对局状态本来就只有普通数据,原样交给 SaveSlot;坏档由 loadGame 兜住 */
export function saveGame(s: GameState): unknown {
  return s
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const isInt = (v: unknown): v is number => isNum(v) && Number.isInteger(v)
const isBool = (v: unknown): v is boolean => typeof v === 'boolean'
const isCardId = (v: unknown): v is string => {
  const c = cardOrNull(v)
  return !!c && !c.token
}

function loadSide(raw: unknown): SideState | null {
  const s = raw as SideState
  if (!s || typeof s !== 'object') return null
  if (!heroOrNull(s.hero)) return null
  if (!isInt(s.hp) || s.hp < 0 || s.hp > START_HP) return null
  if (!isInt(s.maxEnergy) || s.maxEnergy < 0 || s.maxEnergy > MAX_ENERGY) return null
  // 「幸运币」是 1.1 才加的字段:1.0 的存档没有它,补 0 继续用 —— 不能因为新字段把整局判成坏档
  const coin = s.coin === undefined ? 0 : s.coin
  if (!isInt(coin) || coin < 0 || coin > 1) return null
  // 后手「幸运币」那一回合能量会比上限多 1(存档正好存在这一刻也要能读回来)
  if (!isInt(s.energy) || s.energy < 0 || s.energy > s.maxEnergy + 1) return null
  if (!isInt(s.fatigue) || s.fatigue < 0) return null
  if (!isInt(s.played) || s.played < 0 || !isInt(s.dealt) || s.dealt < 0 || !isInt(s.lost) || s.lost < 0) return null
  if (!Array.isArray(s.deck) || s.deck.length > DECK_SIZE || !s.deck.every(isCardId)) return null
  if (!Array.isArray(s.hand) || s.hand.length > MAX_HAND || !s.hand.every(isCardId)) return null
  if (!Array.isArray(s.board) || s.board.length > MAX_BOARD) return null
  for (const m of s.board) {
    if (!m || typeof m !== 'object') return null
    if (!isInt(m.uid) || m.uid < 1) return null
    const def = cardOrNull(m.card)
    if (!def || def.type !== 'minion') return null
    if (!isNum(m.attack) || m.attack < 0) return null
    if (!isInt(m.health) || m.health < 1 || !isInt(m.maxHealth) || m.maxHealth < m.health) return null
    if (!isBool(m.taunt) || !isBool(m.shield) || !isBool(m.sick)) return null
    if (!isInt(m.attacks) || m.attacks < 0 || m.attacks > 1) return null
  }
  s.coin = coin
  return s
}

/** 读对局存档;坏的、版本不对的、结构对不上的返回 null(当作没有存档) */
export function loadGame(raw: unknown): GameState | null {
  const g = raw as GameState
  if (!g || typeof g !== 'object') return null
  if (g.v !== 1 || !isNum(g.seed) || !isInt(g.turn) || g.turn < 1) return null
  if (g.active !== 0 && g.active !== 1) return null
  if (!isInt(g.nextUid) || g.nextUid < 1) return null
  if (!Array.isArray(g.sides) || g.sides.length !== 2) return null
  try {
    const s0 = loadSide(g.sides[0])
    const s1 = loadSide(g.sides[1])
    if (!s0 || !s1) return null
    if (g.over !== null) {
      if (!g.over || typeof g.over !== 'object') return null
      if (g.over.winner !== 0 && g.over.winner !== 1 && g.over.winner !== -1) return null
      if (g.over.reason !== 'hp' && g.over.reason !== 'fatigue' && g.over.reason !== 'quit') return null
    }
    return g
  } catch (_) {
    return null
  }
}
