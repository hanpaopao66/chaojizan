// 对局部件的「画」:DOM 缓存、英雄 / 随从 / 手牌渲染、目标高亮、飘字动画、横幅、读屏播报。
// 规则和流程在 table.ts;这里不碰电脑、也不改对局状态,只把状态画出来、把事件放成动画。
import { card, hero } from './data'
import { attackTargets, findMinion, playTargets } from './engine'
import type { Ev, GameState, Minion, Side, TargetRef } from './types'
import { MAX_ENERGY } from './types'
import { artEl } from './art'
import { play as sfx } from './audio'
import { $, el, reduced } from '../../shared/src/ui'

export type Mode = 'idle' | 'card' | 'attacker'

/** 界面现在的选择状态(画高亮、提示语用) */
export interface ViewFlags {
  mode: Mode
  selectedHand: number
  attackerUid: number
  paused: boolean
}

export interface ViewHandlers {
  onCard(index: number): void
  onMinion(side: Side, uid: number): void
  onHero(side: Side): void
  onEndTurn(): void
  onPause(): void
  /** 点牌桌空白处(不是按钮的地方) */
  onBlank(): void
}

/** 手牌张数 → 卡面宽度(rem):牌越多越窄,尽量都看得见 */
function cardWidth(n: number): string {
  if (n <= 5) return '4.6rem'
  if (n === 6) return '4.2rem'
  if (n === 7) return '3.9rem'
  if (n === 8) return '3.6rem'
  if (n === 9) return '3.4rem'
  return '3.15rem'
}

/** 手牌张数 → 重叠比例(牌多的时候叠一点,免得一定要横向滚) */
function cardOverlap(n: number): string {
  if (n <= 5) return '.1'
  if (n === 6) return '.16'
  if (n === 7) return '.2'
  if (n === 8) return '.24'
  if (n === 9) return '.27'
  return '.32'
}

export class TableView {
  readonly root = $('table')
  private readonly els = {
    foeHero: $<HTMLButtonElement>('foe-hero'),
    foePortrait: $('foe-portrait'),
    foeHp: $('foe-hp'),
    foeName: $('foe-name'),
    foeLine: $('foe-line'),
    foeEnergy: $('foe-energy'),
    myHero: $<HTMLButtonElement>('my-hero'),
    myPortrait: $('my-portrait'),
    myHp: $('my-hp'),
    foeBoard: $('foe-board'),
    myBoard: $('my-board'),
    banner: $('banner'),
    log: $('log'),
    energy: $('energy'),
    endTurn: $<HTMLButtonElement>('end-turn'),
    hint: $('hint'),
    hand: $('hand'),
    fx: $('fx'),
    pause: $<HTMLButtonElement>('pause'),
  }

  private readonly boardEls: [Map<number, HTMLElement>, Map<number, HTMLElement>] = [new Map(), new Map()]
  /** 只在文字变了的时候写 DOM(每帧都写会让浏览器重排) */
  private readonly shown = new Map<string, string>()
  private readonly live = $('live')
  private handKey = ''
  private heroKey = ''
  private bannerTimer = 0
  private hintTimer = 0
  private hintMsg = ''
  private hintAt = -1e9
  private last: { s: GameState; f: ViewFlags } | null = null

  constructor(private readonly cb: ViewHandlers) {
    this.els.foeHero.addEventListener('click', () => cb.onHero(1))
    this.els.myHero.addEventListener('click', () => cb.onHero(0))
    this.els.myBoard.addEventListener('click', (e) => this.boardClick(e, 0))
    this.els.foeBoard.addEventListener('click', (e) => this.boardClick(e, 1))
    this.els.endTurn.addEventListener('click', () => cb.onEndTurn())
    this.els.pause.addEventListener('click', () => cb.onPause())
    // 点牌桌空白处取消选牌:手牌、随从、英雄和按钮都是 <button>,只把非按钮的空白交给外面判断
    this.root.addEventListener('pointerdown', (e) => {
      if (this.root.hidden) return
      const target = e.target as HTMLElement | null
      if (!target || !this.root.contains(target) || target.closest('button')) return
      this.cb.onBlank()
    })
  }

