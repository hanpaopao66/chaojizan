// 成长:存档(带版本号和迁移)、奖励、升级、卡组、每日挑战、成就。全是纯函数,和界面无关。
//
// ## 金币不存余额,按账推出来
//
//   金币 = 各关第一次通关的奖励 + 每颗星的奖励 + 成就奖励 + 各台设备自己挣的(重复通关、每日挑战)
//        − 各张卡升到现在的等级一共花的
//
// 前三项从「星数表」「成就表」直接算;第四项每台设备只加自己那一格(earn[设备] 只增不减);
// 花掉的从「卡牌等级」算。这样两台设备的存档合并时(星取大、等级取大、各设备的格子取大、成就取并集),
// 金币既不会多算也不会丢 —— 不会出现「这台升了级、那台的旧余额又盖回来」白送金币的情况。
// 唯一的边角:两台设备离线时各自升级、各自把钱花光,合并后可能是负数(显示为负,再赢几局就回来)。
//
// ## 存档大小(云存储每个应用每个用户 1024 个键、5 MB;单个值 ≤ 64 KB)
//
// 只用两个键:best(这份档案,约 1–2 KB)和 state(打到一半的那一局,约 2–30 KB)。
// 每日挑战只留最近 30 天,成就 19 个,设备格子一般一两个 —— 怎么玩都到不了 64 KB。
import { rand } from '../../shared/src/rand'
import {
  ACHIEVEMENTS, AI_NORMAL, AchDef, AchMetric, CARDS, CHAPTERS, COLLECTION, DAILY_COINS, DAILY_LEVEL, Goal, LEVELS,
  LEVEL_BY_ID, LevelDef, MAX_LEVEL, STARTERS, Theme, UPGRADE_COST, replayCoins, spentOn, starCoins,
} from './data'
import type { BattleConfig } from './field'

export const PROFILE_V = 1
export const DECKS = 3
export const DECK_SIZE = 8
const DAILY_KEEP = 30
const SEEN_KEEP = 24

export interface Profile {
  v: number
  /** 关卡 id → 最好的星数(1–3);没过的关没有这个键 */
  stars: Record<string, number>
  /** 卡 id → 等级(1 级的不写) */
  levels: Record<string, number>
  /** 设备 id → 这台设备累计挣的金币(重复通关、每日挑战) */
  earn: Record<string, number>
  /** 3 套卡组,每套 8 个卡 id */
  decks: string[][]
  /** 出战的是第几套 */
  deck: number
  /** 卡组最后一次改动的时间(毫秒):两台设备合并时新的赢 */
  deckAt: number
  /** 每日挑战:日期(北京时间 YYYY-MM-DD)→ 最好的星数,只留最近 30 天 */
  daily: Record<string, number>
  /** 达成过的成就 */
  ach: string[]
  /** 累计数据:games、wins、towers、dailyWins、bestKills、bestRefund、allLanes、flawless */
  stats: Record<string, number>
  /** 看过的提示(新手引导) */
  seen: string[]
}

export function newProfile(): Profile {
  return {
    v: PROFILE_V, stars: {}, levels: {}, earn: {}, decks: [STARTERS.slice(), STARTERS.slice(), STARTERS.slice()],
    deck: 0, deckAt: 0, daily: {}, ach: [], stats: {}, seen: [],
  }
}

/** 存档是更新的版本写的(这台设备上的代码旧了):只读,不合并、不回写 */
export const isFuture = (p: Profile): boolean => p.v > PROFILE_V

// ---------------------------------------------------------------- 读档、迁移、合并

type Migration = (raw: Record<string, unknown>) => Record<string, unknown>

/**
 * 迁移表:MIGRATIONS[n] 把第 n 版升到第 n+1 版。现在只有第 1 版,表是空的;
 * 以后改了存档结构(字段改名、换含义)就在这里加一步,并把 PROFILE_V 加一。
 * 只是**新增**字段不用升版本:读档时缺的字段按默认值补上(sanitize)。
 */
export const MIGRATIONS: Record<number, Migration> = {}

