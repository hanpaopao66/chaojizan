// 菜单界面:主菜单、闯关、关卡说明、卡牌与卡组、成就、每日挑战、结算、关于。全部是 DOM(字清楚、读屏读得到),
// 用户看得到的字一律 textContent,不拼 HTML。规则都在 progress.ts / data.ts,这里只管摆出来和转发操作。
import { artSpan, icon } from './assets'
import { play as sfx, setSound, soundOn } from './audio'
import { starsOf } from './battle'
import {
  ACHIEVEMENTS, CARDS, CHAPTERS, CardDef, COLLECTION, DAILY_COINS, DAILY_LEVEL, Goal, LEVELS, LEVEL_BY_ID, LevelDef,
  MAX_LEVEL, card, replayCoins, starCoins, statMul,
} from './data'
import { Battle } from './field'
import {
  DECKS, Profile, Reward, achProgress, activeDeck, canUpgrade, cardLevel, coins, dailyChallenge, dailyDone,
  levelOpen, nextLevel, totalStars, unlocked, unlockedBy, upgradeCost,
} from './progress'
import { Overlay, bullets, button, el, row } from '../../shared/src/ui'

export type Screen = 'home' | 'campaign' | 'cards' | 'ach' | 'daily'

export interface App {
  profile(): Profile
  /** 改了档案:存档 + 刷新当前界面 */
  commit(p: Profile): void
  go(s: Screen, arg?: number): void
  startLevel(id: string): void
  startDaily(): void
  upgradeCard(id: string): void
  setDeck(i: number, cards: string[]): void
  useDeck(i: number): void
  readonly overlay: Overlay
  now(): number
  toast(text: string): void
  /** 存档是更新版本写的,只能看不能改 */
  readonly frozen: boolean
}

const TOTAL_STARS = LEVELS.length * 3
const num = (n: number) => n.toLocaleString('zh-CN')

function iconBtn(name: string, label: string, onClick: () => void, cls = 'icon-btn'): HTMLButtonElement {
  const b = button('', onClick, cls)
  b.append(icon(name))
  b.setAttribute('aria-label', label)
  b.title = label
  return b
}

function pill(iconName: string, text: string, cls: string): HTMLElement {
  const p = el('div', '', `pill ${cls}`)
  p.append(icon(iconName), el('b', text))
  return p
}

function stars(n: number, of = 3, cls = 'stars'): HTMLElement {
  const s = el('span', '', cls)
  s.setAttribute('role', 'img')
  s.setAttribute('aria-label', `${n} 颗星`)
  for (let i = 0; i < of; i++) s.append(icon('star', i < n ? 'on' : 'off'))
  return s
}

function header(app: App, title: string, extra?: HTMLElement): HTMLElement {
  const h = el('header', '', 'bar')
  h.append(iconBtn('back', '返回', () => app.go('home')), el('h2', title))
  if (extra) h.append(extra)
  return h
}

export function goalText(g: Goal): string {
  switch (g.kind) {
    case 'win': return '赢下这一局'
    case 'lost': return g.n === 0 ? '一座哨塔都不丢' : `丢的哨塔不超过 ${g.n} 座`
    case 'time': return `${g.n} 秒内赢`
    case 'kills': return `击倒至少 ${g.n} 个敌方单位`
  }
  return ''
}

/** 一张卡(DOM):卡面、费用、等级、名字 */
export function cardEl(c: CardDef, opts: { level?: number; locked?: boolean; size?: number; cls?: string } = {}): HTMLElement {
  const e = el('div', '', `card ${c.kind} ${opts.cls || ''}`.trim())
  e.dataset.id = c.id
  e.append(el('span', '', 'glow'))
  const art = artSpan(c.art, opts.size || 50)
  e.append(art, el('span', String(c.cost), 'cost'))
  if (opts.level) e.append(el('span', `${opts.level}级`, 'lv'))
  e.append(el('span', c.name, 'nm'))
  if (opts.locked) {
    e.classList.add('locked')
    e.append(icon('lock', 'lockic'))
  }
  return e
}

// ---------------------------------------------------------------- 主菜单