  // ---------------------------------------------------------------- 开局 / 清空

  reset(): void {
    this.boardEls[0].clear()
    this.boardEls[1].clear()
    this.els.foeBoard.textContent = ''
    this.els.myBoard.textContent = ''
    this.els.hand.textContent = ''
    this.els.fx.textContent = ''
    this.shown.clear()
    this.handKey = ''
    this.heroKey = ''
    this.hintMsg = ''
    this.hintAt = -1e9
    window.clearTimeout(this.bannerTimer)
    window.clearTimeout(this.hintTimer)
    this.els.banner.hidden = true
    this.els.log.textContent = ''
  }

  show(): void {
    this.root.hidden = false
  }

  hide(): void {
    this.root.hidden = true
    window.clearTimeout(this.bannerTimer)
  }

  // ---------------------------------------------------------------- 画整屏

  render(s: GameState, f: ViewFlags): void {
    this.last = { s, f }
    this.renderHud(s, f)
    this.renderBoard(s, 0)
    this.renderBoard(s, 1)
    this.syncHand(s, f)
    this.updateHint(s, f)
  }

  private put(id: string, text: string): void {
    if (this.shown.get(id) === text) return
    this.shown.set(id, text)
    $(id).textContent = text
  }

  private renderHud(s: GameState, f: ViewFlags): void {
    const me = s.sides[0]
    const foe = s.sides[1]
    const myHero = hero(me.hero)
    const foeHero = hero(foe.hero)
    const key = `${me.hero}|${foe.hero}`
    if (this.heroKey !== key) {
      this.heroKey = key
      this.els.myPortrait.textContent = ''
      this.els.foePortrait.textContent = ''
      this.els.myPortrait.append(artEl(myHero.art))
      this.els.foePortrait.append(artEl(foeHero.art))
      this.els.myPortrait.className = `portrait cls-${myHero.cls}`
      this.els.foePortrait.className = `portrait cls-${foeHero.cls}`
      this.put('foe-name', `${foeHero.name} · ${foeHero.title}`)
    }
    this.put('my-hp', String(me.hp))
    this.put('foe-hp', String(foe.hp))
    this.put('foe-line', `手牌 ${foe.hand.length} · 牌库 ${foe.deck.length}`)
    this.els.myHp.classList.toggle('low', me.hp <= 10)
    this.els.foeHp.classList.toggle('low', foe.hp <= 10)
    this.els.foeHero.setAttribute('aria-label', `敌方英雄 ${foeHero.name},${foe.hp} 点生命`)
    this.els.myHero.setAttribute('aria-label', `我的英雄 ${myHero.name},${me.hp} 点生命`)
    this.renderEnergy(me.energy, me.maxEnergy)
    this.renderFoeEnergy(foe.energy, foe.maxEnergy)
    const myTurn = s.active === 0 && !s.over && !f.paused
    this.els.endTurn.disabled = !myTurn
    this.els.endTurn.textContent = s.over ? '对局结束' : s.active === 0 ? '结束回合' : '对手回合…'
    this.root.dataset.turn = s.over ? 'over' : String(s.active)
  }

  private renderEnergy(energy: number, max: number): void {
    const key = `${energy}/${max}`
    if (this.shown.get('energy') === key) return
    this.shown.set('energy', key)
    const box = this.els.energy
    box.textContent = ''
    for (let i = 0; i < MAX_ENERGY; i++) {
      const p = el('i', '', 'pip')
      if (i >= max) p.classList.add('off')
      else if (i < energy) p.classList.add('on')
      box.append(p)
    }
    box.append(el('b', `${energy}/${max}`, 'energy-num'))
    box.setAttribute('aria-label', `能量 ${energy}/${max}`)
  }