export function migrate(raw: Record<string, unknown>, steps: Record<number, Migration> = MIGRATIONS,
  target = PROFILE_V): Record<string, unknown> | null {
  let cur = raw
  let v = Number(cur.v) || 0
  while (v < target) {
    const step = steps[v]
    if (!step) return null
    cur = { ...step(cur), v: v + 1 }
    v++
  }
  return cur
}

const obj = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {})
const int = (v: unknown, lo: number, hi: number): number | null => {
  const n = Math.floor(Number(v))
  return Number.isFinite(n) && n >= lo && n <= hi ? n : null
}

/** 读档:坏的返回 null(当作没有存档);旧版本先迁移;更新版本的原样返回(isFuture 为真,只读) */
export function loadProfile(raw: unknown): Profile | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const r = raw as Record<string, unknown>
  const v = Number(r.v)
  if (!Number.isInteger(v) || v < 1) return null
  if (v > PROFILE_V) return { ...newProfile(), ...(r as object), v } as Profile
  const m = migrate(r)
  return m ? sanitize(m) : null
}

/** 把一份(迁移过的)存档洗干净:不认识的卡、越界的数一律丢掉,缺的补默认值 */
export function sanitize(r: Record<string, unknown>): Profile {
  const p = newProfile()
  for (const [id, s] of Object.entries(obj(r.stars))) {
    const n = int(s, 1, 3)
    if (LEVEL_BY_ID[id] && n) p.stars[id] = n
  }
  for (const [id, l] of Object.entries(obj(r.levels))) {
    const n = int(l, 2, MAX_LEVEL)
    if (CARDS[id] && !CARDS[id].aiOnly && n) p.levels[id] = n
  }
  for (const [d, c] of Object.entries(obj(r.earn))) {
    const n = int(c, 1, 1e9)
    if (/^[a-z0-9_]{1,16}$/.test(d) && n) p.earn[d] = n
  }
  if (Array.isArray(r.decks)) {
    for (let i = 0; i < DECKS; i++) {
      const d = r.decks[i]
      if (Array.isArray(d) && validDeck(d as string[])) p.decks[i] = (d as string[]).slice()
    }
  }
  p.deck = int(r.deck, 0, DECKS - 1) ?? 0
  p.deckAt = int(r.deckAt, 0, 1e15) ?? 0
  for (const [d, s] of Object.entries(obj(r.daily))) {
    const n = int(s, 0, 3)
    if (/^\d{4}-\d{2}-\d{2}$/.test(d) && n !== null) p.daily[d] = n
  }
  if (Array.isArray(r.ach)) p.ach = r.ach.filter((a): a is string => typeof a === 'string' && ACHIEVEMENTS.some((x) => x.id === a))
  for (const [k, s] of Object.entries(obj(r.stats))) {
    const n = int(s, 0, 1e9)
    if (/^[a-zA-Z]{1,20}$/.test(k) && n !== null) p.stats[k] = n
  }
  if (Array.isArray(r.seen)) p.seen = r.seen.filter((s): s is string => typeof s === 'string' && s.length <= 24).slice(0, SEEN_KEEP)
  return canon(p)
}

/** 键排好序、数组去重排序:同样的内容永远是同样的 JSON(存档层按 JSON 比较有没有变) */
export function canon(p: Profile): Profile {
  const sortObj = <T>(o: Record<string, T>): Record<string, T> => {
    const out: Record<string, T> = {}
    for (const k of Object.keys(o).sort()) out[k] = o[k]
    return out
  }
  const daily = sortObj(p.daily)
  const days = Object.keys(daily)
  for (const d of days.slice(0, Math.max(0, days.length - DAILY_KEEP))) delete daily[d]
  return {
    v: p.v, stars: sortObj(p.stars), levels: sortObj(p.levels), earn: sortObj(p.earn),
    decks: p.decks.map((d) => d.slice()), deck: p.deck, deckAt: p.deckAt, daily,
    ach: Array.from(new Set(p.ach)).sort(), stats: sortObj(p.stats), seen: Array.from(new Set(p.seen)).sort().slice(0, SEEN_KEEP),
  }
}