export function home(app: App, root: HTMLElement): void {
  const p = app.profile()
  const s = el('div', '', 'scr home')
  const top = el('header', '', 'topbar')
  top.append(pill('coin', num(coins(p)), 'coin'), pill('star', `${totalStars(p)}/${TOTAL_STARS}`, 'star'), el('span', '', 'spacer'))
  const snd = iconBtn(soundOn() ? 'sound-on' : 'sound-off', soundOn() ? '关掉声音' : '打开声音', () => {
    setSound(!soundOn())
    app.go('home')
    if (soundOn()) sfx('tap')
  })
  top.append(snd, iconBtn('info', '关于', () => about(app)))
  s.append(top)

  const hero = el('div', '', 'hero')
  // 天上:亮色是几朵慢慢飘的云,暗色是星星和月亮(都是 CSS 画的)
  const sky = el('div', '', 'sky')
  sky.setAttribute('aria-hidden', 'true')
  for (let i = 1; i <= 3; i++) sky.append(el('span', '', `cloud c${i}`))
  hero.append(sky)
  const logo = el('h1', '', 'logo')
  logo.append(el('span', '萌兽'), el('span', '三路'))
  hero.append(logo, el('p', '三条路 · 八张牌 · 和电脑切磋', 'tagline'))
  hero.append(el('div', '', 'hills'))
  const parade = el('div', '', 'parade')
  ;['rabbit', 'pig', 'bear', 'monkey', 'penguin'].forEach((a, i) => {
    const w = artSpan(a, i === 2 ? 74 : i === 1 || i === 3 ? 60 : 52, 'art bob')
    w.style.animationDelay = `${i * 0.13}s`
    parade.append(w)
  })
  hero.append(parade)
  s.append(hero)

  const menu = el('div', '', 'menu')
  const nx = nextLevel(p)
  const allDone = LEVELS.every((L) => (p.stars[L.id] || 0) > 0)
  const cleared = LEVELS.filter((L) => (p.stars[L.id] || 0) > 0).length
  const jr = el('div', '', 'journey')
  const bar = el('div', '', 'prog')
  const fill = el('i')
  fill.style.transform = `scaleX(${cleared / LEVELS.length})`
  bar.append(fill)
  jr.append(el('span', '闯关进度'), bar, el('b', `${cleared}/${LEVELS.length} 关`))
  menu.append(jr)
  const go = button('', () => app.go('campaign', nx.chapter), 'cta primary')
  go.append(el('b', '闯关'), el('small', allDone ? `全部通关 · ${totalStars(p)} 颗星` : `第 ${nx.chapter} 章 · ${nx.id} ${nx.name}`))
  menu.append(go)
  const grid = el('div', '', 'tiles')
  const today = dailyChallenge(dayKey(app.now()))
  const done = dailyDone(p, today.date)
  const t1 = button('', () => app.go('daily'), 'tile')
  t1.append(icon('calendar'), el('b', '每日挑战'), el('small', done ? `今天 ${done} 星` : '今天还没赢'))
  const got = unlocked(p).length
  const t2 = button('', () => app.go('cards'), 'tile')
  t2.append(icon('cards'), el('b', '卡牌'), el('small', `${got}/${COLLECTION.length} 张`))
  if (COLLECTION.some((id) => canUpgrade(p, id))) t2.append(el('i', '', 'dot'))
  const t3 = button('', () => app.go('ach'), 'tile')
  t3.append(icon('trophy'), el('b', '成就'), el('small', `${p.ach.length}/${ACHIEVEMENTS.length}`))
  grid.append(t1, t2, t3)
  menu.append(grid)
  s.append(menu)
  s.append(el('p', '没有广告 · 没有内购 · 没有排行榜', 'fine'))
  root.append(s)
}

export function dayKey(now: number): string {
  return new Date(now + 8 * 3600 * 1000).toISOString().slice(0, 10)
}

// ---------------------------------------------------------------- 闯关