  private renderFoeEnergy(energy: number, max: number): void {
    const box = this.els.foeEnergy
    const key = `${energy}/${max}`
    if (this.shown.get('foe-energy') === key) return
    this.shown.set('foe-energy', key)
    box.textContent = ''
    // 还没到对手的第一个回合(上限 0)就不显示这一行,免得挂一个孤零零的 0
    if (max <= 0) {
      box.hidden = true
      return
    }
    box.hidden = false
    for (let i = 0; i < max; i++) {
      const p = el('i', '', 'pip small')
      if (i < energy) p.classList.add('on')
      box.append(p)
    }
    box.append(el('b', `${energy}/${max}`, 'energy-num'))
    box.setAttribute('aria-label', `敌方能量 ${energy}/${max}`)
  }

  private minionButton(m: Minion): HTMLButtonElement {
    const b = el('button', '', 'minion') as HTMLButtonElement
    b.type = 'button'
    b.dataset.uid = String(m.uid)
    const c = card(m.card)
    b.classList.add(`cls-${c.cls}`)
    const art = artEl(c.art)
    art.classList.add('m-art')
    b.append(art, el('span', c.name, 'm-name'))
    b.append(el('span', '', 'm-badges'), el('span', '', 'm-atk'), el('span', '', 'm-hp'))
    return b
  }

  private updateMinion(node: HTMLElement, m: Minion): void {
    const c = card(m.card)
    const atk = node.querySelector('.m-atk') as HTMLElement
    const hp = node.querySelector('.m-hp') as HTMLElement
    const name = node.querySelector('.m-name') as HTMLElement
    const badges = node.querySelector('.m-badges') as HTMLElement
    if (atk.textContent !== String(m.attack)) atk.textContent = String(m.attack)
    if (hp.textContent !== String(m.health)) hp.textContent = String(m.health)
    if (name.textContent !== c.name) name.textContent = c.name
    const badgeKey = `${m.taunt ? 't' : ''}${m.shield ? 's' : ''}`
    if (badges.dataset.key !== badgeKey) {
      badges.dataset.key = badgeKey
      badges.textContent = ''
      if (m.taunt) badges.append(el('i', '嘲', 'mb taunt'))
      if (m.shield) badges.append(el('i', '盾', 'mb shield'))
    }
    node.classList.toggle('taunt', m.taunt)
    node.classList.toggle('hurt', m.health < m.maxHealth)
    node.classList.toggle('sick', m.sick)
    node.setAttribute('aria-label', `${m.taunt ? '嘲讽' : ''}${c.name},${m.attack} 攻击 ${m.health} 生命${
      m.shield ? ',圣盾' : ''}${m.sick ? ',这回合不能攻击' : ''}`)
  }

  private renderBoard(s: GameState, side: Side): void {
    const host = side === 0 ? this.els.myBoard : this.els.foeBoard
    const map = this.boardEls[side]
    const seen = new Set<number>()
    for (const m of s.sides[side].board) {
      seen.add(m.uid)
      let node = map.get(m.uid)
      if (!node) {
        node = this.minionButton(m)
        map.set(m.uid, node)
        node.classList.add('spawn')
        window.setTimeout(() => node?.classList.remove('spawn'), 320)
      }
      this.updateMinion(node, m)
      node.classList.toggle('can-act', side === 0 && s.active === 0 && !s.over && m.attacks > 0 && !m.sick)
      host.append(node)
    }
    for (const [uid, node] of map) {
      if (seen.has(uid)) continue
      node.remove()
      map.delete(uid)
    }
    host.classList.toggle('empty', s.sides[side].board.length === 0)
  }

  private cardButton(id: string, index: number): HTMLButtonElement {
    const c = card(id)
    const b = el('button', '', `hand-card cls-${c.cls}`) as HTMLButtonElement
    b.type = 'button'
    b.dataset.index = String(index)
    b.append(el('span', String(c.cost), 'cost'))
    const art = artEl(c.art)
    art.classList.add('hc-art')
    b.append(art, el('span', c.name, 'hc-name'), el('span', c.text, 'hc-text'))
    if (c.type === 'minion') {
      const stats = el('span', '', 'hc-stats')
      stats.append(el('b', String(c.attack), 'atk'), el('b', String(c.health), 'hp'))
      b.append(stats)
    }
    b.setAttribute('aria-label', `${c.name},${c.cost} 点能量,${c.type === 'minion' ? `${c.attack} 攻击 ${c.health} 生命,` : ''}${c.text || '没有特殊效果'}`)
    b.addEventListener('click', () => this.cb.onCard(index))
    return b
  }