/** 两台设备的存档合成一份:星、等级、设备格子、统计取大,成就和提示取并集,卡组谁新用谁 */
export function mergeProfile(a: Profile, b: Profile): Profile {
  if (isFuture(a) || isFuture(b)) return a.v >= b.v ? a : b
  const maxObj = (x: Record<string, number>, y: Record<string, number>): Record<string, number> => {
    const out = { ...x }
    for (const [k, v] of Object.entries(y)) out[k] = Math.max(out[k] ?? v, v)
    return out
  }
  const newer = b.deckAt > a.deckAt ? b : a
  const daily = maxObj(a.daily, b.daily)
  return canon({
    v: PROFILE_V, stars: maxObj(a.stars, b.stars), levels: maxObj(a.levels, b.levels), earn: maxObj(a.earn, b.earn),
    decks: newer.decks, deck: newer.deck, deckAt: newer.deckAt, daily,
    ach: a.ach.concat(b.ach), stats: maxObj(a.stats, b.stats), seen: a.seen.concat(b.seen),
  })
}

// ---------------------------------------------------------------- 查询

export const totalStars = (p: Profile): number => Object.values(p.stars).reduce((s, n) => s + n, 0)
export const cardLevel = (p: Profile, id: string): number => p.levels[id] || 1

/** 能用的卡:开局的 8 张 + 通关解锁的 */
export function unlocked(p: Profile): string[] {
  const got = new Set(STARTERS)
  for (const L of LEVELS) if (L.unlock && (p.stars[L.id] || 0) > 0) got.add(L.unlock)
  return COLLECTION.filter((id) => got.has(id))
}

/** 这张卡在哪一关解锁(开局就有的返回 null) */
export function unlockedBy(id: string): LevelDef | null {
  return LEVELS.find((L) => L.unlock === id) || null
}

/** 关卡开没开:第一关一直开着,之后的要前一关过了 */
export function levelOpen(p: Profile, id: string): boolean {
  const i = LEVELS.findIndex((L) => L.id === id)
  if (i < 0) return false
  return i === 0 || (p.stars[LEVELS[i - 1].id] || 0) > 0
}

/** 下一关要打的(全过了就是最后一关) */
export function nextLevel(p: Profile): LevelDef {
  return LEVELS.find((L) => !(p.stars[L.id] > 0)) || LEVELS[LEVELS.length - 1]
}

export function chaptersCleared(p: Profile): number {
  return CHAPTERS.filter((c) => (p.stars[`${c.n}-5`] || 0) > 0).length
}

export function coins(p: Profile): number {
  let c = 0
  for (const [id, s] of Object.entries(p.stars)) {
    const L = LEVEL_BY_ID[id]
    if (!L || s <= 0) continue
    c += L.coins + s * starCoins(L.chapter)
  }
  for (const a of p.ach) c += ACHIEVEMENTS.find((x) => x.id === a)?.coins || 0
  for (const e of Object.values(p.earn)) c += e
  for (const [id, l] of Object.entries(p.levels)) if (CARDS[id]) c -= spentOn(l)
  return c
}

export function upgradeCost(p: Profile, id: string): number | null {
  const l = cardLevel(p, id)
  return l >= MAX_LEVEL ? null : UPGRADE_COST[l]
}

export function canUpgrade(p: Profile, id: string): boolean {
  const cost = upgradeCost(p, id)
  return !isFuture(p) && cost !== null && unlocked(p).indexOf(id) >= 0 && coins(p) >= cost
}

export function upgrade(p: Profile, id: string): Profile {
  if (!canUpgrade(p, id)) return p
  return canon({ ...p, levels: { ...p.levels, [id]: cardLevel(p, id) + 1 } })
}

export function validDeck(d: string[]): boolean {
  if (d.length !== DECK_SIZE || new Set(d).size !== DECK_SIZE) return false
  return d.every((id) => !!CARDS[id] && !CARDS[id].aiOnly)
}

/** 出战的卡组(万一出战那套里有还没解锁的卡 —— 比如合并过来的 —— 退回开局那套) */
export function activeDeck(p: Profile): string[] {
  const d = p.decks[p.deck] || STARTERS
  const have = new Set(unlocked(p))
  return validDeck(d) && d.every((id) => have.has(id)) ? d.slice() : STARTERS.slice()
}