export function campaign(app: App, root: HTMLElement, chapter: number): void {
  const p = app.profile()
  const s = el('div', '', 'scr camp')
  s.append(header(app, '闯关', pill('star', `${totalStars(p)}/${TOTAL_STARS}`, 'star')))
  const tabs = el('div', '', 'chapters')
  tabs.setAttribute('role', 'tablist')
  CHAPTERS.forEach((c) => {
    const open = levelOpen(p, `${c.n}-1`)
    const b = button('', () => { if (open) app.go('campaign', c.n) }, `chip theme-${c.theme}`)
    b.setAttribute('role', 'tab')
    b.setAttribute('aria-selected', String(c.n === chapter))
    b.disabled = !open
    b.append(el('b', `${c.n}`), el('span', c.name))
    if (!open) b.append(icon('lock'))
    tabs.append(b)
  })
  s.append(tabs)
  const ch = CHAPTERS[chapter - 1]
  const card0 = el('div', '', `chapter theme-${ch.theme}`)
  const got = LEVELS.filter((L) => L.chapter === chapter).reduce((n, L) => n + (p.stars[L.id] || 0), 0)
  const bossArt = artSpan(CARDS[ch.boss].art, 76, 'art boss')
  const txt = el('div', '', 'ch-text')
  txt.append(el('h3', `第${'一二三四五'[chapter - 1]}章 · ${ch.name}`), el('p', ch.blurb))
  const st = el('p', '', 'ch-stars')
  st.append(icon('star', 'on'), el('span', `${got}/15`))
  txt.append(st)
  card0.append(txt, bossArt)
  s.append(card0)
  const path = el('ol', '', 'path')
  LEVELS.filter((L) => L.chapter === chapter).forEach((L, i) => {
    const li = el('li', '', i % 2 ? 'r' : 'l')
    const open = levelOpen(p, L.id)
    const got2 = p.stars[L.id] || 0
    const b = button('', () => levelSheet(app, L), `node ${got2 ? 'done' : open ? 'open' : 'locked'}${L.boss ? ' boss' : ''}`)
    b.disabled = !open
    const badge = el('span', '', 'badge')
    if (L.boss) badge.append(artSpan(CARDS[CHAPTERS[L.chapter - 1].boss].art, 40))
    else badge.append(el('b', String(L.index)))
    b.append(badge)
    const info = el('span', '', 'info')
    info.append(el('b', `${L.id} ${L.name}`))
    const tags: string[] = []
    if (L.boss) tags.push('Boss')
    if (L.objective === 'defend') tags.push('坚守')
    if (L.objective === 'blitz') tags.push('速攻')
    if (L.closed?.length) tags.push(L.closed.length === 2 ? '单路' : '两路')
    if (L.unlock && !got2) tags.push(`解锁 ${card(L.unlock).name}`)
    info.append(el('small', tags.join(' · ') || ' '))
    b.append(info)
    if (open) b.append(stars(got2))
    else b.append(icon('lock', 'lockic'))
    b.setAttribute('aria-label', `${L.id} ${L.name},${open ? `${got2} 颗星` : '还没开'}`)
    li.append(b)
    path.append(li)
  })
  s.append(path)
  root.append(s)
  const cur = path.querySelector('.node.open') as HTMLElement | null
  cur?.scrollIntoView?.({ block: 'center' })
}

function rulesOf(L: LevelDef): string[] {
  const out: string[] = []
  if (L.objective === 'defend') out.push(`坚守:守满 ${L.duration} 秒、大本营还在就赢`)
  else if (L.objective === 'blitz') out.push(`速攻:${L.duration} 秒内推倒 ${L.target} 座塔(大本营算三座)`)
  else out.push(`推倒对面的大本营就赢;${Math.floor(L.duration / 60)} 分 ${L.duration % 60 ? `${L.duration % 60} 秒` : ''}到了比推倒的哨塔数`)
  if (L.closed?.length) out.push(`封路:${L.closed.map((l) => ['左', '中', '右'][l]).join('、')}路走不通`)
  if (L.regen && (L.regen[0] !== 1 || L.regen[1] !== 1)) {
    const [a, b] = L.regen
    out.push(a === b ? `两边能量回复 ×${a}` : `对面能量回复 ×${b}`)
  }
  if (L.startEnergy) out.push(`开局能量:你 ${L.startEnergy[0]} 点,对面 ${L.startEnergy[1]} 点`)
  if (L.speed && L.speed !== 1) out.push(`所有单位移动 ×${L.speed}`)
  if (L.towerHp && L.towerHp[1] !== 1) out.push(`对面的塔血 ×${L.towerHp[1]}`)
  out.push(`对面的卡牌和塔是 ${L.enemyLevel} 级`)
  return out
}