  private syncHand(s: GameState, f: ViewFlags): void {
    const hand = s.sides[0].hand
    const key = hand.join(',')
    if (key !== this.handKey) {
      this.handKey = key
      this.els.hand.textContent = ''
      this.els.hand.style.setProperty('--cw', cardWidth(hand.length))
      this.els.hand.style.setProperty('--ov', cardOverlap(hand.length))
      for (let i = 0; i < hand.length; i++) {
        const btn = this.cardButton(hand[i], i)
        // 手牌摆成很浅的扇形:中间最高、两边微斜,牌多的时候也不至于太乱
        const mid = (hand.length - 1) / 2
        btn.style.setProperty('--rot', `${((i - mid) * 1.8).toFixed(2)}deg`)
        this.els.hand.append(btn)
      }
    }
    const energy = s.sides[0].energy
    Array.from(this.els.hand.children).forEach((child, i) => {
      const id = hand[i]
      if (!id) return
      const b = child as HTMLButtonElement
      b.classList.toggle('poor', card(id).cost > energy)
      b.classList.toggle('sel', f.mode === 'card' && f.selectedHand === i)
    })
    this.els.hand.setAttribute('aria-label', `手牌 ${hand.length} 张`)
  }

  // ---------------------------------------------------------------- 高亮 / 提示

  private nodeOf(t: TargetRef): HTMLElement | undefined {
    if (t.kind === 'hero') return t.side === 0 ? this.els.myHero : this.els.foeHero
    return this.boardEls[t.side].get(t.uid)
  }

  private clearHighlights(): void {
    for (const host of [this.root, this.els.myBoard, this.els.foeBoard]) {
      host.querySelectorAll('.targetable, .sel-minion').forEach((n) => n.classList.remove('targetable', 'sel-minion'))
    }
    this.els.hand.querySelectorAll('.sel').forEach((n) => n.classList.remove('sel'))
  }

  private updateHighlights(s: GameState, f: ViewFlags): void {
    this.clearHighlights()
    if (f.mode === 'card' && f.selectedHand >= 0) {
      const node = this.els.hand.children[f.selectedHand] as HTMLElement | undefined
      node?.classList.add('sel')
      for (const t of playTargets(s, 0, f.selectedHand)) this.nodeOf(t)?.classList.add('targetable')
    } else if (f.mode === 'attacker') {
      this.boardEls[0].get(f.attackerUid)?.classList.add('sel-minion')
      for (const t of attackTargets(s, 0, f.attackerUid)) this.nodeOf(t)?.classList.add('targetable')
    }
  }

  private updateHint(s: GameState, f: ViewFlags): void {
    let text = '第 1 回合 · 你的回合'
    if (s.over) text = '对局结束'
    else if (f.paused) text = '已暂停'
    else if (s.active === 1) text = '电脑在想…'
    else if (f.mode === 'card') {
      const id = s.sides[0].hand[f.selectedHand]
      const c = id ? card(id) : null
      text = c ? `已选「${c.name}」:点目标出牌;点空白处取消` : '点目标'
    } else if (f.mode === 'attacker') {
      const m = findMinion(s, 0, f.attackerUid)
      text = m ? `已选「${card(m.card).name}」:点敌方目标攻击;点自己取消` : '点敌方目标'
    } else if (s.active === 0) {
      text = s.turn === 1 ? '你的回合:点手牌出牌,点自己的随从再点敌方目标攻击' : `第 ${s.turn} 回合 · 你的回合:出牌、攻击,或结束回合`
    }
    const recent = performance.now() - this.hintAt < 1800
    if (recent && this.hintMsg) text = this.hintMsg
    if (this.els.hint.textContent !== text) this.els.hint.textContent = text
    this.els.hint.classList.toggle('bad', recent && !!this.hintMsg)
    this.updateHighlights(s, f)
  }