export function setDeck(p: Profile, i: number, cards: string[], now: number): Profile {
  if (i < 0 || i >= DECKS || !validDeck(cards)) return p
  const have = new Set(unlocked(p))
  if (!cards.every((id) => have.has(id))) return p
  const decks = p.decks.map((d, k) => (k === i ? cards.slice() : d.slice()))
  return canon({ ...p, decks, deckAt: now })
}

export function useDeck(p: Profile, i: number, now: number): Profile {
  if (i < 0 || i >= DECKS || i === p.deck) return p
  return canon({ ...p, deck: i, deckAt: now })
}

export function markSeen(p: Profile, key: string): Profile {
  return p.seen.indexOf(key) >= 0 ? p : canon({ ...p, seen: p.seen.concat(key) })
}

// ---------------------------------------------------------------- 开一局

function levelsOf(cards: string[], level: number | ((id: string) => number)): Record<string, number> {
  const out: Record<string, number> = {}
  for (const id of cards) out[id] = typeof level === 'number' ? level : level(id)
  return out
}

/** 塔的等级:出战卡组的平均等级(向下取整) */
export function towerLevelOf(p: Profile, deck: string[]): number {
  const sum = deck.reduce((s, id) => s + cardLevel(p, id), 0)
  return Math.max(1, Math.floor(sum / deck.length))
}

export function levelConfig(p: Profile, L: LevelDef, seed: number): BattleConfig {
  const deck = activeDeck(p)
  return {
    seed, duration: L.duration, objective: L.objective, target: L.target || 0,
    decks: [{ cards: deck, levels: levelsOf(deck, (id) => cardLevel(p, id)) },
      { cards: L.enemy.slice(), levels: levelsOf(L.enemy, L.enemyLevel) }],
    ai: [null, L.ai], regen: L.regen || [1, 1], startEnergy: L.startEnergy || [5, 5], towerHp: L.towerHp || [1, 1],
    towerLevel: [towerLevelOf(p, deck), L.enemyLevel], closed: L.closed || [], speed: L.speed || 1,
    stars: L.stars, tag: L.id, theme: CHAPTERS[L.chapter - 1].theme,
  }
}

// ---------------------------------------------------------------- 每日挑战

/** 北京时间的日期 YYYY-MM-DD(每日挑战按它换关,人人同一关) */
export function todayKey(now: number): string {
  return new Date(now + 8 * 3600 * 1000).toISOString().slice(0, 10)
}