function foesEl(ids: string[]): HTMLElement {
  const f = el('div', '', 'foes')
  for (const id of Array.from(new Set(ids))) {
    const c = card(id)
    const w = el('span', '', `foe ${c.boss ? 'boss' : ''}`)
    w.append(artSpan(c.art, c.boss ? 40 : 32))
    w.title = c.name
    w.setAttribute('aria-label', c.name)
    f.append(w)
  }
  return f
}

export function levelSheet(app: App, L: LevelDef): void {
  const p = app.profile()
  const got = p.stars[L.id] || 0
  app.overlay.show((panel) => {
    panel.append(el('h2', `${L.id} ${L.name}`), el('p', L.intro, 'intro'))
    panel.append(bullets(rulesOf(L)))
    panel.append(el('h3', '星级'))
    const goals = el('ul', '', 'goals')
    L.stars.forEach((g, i) => {
      const li = el('li', '', i < got ? 'got' : '')
      li.append(icon('star', i < got ? 'on' : 'off'), el('span', goalText(g)))
      goals.append(li)
    })
    panel.append(goals)
    panel.append(el('h3', '对面的卡'), foesEl(L.enemy))
    panel.append(el('h3', '奖励'))
    const rw = el('div', '', 'reward')
    if (!got) {
      rw.append(pill('coin', `第一次通关 ${L.coins}`, 'coin'), pill('star', `每颗星 ${starCoins(L.chapter)}`, 'star'))
      if (L.unlock) {
        const u = el('div', '', 'unlock')
        u.append(artSpan(card(L.unlock).art, 30), el('span', `解锁 ${card(L.unlock).name}`))
        rw.append(u)
      }
    } else {
      rw.append(pill('coin', `再赢一次 ${replayCoins(L.chapter, 1)}–${replayCoins(L.chapter, 3)}`, 'coin'))
      if (got < 3) rw.append(pill('star', `新的星每颗 ${starCoins(L.chapter)}`, 'star'))
    }
    panel.append(rw)
    panel.append(el('h3', '出战卡组'))
    panel.append(deckPicker(app, () => levelSheet(app, LEVEL_BY_ID[L.id])))
    const go = button('开战', () => {
      app.overlay.hide()
      app.startLevel(L.id)
    }, 'primary')
    go.disabled = app.frozen
    panel.append(row(button('取消', () => app.overlay.hide()), go))
  }, { cls: 'sheet level', onDismiss: () => undefined })
}

/** 三套卡组的切换条 + 当前这套的 8 张小卡 */
function deckPicker(app: App, redraw: () => void): HTMLElement {
  const p = app.profile()
  const w = el('div', '', 'deckpick')
  const tabs = el('div', '', 'seg')
  for (let i = 0; i < DECKS; i++) {
    const b = button(`卡组${'一二三'[i]}`, () => {
      app.useDeck(i)
      redraw()
    })
    b.setAttribute('aria-pressed', String(p.deck === i))
    tabs.append(b)
  }
  w.append(tabs)
  const mini = el('div', '', 'mini-deck')
  for (const id of activeDeck(p)) {
    const c = card(id)
    const m = el('span', '', `mini ${c.kind}`)
    m.append(artSpan(c.art, 28), el('i', String(c.cost)))
    m.title = c.name
    mini.append(m)
  }
  w.append(mini)
  return w
}

// ---------------------------------------------------------------- 卡牌

let swapFrom = -1 // 卡组里选中要换下的那一格
let swapIn: string | null = null // 从收藏里选中要换进来的卡

/** 离开卡牌页时清掉没换完的选择 */
export function resetSwap(): void {
  swapFrom = -1
  swapIn = null
}