  /** 操作不合法时在提示栏闪一句原因,并播报给读屏 */
  flashHint(text: string): void {
    this.hintMsg = text
    this.hintAt = performance.now()
    sfx('error')
    this.live.textContent = text
    if (this.last) this.updateHint(this.last.s, this.last.f)
    window.clearTimeout(this.hintTimer)
    this.hintTimer = window.setTimeout(() => {
      this.hintMsg = ''
      this.hintAt = -1e9
      if (this.last) this.updateHint(this.last.s, this.last.f)
    }, 1900)
  }

  /** 读屏单独播一句(选牌、选攻击者时) */
  say(text: string): void {
    this.live.textContent = text
  }

  // ---------------------------------------------------------------- 横幅 / 日志

  log(text: string): void {
    this.els.log.textContent = text
  }

  banner(text: string, kind: string, keep = false): void {
    const b = this.els.banner
    b.textContent = text
    b.className = `banner show ${kind}`
    b.hidden = false
    window.clearTimeout(this.bannerTimer)
    if (!keep) this.bannerTimer = window.setTimeout(() => { b.hidden = true }, 1250)
  }

  // ---------------------------------------------------------------- 动画 / 飘字

  private float(t: TargetRef, text: string, kind: string): void {
    const node = this.nodeOf(t)
    if (!node) return
    this.floatOn(node, text, kind)
  }

  /** 在某个 DOM 元素上方飘一行字 */
  private floatOn(node: HTMLElement, text: string, kind: string): void {
    const r = node.getBoundingClientRect()
    const box = this.root.getBoundingClientRect()
    const f = el('span', text, `float ${kind}`)
    f.style.left = `${r.left - box.left + r.width / 2}px`
    f.style.top = `${r.top - box.top + r.height * 0.15}px`
    this.els.fx.append(f)
    window.setTimeout(() => f.remove(), reduced() ? 260 : 950)
  }

  private shake(node: HTMLElement | undefined, cls = 'hit'): void {
    if (!node) return
    node.classList.remove(cls)
    void node.offsetWidth
    node.classList.add(cls)
    window.setTimeout(() => node.classList.remove(cls), 340)
  }

  /** 事件 → 画面上的小动作(攻击前冲、受伤、飘字、死亡淡出、圣盾) */
  animate(events: Ev[]): void {
    for (const e of events) {
      switch (e.e) {
        case 'attack': {
          const from = this.boardEls[e.side].get(e.uid)
          if (from) {
            from.classList.remove('lunge-up', 'lunge-down')
            void from.offsetWidth
            from.classList.add(e.side === 0 ? 'lunge-up' : 'lunge-down')
            window.setTimeout(() => from.classList.remove('lunge-up', 'lunge-down'), 320)
          }
          break
        }
        case 'damage':
          if (e.shielded || e.amount <= 0) break
          this.float(e.target, `-${e.amount}`, 'dmg')
          this.shake(this.nodeOf(e.target))
          if (e.target.kind === 'hero') this.shake(e.target.side === 0 ? this.els.myHero : this.els.foeHero, 'hurt')
          break
        case 'heal':
          this.float(e.target, `+${e.amount}`, 'heal')
          break
        case 'shield':
          this.float(e.target, '圣盾', 'shield')
          this.shake(this.nodeOf(e.target), 'shield-pop')
          break
        case 'buff':
          this.float(e.target, `+${e.attack}/+${e.health}`, 'buff')
          break
        case 'fatigue':
          this.float({ kind: 'hero', side: e.side }, `疲劳 ${e.amount}`, 'dmg')
          this.shake(e.side === 0 ? this.els.myHero : this.els.foeHero, 'hurt')
          break
        case 'burn':
          this.floatOn(this.els.hand, '手牌满了,烧掉一张', 'dmg')
          break
        case 'death': {
          const node = this.boardEls[e.side].get(e.uid)
          if (node) {
            node.classList.add('dying')
            this.boardEls[e.side].delete(e.uid)
            window.setTimeout(() => node.remove(), reduced() ? 120 : 380)
          }
          break
        }
        case 'turn':
          this.banner(e.side === 0 ? '你的回合' : '对手回合', 'turn')
          break
        case 'play':
          if (e.side === 1) this.log(`对手打出「${card(e.card).name}」`)
          break
        default:
          break
      }
    }
  }