/** FNV-1a:日期字符串 → 32 位种子 */
export function hash(s: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

export interface DailyDef {
  date: string
  name: string
  /** 今天的规则 */
  rule: string
  cfg: BattleConfig
}

const TANKS = ['bear', 'hippo', 'gorilla', 'crocodile', 'cow', 'elephant', 'rhino']
const RANGED = ['duck', 'monkey', 'parrot', 'giraffe', 'lookout']
const SPELLS = ['fire', 'freeze', 'heal', 'rage']
const LIGHT = ['chick', 'rabbit', 'penguin', 'pig', 'frog', 'snake', 'fence', 'coop', 'owl']
const THEMES: Theme[] = ['meadow', 'swamp', 'snow', 'jungle', 'highland']

function pick<T>(list: readonly T[], seed: number): [T, number] {
  const [r, s] = rand(seed)
  return [list[Math.floor(r * list.length)], s]
}

/** 按「一坦克、两远程、一法术、两轻兵、两随便」凑 8 张不重复的;至少有一张能打天上的 */
function rollDeck(seed: number, pool: string[]): [string[], number] {
  let s = seed
  const out: string[] = []
  const take = (from: string[]) => {
    const left = from.filter((id) => out.indexOf(id) < 0 && pool.indexOf(id) >= 0)
    if (!left.length) return
    let id: string
    ;[id, s] = pick(left, s)
    out.push(id)
  }
  take(TANKS)
  take(RANGED)
  take(RANGED)
  take(SPELLS)
  take(LIGHT)
  take(LIGHT)
  while (out.length < DECK_SIZE) take(pool)
  return [out, s]
}

interface Twist { name: string; rule: string; apply: (c: BattleConfig, seed: number) => number }

const TWISTS: Twist[] = [
  { name: '标准对局', rule: '没有特殊规则,推倒大本营就赢。', apply: (_c, s) => s },
  { name: '能量充沛', rule: '两边能量都回得快一半。', apply: (c, s) => { c.regen = [1.5, 1.5]; return s } },
  { name: '单路塌方', rule: '有一路塌了,只剩两路能走。', apply: (c, s) => {
    let lane: number
    ;[lane, s] = pick([0, 2], s)
    c.closed = [lane]
    return s
  } },
  { name: '疾风', rule: '所有单位走得快两成五。', apply: (c, s) => { c.speed = 1.25; return s } },
  { name: '坚城', rule: '两边的塔血都多一半,时间也长一些。', apply: (c, s) => { c.towerHp = [1.5, 1.5]; c.duration = 180; return s } },
  { name: '满能开局', rule: '两边开局能量都是满的。', apply: (c, s) => { c.startEnergy = [10, 10]; return s } },
  { name: '坚守', rule: '守满 120 秒、大本营还在就赢。对面能量回得快四成。', apply: (c, s) => {
    c.objective = 'defend'; c.duration = 120; c.regen = [1, 1.4]; c.startEnergy = [7, 5]; c.stars = [W, lost1, lost0]; return s
  } },
  { name: '速攻', rule: '120 秒内推倒一座塔才算赢。', apply: (c, s) => {
    c.objective = 'blitz'; c.target = 1; c.duration = 120; c.stars = [W, { kind: 'time', n: 80 }, lost0]; return s
  } },
]
const W: Goal = { kind: 'win' }
const lost1: Goal = { kind: 'lost', n: 1 }
const lost0: Goal = { kind: 'lost', n: 0 }

export function dailyChallenge(date: string): DailyDef {
  let s = hash(`critters:${date}`)
  let twist: Twist
  ;[twist, s] = pick(TWISTS, s)
  let theme: Theme
  ;[theme, s] = pick(THEMES, s)
  let mine: string[]
  ;[mine, s] = rollDeck(s, COLLECTION)
  // 电脑的牌还能有章节特色兵(不含 Boss)
  const aiPool = Object.values(CARDS).filter((c) => !c.boss).map((c) => c.id)
  let theirs: string[]
  ;[theirs, s] = rollDeck(s, aiPool)
  const cfg: BattleConfig = {
    seed: s, duration: 150, objective: 'siege', target: 0,
    decks: [{ cards: mine, levels: levelsOf(mine, DAILY_LEVEL) }, { cards: theirs, levels: levelsOf(theirs, DAILY_LEVEL) }],
    ai: [null, { ...AI_NORMAL, skill: 0.65 }], regen: [1, 1], startEnergy: [5, 5], towerHp: [1, 1],
    towerLevel: [DAILY_LEVEL, DAILY_LEVEL], closed: [], speed: 1, stars: [W, lost1, lost0], tag: `daily:${date}`, theme,
  }
  s = twist.apply(cfg, s)
  cfg.seed = s
  const [, m, d] = date.split('-').map(Number)
  return { date, name: `${m} 月 ${d} 日 · ${twist.name}`, rule: twist.rule, cfg }
}

export function dailyDone(p: Profile, date: string): number {
  return p.daily[date] || 0
}

// ---------------------------------------------------------------- 一局打完

export interface BattleResult {
  /** '1-3' 或 'daily:2026-09-15' */
  tag: string
  won: boolean
  stars: number
  kills: number
  refund: number
  /** 推倒对面几座哨塔 */
  towers: number
  base: boolean
  /** 自己丢了几座哨塔 */
  lost: number
  /** 对面三路的哨塔全推倒了(只在三路都开着时算) */
  allLanes: boolean
}

export interface Reward {
  /** 这一局一共多了多少金币(第一次通关、新的星、重复通关、每日挑战、新成就) */
  coins: number
  /** 这一关比以前多拿了几颗星 */
  newStars: number
  firstClear: boolean
  /** 新解锁的卡 */
  cards: string[]
  /** 新达成的成就 */
  achievements: string[]
}

export function applyResult(p: Profile, r: BattleResult, device: string): { profile: Profile; reward: Reward } {
  const reward: Reward = { coins: 0, newStars: 0, firstClear: false, cards: [], achievements: [] }
  if (isFuture(p)) return { profile: p, reward }
  const before = coins(p)
  const cardsBefore = new Set(unlocked(p))
  const n: Profile = {
    ...p, stars: { ...p.stars }, earn: { ...p.earn }, daily: { ...p.daily }, stats: { ...p.stats }, ach: p.ach.slice(),
  }
  const st = n.stats
  const bump = (k: string, by = 1) => { st[k] = (st[k] || 0) + by }
  const best = (k: string, v: number) => { st[k] = Math.max(st[k] || 0, Math.floor(v)) }
  bump('games')
  bump('towers', r.towers + (r.base ? 1 : 0))
  best('bestKills', r.kills)
  best('bestRefund', r.refund)
  if (r.allLanes) bump('allLanes')
  const dev = /^[a-z0-9_]{1,16}$/.test(device) ? device : 'x'
  if (r.won) {
    bump('wins')
    if (r.lost === 0) bump('flawless')
    if (r.tag.startsWith('daily:')) {
      const date = r.tag.slice(6)
      if (!(n.daily[date] > 0)) {
        n.earn[dev] = (n.earn[dev] || 0) + DAILY_COINS
        bump('dailyWins')
      }
      n.daily[date] = Math.max(n.daily[date] || 0, r.stars)
    } else {
      const L = LEVEL_BY_ID[r.tag]
      if (L) {
        const prev = n.stars[L.id] || 0
        reward.firstClear = prev === 0
        reward.newStars = Math.max(0, r.stars - prev)
        n.stars[L.id] = Math.max(prev, r.stars)
        if (!reward.firstClear) n.earn[dev] = (n.earn[dev] || 0) + replayCoins(L.chapter, r.stars)
      }
    }
  } else if (r.tag.startsWith('daily:')) {
    const date = r.tag.slice(6)
    n.daily[date] = n.daily[date] || 0
  }
  let out = canon(n)
  for (const a of ACHIEVEMENTS) {
    if (out.ach.indexOf(a.id) < 0 && achProgress(out, a) >= a.n) reward.achievements.push(a.id)
  }
  if (reward.achievements.length) out = canon({ ...out, ach: out.ach.concat(reward.achievements) })
  reward.cards = unlocked(out).filter((id) => !cardsBefore.has(id))
  reward.coins = coins(out) - before
  return { profile: out, reward }
}

// ---------------------------------------------------------------- 成就

export function metric(p: Profile, m: AchMetric): number {
  const s = p.stats
  switch (m) {
    case 'wins': return s.wins || 0
    case 'towers': return s.towers || 0
    case 'dailyWins': return s.dailyWins || 0
    case 'bossWins': return LEVELS.filter((L) => L.boss && (p.stars[L.id] || 0) > 0).length
    case 'stars': return totalStars(p)
    case 'threeStars': return Object.values(p.stars).filter((n) => n >= 3).length
    case 'cards': return unlocked(p).length
    case 'maxLevel': return Math.max(1, ...Object.values(p.levels))
    case 'chapters': return chaptersCleared(p)
    case 'bestKills': return s.bestKills || 0
    case 'bestRefund': return s.bestRefund || 0
    case 'allLanes': return s.allLanes || 0
    case 'flawless': return s.flawless || 0
  }
  return 0
}

export function achProgress(p: Profile, a: AchDef): number {
  return metric(p, a.metric)
}

/** 升级之后可能达成的成就(「把一张卡升到 5 级」):升级时顺手记上 */
export function claimAchievements(p: Profile): { profile: Profile; got: string[] } {
  if (isFuture(p)) return { profile: p, got: [] }
  const got = ACHIEVEMENTS.filter((a) => p.ach.indexOf(a.id) < 0 && achProgress(p, a) >= a.n).map((a) => a.id)
  return { profile: got.length ? canon({ ...p, ach: p.ach.concat(got) }) : p, got }
}