export function cards(app: App, root: HTMLElement): void {
  const p = app.profile()
  const s = el('div', '', 'scr cards')
  s.append(header(app, '卡牌', pill('coin', num(coins(p)), 'coin')))
  const bar = el('div', '', 'deckbar')
  const tabs = el('div', '', 'seg')
  for (let i = 0; i < DECKS; i++) {
    const b = button(`卡组${'一二三'[i]}`, () => {
      swapFrom = -1
      swapIn = null
      app.useDeck(i)
    })
    b.setAttribute('aria-pressed', String(p.deck === i))
    tabs.append(b)
  }
  bar.append(tabs)
  const deck = activeDeck(p)
  const grid = el('div', '', 'deck-grid')
  deck.forEach((id, i) => {
    const c = card(id)
    const e = cardEl(c, { level: cardLevel(p, id), size: 46, cls: `${swapFrom === i ? 'sel' : ''} ${swapIn ? 'wiggle' : ''}` })
    const b = button('', () => {
      if (swapIn) {
        const next = deck.slice()
        next[i] = swapIn
        swapIn = null
        swapFrom = -1
        app.setDeck(p.deck, next)
        sfx('place', { vol: 0.5 })
        return
      }
      swapFrom = swapFrom === i ? -1 : i
      sfx('pick', { vol: 0.4 })
      app.go('cards')
    }, 'slot')
    b.append(e)
    b.setAttribute('aria-label', `${c.name},卡组第 ${i + 1} 张${swapFrom === i ? ',已选中,再点收藏里的一张换进来' : ''}`)
    grid.append(b)
  })
  bar.append(grid)
  const avg = deck.reduce((n, id) => n + card(id).cost, 0) / deck.length
  const info = el('p', swapIn ? `点卡组里的一张,换成「${card(swapIn).name}」` : swapFrom >= 0 ? '再点下面收藏里的一张,换进这个位置'
    : `选中的这套出战 · 平均费用 ${avg.toFixed(1)} · 点一张再点收藏里的,就换进来`, 'deck-info')
  if (swapIn || swapFrom >= 0) {
    const cancel = button('取消', () => {
      swapIn = null
      swapFrom = -1
      app.go('cards')
    }, 'link')
    info.append(cancel)
  }
  bar.append(info)
  s.append(bar)
  const have = new Set(unlocked(p))
  s.append(el('h3', `收藏 ${have.size}/${COLLECTION.length}`, 'sec'))
  const coll = el('div', '', 'coll')
  for (const id of COLLECTION) {
    const c = card(id)
    const got = have.has(id)
    const inDeck = deck.indexOf(id) >= 0
    const e = cardEl(c, { level: got ? cardLevel(p, id) : undefined, locked: !got, size: 46, cls: inDeck ? 'indeck' : '' })
    if (got && canUpgrade(p, id)) e.append(el('i', '', 'updot'))
    if (inDeck) {
      const badge = el('span', '', 'inic')
      badge.append(icon('check'))
      e.append(badge)
    }
    if (!got) {
      const by = unlockedBy(id)
      e.append(el('span', by ? `${by.id} 解锁` : '', 'how'))
    }
    const b = button('', () => {
      if (got && swapFrom >= 0 && !inDeck) {
        const next = deck.slice()
        next[swapFrom] = id
        swapFrom = -1
        app.setDeck(p.deck, next)
        sfx('place', { vol: 0.5 })
        return
      }
      cardSheet(app, id)
    }, 'slot')
    b.append(e)
    b.setAttribute('aria-label', `${c.name}${got ? `,${cardLevel(p, id)} 级${inDeck ? ',在卡组里' : ''}` : ',还没解锁'}`)
    coll.append(b)
  }
  s.append(coll)
  root.append(s)
}

const speedWord = (v: number) => (v >= 1.4 ? '很快' : v >= 1.1 ? '快' : v >= 0.85 ? '中等' : v > 0 ? '慢' : '不动')