  // ---------------------------------------------------------------- 读屏播报

  private targetName(s: GameState, t: TargetRef): string {
    if (t.kind === 'hero') return t.side === 0 ? '你的英雄' : '电脑的英雄'
    const m = findMinion(s, t.side, t.uid)
    return m ? `${t.side === 0 ? '你的' : '电脑的'}${card(m.card).name}` : '随从'
  }

  private whoName(s: GameState, side: Side, uid: number): string {
    const m = findMinion(s, side, uid)
    return m ? `${side === 0 ? '你的' : '电脑的'}${card(m.card).name}` : '随从'
  }

  /** 把事件翻成一句人话:读屏播报 + 中间那行日志 */
  announce(prev: GameState, next: GameState, events: Ev[]): void {
    const parts: string[] = []
    let attackTarget: string | null = null
    for (const e of events) {
      switch (e.e) {
        case 'turn':
          parts.push(e.side === 0 ? `你的回合,第 ${e.turn} 回合` : `电脑的回合,第 ${e.turn} 回合`)
          break
        case 'play':
          parts.push(`${e.side === 0 ? '你' : '电脑'}打出「${card(e.card).name}」`)
          this.log(`${e.side === 0 ? '你' : '电脑'}打出「${card(e.card).name}」`)
          break
        case 'attack': {
          const line = `${this.whoName(prev, e.side, e.uid)}攻击${this.targetName(prev, e.target)},造成 ${e.toTarget} 点伤害`
          parts.push(line)
          attackTarget = `${e.target.kind}:${e.target.side}:${e.target.kind === 'minion' ? e.target.uid : 0}`
          this.log(line)
          break
        }
        case 'damage': {
          // 攻击造成的伤害上面已经报过了,这里只报法术 / 战吼 / 亡语的伤害
          const key = `${e.target.kind}:${e.target.side}:${e.target.kind === 'minion' ? e.target.uid : 0}`
          if (key === attackTarget && e.amount > 0) break
          if (e.amount > 0) parts.push(`${this.targetName(prev, e.target)}受到 ${e.amount} 点伤害`)
          break
        }
        case 'shield': parts.push('圣盾挡下了这次伤害'); break
        case 'death': parts.push(`${card(e.card).name}死亡`); break
        case 'heal': parts.push(`${this.targetName(prev, e.target)}恢复 ${e.amount} 点生命`); break
        case 'buff': parts.push(`随从获得 +${e.attack}/+${e.health}`); break
        case 'draw': if (e.side === 0) parts.push('你抽了一张牌'); break
        case 'burn': parts.push(`${e.side === 0 ? '你' : '电脑'}手牌满了,烧掉一张牌`); break
        case 'fatigue': parts.push(`${e.side === 0 ? '你' : '电脑'}受到 ${e.amount} 点疲劳伤害`); break
        case 'over': parts.push(e.winner === 0 ? '你赢了' : e.winner === 1 ? '你输了' : '平局'); break
      }
    }
    if (parts.length) {
      this.live.textContent = `${parts.slice(0, 4).join(';')}。现在:你 ${next.sides[0].hp} 点生命,电脑 ${next.sides[1].hp} 点生命。`
      if (!events.some((e) => e.e === 'play' || e.e === 'attack')) this.log(parts[parts.length - 1])
    }
  }

  // ---------------------------------------------------------------- 点击转发

  private boardClick(e: MouseEvent, side: Side): void {
    const node = (e.target as HTMLElement).closest<HTMLElement>('.minion')
    if (!node) return
    const uid = Number(node.dataset.uid)
    if (!Number.isFinite(uid)) return
    this.cb.onMinion(side, uid)
  }
}