export function cardSheet(app: App, id: string): void {
  const p = app.profile()
  const c = card(id)
  const got = unlocked(p).indexOf(id) >= 0
  const lvl = cardLevel(p, id)
  const mul = statMul(lvl)
  const mul2 = statMul(Math.min(MAX_LEVEL, lvl + 1))
  app.overlay.show((panel) => {
    const head = el('div', '', 'cd-head')
    head.append(cardEl(c, { level: got ? lvl : undefined, locked: !got, size: 66, cls: 'hero-card' }))
    const t = el('div', '', 'cd-title')
    t.append(el('h2', c.name), el('p', c.tags.join(' · '), 'tags'))
    head.append(t)
    panel.append(head, el('p', c.desc, 'desc'))
    const tb = el('dl', '', 'stats')
    const add = (k: string, v: string) => tb.append(el('dt', k), el('dd', v))
    const up = got && lvl < MAX_LEVEL
    const two = (a: number, b: number) => (up ? `${Math.round(a)} → ${Math.round(b)}` : String(Math.round(a)))
    add('费用', `${c.cost} 点能量`)
    if (c.unit) {
      const u = c.unit
      add('生命', two(u.hp * mul, u.hp * mul2))
      if (u.atk > 0) {
        add('每次伤害', two(u.atk * mul, u.atk * mul2) + (u.count && u.count > 1 ? `(×${u.count} 只)` : ''))
        add('出手间隔', `${u.rate} 秒`)
        add('射程', u.range >= 1.2 ? `${u.range} 格` : '近战')
        add('打谁', u.siege ? '只打建筑' : u.air || u.hitsAir ? '地面和空中' : '只打地面')
      }
      if (u.speed > 0) add('移动', speedWord(u.speed))
      if (u.air) add('位置', '飞在天上')
      if (u.life) add('存在', `${u.life} 秒`)
      if (u.heal) add('光环回血', `每秒 ${two(u.heal * mul, u.heal * mul2)}`)
      if (u.poison) add('中毒', `每秒 ${two(u.poison * mul, u.poison * mul2)},4 秒`)
      if (u.splash) add('范围', `${u.splash} 格`)
    } else if (c.spell) {
      const sp = c.spell
      add('范围', `半径 ${sp.radius} 格`)
      if (sp.damage) add('伤害', `${two(sp.damage * mul, sp.damage * mul2)}(打塔 ${Math.round((sp.towerPct ?? 1) * 100)}%)`)
      if (sp.freeze) add('冻住', `${sp.freeze} 秒`)
      if (sp.heal) add('回血', two(sp.heal * mul, sp.heal * mul2))
      if (sp.rage) add('鼓舞', `${sp.rage} 秒`)
    }
    panel.append(tb)
    if (!got) {
      const by = unlockedBy(id)
      panel.append(el('p', by ? `第一次通过 ${by.id}「${by.name}」就解锁(固定奖励,不抽卡)。` : '', 'how'))
      panel.append(row(button('知道了', () => app.overlay.hide(), 'primary')))
      return
    }
    const cost = upgradeCost(p, id)
    const lv = el('div', '', 'lvrow')
    lv.append(el('span', `${lvl} 级${lvl >= MAX_LEVEL ? '(满级)' : ''}`))
    if (cost !== null) {
      const ub = button('', () => app.upgradeCard(id), 'primary up')
      ub.append(el('span', '升级'), icon('coin'), el('b', num(cost)))
      ub.disabled = !canUpgrade(p, id)
      lv.append(ub)
      if (!canUpgrade(p, id) && !app.frozen) lv.append(el('small', `还差 ${num(cost - coins(p))} 金币`))
    }
    panel.append(lv)
    const deck = activeDeck(p)
    const btns: HTMLButtonElement[] = [button('关闭', () => app.overlay.hide())]
    if (deck.indexOf(id) < 0) {
      btns.push(button('换进卡组', () => {
        swapIn = id
        swapFrom = -1
        app.overlay.hide()
        app.go('cards')
        app.toast(`点卡组里的一张,换成「${c.name}」`)
      }))
    }
    panel.append(row(...btns))
  }, { cls: 'sheet card-sheet', onDismiss: () => undefined })
}

// ---------------------------------------------------------------- 成就

export function achievements(app: App, root: HTMLElement): void {
  const p = app.profile()
  const s = el('div', '', 'scr ach')
  s.append(header(app, '成就', pill('trophy', `${p.ach.length}/${ACHIEVEMENTS.length}`, 'star')))
  const ul = el('ul', '', 'ach-list')
  for (const a of ACHIEVEMENTS) {
    const done = p.ach.indexOf(a.id) >= 0
    const cur = Math.min(a.n, achProgress(p, a))
    const li = el('li', '', done ? 'done' : '')
    li.append(icon(done ? 'medal' : 'target', 'aic'))
    const t = el('div', '', 'at')
    t.append(el('b', a.name), el('span', a.desc))
    const bar = el('div', '', 'prog')
    const fill = el('i')
    fill.style.transform = `scaleX(${cur / a.n})`
    bar.append(fill)
    t.append(bar)
    li.append(t)
    const r = el('div', '', 'ar')
    r.append(el('small', done ? '已达成' : `${cur}/${a.n}`), pill('coin', `+${a.coins}`, 'coin sm'))
    li.append(r)
    ul.append(li)
  }
  s.append(ul)
  s.append(el('p', '成就的金币达成时自动到账,没有要手动领的东西。', 'fine'))
  root.append(s)
}

// ---------------------------------------------------------------- 每日挑战

export function daily(app: App, root: HTMLElement): void {
  const p = app.profile()
  const d = dailyChallenge(dayKey(app.now()))
  const done = dailyDone(p, d.date)
  const s = el('div', '', 'scr daily')
  s.append(header(app, '每日挑战'))
  const box = el('div', `${''}`, `daily-card theme-${d.cfg.theme}`)
  box.append(el('small', '今天的关', 'eyebrow'), el('h3', d.name), el('p', d.rule))
  const st = el('div', '', 'daily-st')
  st.append(stars(done), el('span', done ? `今天最好 ${done} 星` : `第一次赢拿 ${DAILY_COINS} 金币`))
  box.append(st)
  s.append(box)
  s.append(el('h3', `发给你的卡组(都是 ${DAILY_LEVEL} 级)`, 'sec'))
  const g = el('div', '', 'deck-grid')
  for (const id of d.cfg.decks[0].cards) g.append(cardEl(card(id), { level: DAILY_LEVEL, size: 46 }))
  s.append(g)
  s.append(el('h3', '对面的卡', 'sec'), foesEl(d.cfg.decks[1].cards))
  s.append(el('p', '每天北京时间 0 点换关,人人打同一关;两边卡牌都是固定等级,和你自己的收藏、等级无关。' +
    '可以打很多次,记最好的星数;没有连续挑战奖励,哪天不打也不亏什么。', 'fine'))
  const go = button('开始挑战', () => app.startDaily(), 'cta primary')
  go.disabled = app.frozen
  s.append(go)
  root.append(s)
}

// ---------------------------------------------------------------- 结算

export function result(app: App, b: Battle, reward: Reward, next: { retry: () => void; next?: () => void; back: () => void }): void {
  const over = b.over!
  const won = over.winner === 0
  const n = starsOf(b)
  const L = LEVEL_BY_ID[b.cfg.tag]
  app.overlay.show((panel) => {
    const ban = el('div', won ? '胜利!' : over.winner === -1 ? '平局' : over.reason === 'quit' ? '认输了' : '失败', 'rbanner')
    // 图放在 public 里,按页面的相对路径引用(不经过打包,不会多出一份带哈希的拷贝)
    ban.style.backgroundImage = 'url(art/ui/banner.webp)'
    panel.append(ban)
    const sw = el('div', '', 'rstars')
    for (let i = 0; i < 3; i++) {
      const st = icon('star', i < n ? 'on' : 'off')
      if (i < n) {
        st.style.animationDelay = `${0.35 + i * 0.28}s`
        window.setTimeout(() => sfx('star', { vol: 0.6, rate: 1 + i * 0.12, gap: 0 }), 350 + i * 280)
      }
      sw.append(st)
    }
    panel.append(sw)
    panel.append(el('p', L ? `${L.id} ${L.name}` : dailyChallenge(b.cfg.tag.slice(6)).name, 'sub'))
    const goals = el('ul', '', 'goals')
    b.cfg.stars.forEach((g, i) => {
      const ok = won && (i === 0 || goalOk(b, g))
      const li = el('li', '', ok ? 'got' : '')
      li.append(icon(ok ? 'check' : 'close'), el('span', goalText(g)))
      goals.append(li)
    })
    panel.append(goals)
    const st = el('div', '', 'rstats')
    const mm = Math.floor(over.t / 60)
    const ss = Math.floor(over.t % 60)
    for (const [k, v] of [['击倒', String(b.stats[0].kills)], ['返还能量', b.stats[0].refund.toFixed(1)],
      ['推倒', `${b.stats[0].towers + (b.stats[0].base ? 1 : 0)} 座`], ['用时', `${mm}:${String(ss).padStart(2, '0')}`]]) {
      const c = el('div')
      c.append(el('b', v), el('small', k))
      st.append(c)
    }
    panel.append(st)
    if (reward.coins || reward.cards.length || reward.achievements.length) {
      const rw = el('div', '', 'reward')
      if (reward.coins) {
        const cp = pill('coin', '+0', 'coin lg')
        rw.append(cp)
        countUp(cp.querySelector('b') as HTMLElement, reward.coins)
        window.setTimeout(() => sfx('coins', { vol: 0.6 }), 700)
      }
      for (const id of reward.cards) {
        const u = el('div', '', 'unlock new')
        u.append(artSpan(card(id).art, 34), el('span', `新卡:${card(id).name}`))
        rw.append(u)
        window.setTimeout(() => sfx('unlock', { vol: 0.7 }), 1300)
      }
      for (const a of reward.achievements) {
        const ach = ACHIEVEMENTS.find((x) => x.id === a)!
        const u = el('div', '', 'unlock ach')
        u.append(icon('medal'), el('span', `成就:${ach.name}`))
        rw.append(u)
      }
      panel.append(rw)
    } else if (!won && L) {
      panel.append(el('p', tipFor(b), 'tip'))
    }
    const btns: HTMLButtonElement[] = [button('返回', next.back), button('再来一次', next.retry)]
    if (next.next) btns.push(button('下一关', next.next, 'primary'))
    else btns[1].classList.add('primary')
    panel.append(row(...btns))
  }, { cls: `sheet result ${won ? 'win' : 'lose'}` })
}

function goalOk(b: Battle, g: Goal): boolean {
  switch (g.kind) {
    case 'win': return true
    case 'lost': return b.stats[0].lost <= g.n
    case 'time': return (b.over?.t ?? 1e9) <= g.n
    case 'kills': return b.stats[0].kills >= g.n
  }
  return false
}

function tipFor(b: Battle): string {
  const tips = [
    '同一路里先放一个血厚的在前面顶着,远程跟在后面,比一只一只送上去强得多。',
    '击倒敌人会返还能量:守住一波再反推,往往比硬冲划算。',
    '对面单位扎堆的时候丢火球;天上的鹦鹉、猫头鹰要用能打空中的(鸭子、猴子、瞭望台……)。',
    '卡牌可以用赢来的金币升级,塔的等级按出战卡组的平均等级算。',
    '两边的哨塔只管自己那一路:哪一路守得薄,就从哪一路推。',
  ]
  return `小提示:${tips[Math.floor(b.t) % tips.length]}`
}

function countUp(e: HTMLElement, to: number): void {
  const t0 = performance.now()
  const dur = 900
  const tick = (t: number) => {
    const k = Math.min(1, (t - t0 - 500) / dur)
    e.textContent = `+${num(Math.max(0, Math.round(to * (k < 0 ? 0 : 1 - Math.pow(1 - k, 3)))))}`
    if (k < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

// ---------------------------------------------------------------- 关于

export function about(app: App): void {
  app.overlay.show((panel) => {
    panel.append(el('h2', '关于萌兽三路'), bullets([
      '单机卡牌对战:你在下、电脑在上,拖一张卡到自己半场的路上就出兵;单位沿路走、自己找敌人打,塔会自动射箭。',
      '三条路:单位只在自己那一路打,推倒这一路对面的哨塔,才能沿路去打对面的大本营;哨塔只管自己那一路,大本营打射程里所有的敌人。',
      '能量:随时间回复,击倒敌方单位还会返还它费用的 25%(一张卡出好几只的按只分摊)。守得漂亮也能攒出反推的本钱。',
      '胜负:推倒对面大本营直接赢;时间到了比谁推倒的哨塔多,一样多比剩下的塔血,再一样是平局。有的关是坚守(守满时间就赢)或速攻(时间内推够塔才赢)。',
      '成长:通关按固定奖励表解锁卡牌,不抽卡、不开宝箱;对局赢来的金币用来升级卡牌;卡组可以存三套。',
      '没有广告,没有内购,没有排行榜,没有体力、没有签到、没有要等的宝箱。',
      '存档自动存到超级赞云存储,换设备接着玩;打到一半关掉,下次打开接着那一局(先停着,点继续再走)。',
      '素材:动物、场景、界面、图标、粒子和音效来自 Kenney(kenney.nl)的公开素材包,CC0 公有领域授权;游戏里的名字、规则、关卡都是原创。',
    ]))
    panel.append(row(button('知道了', () => app.overlay.hide(), 'primary')))
  }, { cls: 'about', onDismiss: () => undefined })
}
