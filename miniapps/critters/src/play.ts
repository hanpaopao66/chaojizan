// 对局界面:画布 + 上下两条界面(计时、推塔数、Boss 血条 / 能量条、手牌、下一张)。
// 模拟按固定步长走(每步 50 毫秒),画面每帧插值;出牌是把「这一步要出的牌」交给 step,由它判断合不合法。
//
// 出牌:按住一张牌拖到下半场的路上松手;或者先点一下牌、再点战场。键盘:1–4 选牌,← ↓ → 出到左中右三路。
import { artSpan, icon, setArt } from './assets'
import { play as sfx } from './audio'
import { Ev, canPlay, step } from './battle'
import { CHAPTERS, ENERGY_MAX, FIELD_W, LANE_X, Side, ZONE, card } from './data'
import { Battle, Cmd, DT, baseOf, foe } from './field'
import { Renderer } from './render'
import { $, WebApp, el, reduced } from '../../shared/src/ui'

export interface PlayHooks {
  /** 打完了(结束动画放完之后) */
  onEnd(b: Battle): void
  /** 该存一下这一局了(每隔几秒、暂停、切走时) */
  onSnapshot(b: Battle): void
  /** 暂停键 / 宿主返回键 */
  onPauseMenu(): void
}

type Phase = 'idle' | 'countdown' | 'running' | 'paused' | 'ending'

const fmt = (sec: number) => {
  const s = Math.max(0, Math.ceil(sec))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export class Play {
  readonly root = $('battle')
  readonly canvas = $<HTMLCanvasElement>('field')
  readonly r = new Renderer(this.canvas)
  battle: Battle | null = null
  phase: Phase = 'idle'
  /** 时间倍率(只有开发时的测试钩子会改,见 main.ts) */
  timeScale = 1
  private pending: Cmd[] = []
  private raf = 0
  private last = 0
  private acc = 0
  private countT = 0
  private endT = 0
  private snapT = 0
  private selected = -1
  private drag: { slot: number; id: number; x0: number; y0: number; moved: boolean; over: boolean } | null = null
  private cards: HTMLButtonElement[] = []
  private handKey = ''
  private lastEnergy = -1
  private hint = false
  private live = $('live')
  private dark = false
  private name = ''

  constructor(private readonly hooks: PlayHooks) {
    this.cards = Array.from(this.root.querySelectorAll<HTMLButtonElement>('.hand .card'))
    this.cards.forEach((b, i) => this.bindCard(b, i))
    $('b-pause').append(icon('pause'))
    $('b-pause').addEventListener('click', () => this.hooks.onPauseMenu())
    this.canvas.addEventListener('pointerdown', (e) => this.fieldDown(e))
    window.addEventListener('pointermove', (e) => this.move(e))
    window.addEventListener('pointerup', (e) => this.up(e))
    window.addEventListener('pointercancel', () => this.cancelDrag())
    window.addEventListener('keydown', (e) => this.key(e))
    new ResizeObserver(() => this.layout()).observe(this.root)
  }

  // ---------------------------------------------------------------- 开始 / 暂停 / 结束

  /** 开一局(或接着打存档里的那一局:resumed 为真时先停着) */
  start(b: Battle, opts: { name: string; resumed: boolean; hint: boolean; dark: boolean }): void {
    this.battle = b
    this.name = opts.name
    this.hint = opts.hint
    this.dark = opts.dark
    this.pending = []
    this.selected = -1
    this.drag = null
    this.handKey = ''
    this.lastEnergy = -1
    this.shown.clear()
    this.acc = 0
    this.snapT = 0
    this.r.reset()
    this.root.hidden = false
    document.body.classList.add('in-battle')
    $('b-name').textContent = opts.name
    const cfg = b.cfg
    $('b-goal').textContent = cfg.objective === 'defend' ? '坚守' : cfg.objective === 'blitz' ? `速攻 · 推倒 ${cfg.target} 座` : ''
    this.root.dataset.theme = cfg.theme
    this.layout()
    this.r.setScene(cfg.theme, cfg.closed, opts.dark)
    this.syncHand(true)
    this.hud()
    $('b-hint').hidden = !opts.hint
    if (opts.resumed || b.t > 0) {
      this.phase = 'paused'
      this.render()
    } else {
      this.phase = 'countdown'
      this.countT = 0
      sfx('shuffle', { vol: 0.5 })
      this.banner('3', 'count')
      sfx('count')
      this.loop()
    }
    this.syncBack()
  }

  setDark(dark: boolean): void {
    this.dark = dark
    if (this.battle) {
      this.r.setScene(this.battle.cfg.theme, this.battle.cfg.closed, dark)
      if (this.phase !== 'running') this.render()
    }
  }

  pause(): void {
    if (this.phase === 'running' || this.phase === 'countdown') {
      this.phase = 'paused'
      this.cancelDrag()
      if (this.battle) this.hooks.onSnapshot(this.battle)
    }
    this.syncBack()
  }

  resume(): void {
    if (this.phase !== 'paused' || !this.battle) return
    if (this.battle.over) return
    this.phase = this.battle.t > 0 ? 'running' : 'countdown'
    this.last = 0
    this.loop()
    this.syncBack()
  }

  get active(): boolean {
    return this.phase !== 'idle'
  }

  stop(): void {
    this.phase = 'idle'
    cancelAnimationFrame(this.raf)
    this.raf = 0
    this.root.hidden = true
    document.body.classList.remove('in-battle')
    this.battle = null
    this.cancelDrag()
    WebApp.BackButton.hide()
  }

  private syncBack(): void {
    if (this.phase === 'running' || this.phase === 'countdown') WebApp.BackButton.show()
    else WebApp.BackButton.hide()
  }

  // ---------------------------------------------------------------- 布局

  private layout(): void {
    const box = this.root.getBoundingClientRect()
    if (!box.width || !box.height) return
    const top = $('b-top').getBoundingClientRect()
    const bottom = $('b-bottom').getBoundingClientRect()
    const area = { x: 6, y: top.bottom - box.top + 4, w: box.width - 12, h: bottom.top - top.bottom - 8 }
    this.canvas.style.width = `${box.width}px`
    this.canvas.style.height = `${box.height}px`
    this.r.layout(box.width, box.height, area)
    if (this.battle) this.r.setScene(this.battle.cfg.theme, this.battle.cfg.closed, this.dark)
    this.orbTarget()
    if (this.phase !== 'running') this.render()
  }

  private orbTarget(): void {
    const box = this.root.getBoundingClientRect()
    const bar = $('b-energy-bar').getBoundingClientRect()
    this.r.orbTarget = { x: bar.left - box.left + bar.width * 0.5, y: bar.top - box.top + bar.height / 2 }
  }

  private render(): void {
    this.r.frame(this.battle, 1, 0)
  }

  // ---------------------------------------------------------------- 主循环

  private loop = (): void => {
    if (this.raf) return
    const tick = (t: number) => {
      this.raf = 0
      if (this.phase === 'idle' || this.phase === 'paused') return
      const dt = this.last ? Math.min(0.1, (t - this.last) / 1000) : 0
      this.last = t
      if (this.phase === 'countdown') this.countdown(dt)
      else if (this.phase === 'running') {
        this.acc += dt * this.timeScale
        let n = 0
        const cap = 6 * Math.max(1, this.timeScale)
        while (this.acc >= DT && n < cap && this.phase === 'running') {
          this.stepOnce()
          this.acc -= DT
          n++
        }
        if (n >= cap) this.acc = 0
      } else if (this.phase === 'ending') {
        this.endT += dt
        if (this.endT > 1.9 && this.battle) {
          const b = this.battle
          this.phase = 'paused'
          this.hooks.onEnd(b)
          return
        }
      }
      this.r.frame(this.battle, this.phase === 'running' ? Math.min(1, this.acc / DT) : 1, dt)
      this.hud()
      this.raf = requestAnimationFrame(tick)
    }
    this.last = 0
    this.raf = requestAnimationFrame(tick)
  }

  private countdown(dt: number): void {
    const before = this.countT
    this.countT += dt
    const marks = [0.75, 1.5, 2.25]
    marks.forEach((m, i) => {
      if (before < m && this.countT >= m) {
        if (i < 2) {
          this.banner(String(2 - i), 'count')
          sfx('count')
        } else {
          this.banner('开战!', 'go')
          sfx('go')
          WebApp.HapticFeedback.impactOccurred('medium')
          this.phase = 'running'
          this.acc = 0
        }
      }
    })
  }

  private stepOnce(): void {
    if (!this.battle) return
    const r = step(this.battle, this.pending)
    this.pending = []
    this.battle = r.state
    this.r.onEvents(r.events, r.state)
    this.events(r.events)
    this.snapT += DT
    if (this.snapT >= 3 && !r.state.over) {
      this.snapT = 0
      this.hooks.onSnapshot(r.state)
    }
    this.syncHand()
  }

  private events(evs: Ev[]): void {
    const b = this.battle!
    for (const e of evs) {
      switch (e.e) {
        case 'play':
          if (e.side === 0) {
            sfx('place', { vol: 0.7 })
            sfx('pop', { vol: 0.5 })
            WebApp.HapticFeedback.impactOccurred('light')
            if (this.hint) {
              this.hint = false
              $('b-hint').hidden = true
            }
          } else {
            sfx('pop', { vol: 0.35, rate: 0.9 })
            if (card(e.card).boss) this.banner(`${card(e.card).name}来了!`, 'boss')
          }
          break
        case 'hit':
          if (e.tower) sfx('tower', { vol: 0.35, gap: 140 })
          else if (e.dmg >= 150) sfx('heavy', { vol: 0.55, gap: 90 })
          else sfx((['hit0', 'hit1', 'hit2'] as const)[b.nextId % 3], { vol: 0.32, gap: 55, rate: 0.9 + (b.nextId % 5) * 0.05 })
          break
        case 'shoot':
          if (e.kind !== 'arrow') sfx('throw', { vol: 0.25, gap: 90, rate: 1.1 })
          break
        case 'die':
          if (!e.expired) sfx('poof', { vol: 0.35, gap: 70 })
          break
        case 'refund':
          if (e.side === 0) {
            sfx('refund', { vol: 0.3, gap: 120 })
            this.floatText(`+${e.amount.toFixed(e.amount < 1 ? 2 : 1).replace(/0$/, '')}`)
          }
          break
        case 'tower': {
          sfx('crash', { vol: 0.8 })
          sfx('boom', { vol: 0.6 })
          WebApp.HapticFeedback.impactOccurred('heavy')
          const where = e.lane === -1 ? '大本营' : `${['左', '中', '右'][e.lane]}路哨塔`
          this.live.textContent = e.side === 1 ? `推倒了对面的${where}` : `我方的${where}倒了`
          if (e.lane !== -1) this.banner(e.side === 1 ? `推倒${where}` : `丢了${where}`, e.side === 1 ? 'good' : 'bad')
          break
        }
        case 'spell':
          sfx(e.card === 'fire' ? 'boom' : e.card === 'freeze' ? 'freeze' : e.card === 'heal' ? 'heal' : 'rage', { vol: 0.6 })
          if (e.card === 'fire') WebApp.HapticFeedback.impactOccurred('medium')
          break
        case 'pulse':
          sfx('heavy', { vol: 0.6, rate: 0.8 })
          break
        case 'end':
          this.finish(e.winner)
          break
      }
    }
  }

  private finish(winner: Side | -1): void {
    this.phase = 'ending'
    this.endT = 0
    this.cancelDrag()
    this.syncBack()
    const b = this.battle!
    if (winner === 0) {
      sfx('win', { vol: 0.8 })
      WebApp.HapticFeedback.notificationOccurred('success')
      this.banner('胜利!', 'win')
      if (!reduced()) {
        const base = baseOf(b, 1)
        for (let i = 0; i < 16; i++) {
          this.r.fx.add({ key: i % 2 ? 'star' : 'twinkle', color: (['gold', 'orange', 'pink', 'cyan'] as const)[i % 4],
            x: Math.random() * FIELD_W, y: base.y + Math.random() * 6, z: 1, vz: 2 + Math.random() * 2, gravity: 3,
            vx: (Math.random() - 0.5) * 2, size: 0.3, life: 1.6, spin: 4 })
        }
      }
    } else if (winner === 1) {
      sfx('lose', { vol: 0.8 })
      WebApp.HapticFeedback.notificationOccurred('error')
      this.banner(b.over?.reason === 'timeout' ? '时间到' : '失败', 'lose')
    } else {
      sfx('lose', { vol: 0.6 })
      this.banner('平局', 'draw')
    }
  }

  // ---------------------------------------------------------------- 界面刷新

  /** 界面上的字只在变了的时候才写(每帧都写会让浏览器每帧重排) */
  private shown = new Map<string, string>()

  private put(id: string, text: string): void {
    if (this.shown.get(id) === text) return
    this.shown.set(id, text)
    $(id).textContent = text
  }

  private hud(): void {
    const b = this.battle
    if (!b) return
    const cfg = b.cfg
    const left = cfg.duration - b.t
    this.put('b-timer', fmt(left))
    const low = left <= 10 && !b.over
    if (this.shown.get('low') !== String(low)) {
      this.shown.set('low', String(low))
      $('b-timer').classList.toggle('low', low)
    }
    this.put('b-down', String(b.stats[0].towers + (b.stats[0].base ? 1 : 0)))
    this.put('b-lost', String(b.stats[1].towers + (b.stats[1].base ? 1 : 0)))
    const me = b.sides[0]
    const e = me.energy
    const fill = $('b-fill')
    fill.style.transform = `scaleX(${Math.min(1, e / ENERGY_MAX)})`
    const shown = Math.floor(e + 1e-6)
    if (shown !== this.lastEnergy) {
      this.lastEnergy = shown
      $('b-energy').textContent = String(shown)
    }
    this.cards.forEach((btn, i) => {
      const id = me.hand[i]
      if (!id) return
      const c = card(id)
      const lack = Math.max(0, c.cost - e)
      btn.classList.toggle('poor', lack > 0)
      const shade = btn.querySelector('.shade') as HTMLElement
      shade.style.transform = `scaleY(${lack > 0 ? Math.min(1, lack / c.cost) : 0})`
    })
    const arriving = this.r.orbsArriving()
    if (arriving) {
      const bar = $('b-energy-bar')
      bar.classList.remove('pulse')
      void bar.offsetWidth
      bar.classList.add('pulse')
    }
    // Boss 血条
    const boss = b.units.find((u) => u.side === 1 && card(u.card).boss)
    const bb = $('b-boss')
    bb.hidden = !boss
    if (boss) {
      const name = card(boss.card).name
      if (this.shown.get('boss') !== name) {
        this.shown.set('boss', name)
        ;(bb.querySelector('.boss-name') as HTMLElement).textContent = name
      }
      ;(bb.querySelector('b') as HTMLElement).style.transform = `scaleX(${boss.hp / boss.max})`
    }
    const towers = b.towers.filter((t) => t.alive)
    const label = `战场:${this.name},剩 ${fmt(left)};我方还有 ${towers.filter((t) => t.side === 0).length} 座塔,对面还有 ${towers.filter((t) => t.side === 1).length} 座`
    if (this.shown.get('label') !== label) {
      this.shown.set('label', label)
      this.canvas.setAttribute('aria-label', label)
    }
  }

  /** 手牌变了才重画卡面 */
  private syncHand(force = false): void {
    const b = this.battle
    if (!b) return
    const me = b.sides[0]
    const key = me.hand.join() + '|' + me.queue[0]
    if (!force && key === this.handKey) return
    const prev = this.handKey ? this.handKey.split('|')[0].split(',') : []
    this.handKey = key
    me.hand.forEach((id, i) => {
      const btn = this.cards[i]
      const c = card(id)
      const lvl = b.cfg.decks[0].levels[id] || 1
      btn.className = `card ${c.kind}${this.selected === i ? ' sel' : ''}`
      btn.dataset.id = id
      ;(btn.querySelector('.cost') as HTMLElement).textContent = String(c.cost)
      ;(btn.querySelector('.nm') as HTMLElement).textContent = c.name
      ;(btn.querySelector('.lv') as HTMLElement).textContent = `${lvl}级`
      setArt(btn.querySelector('.art') as HTMLElement, c.art, 52)
      btn.setAttribute('aria-label', `${c.name},${c.cost} 点能量,${c.desc}`)
      if (prev[i] && prev[i] !== id && !reduced()) {
        btn.classList.remove('deal')
        void btn.offsetWidth
        btn.classList.add('deal')
      }
    })
    const next = card(me.queue[0])
    const nx = $('b-next')
    nx.textContent = ''
    nx.append(artSpan(next.art, 30))
    nx.setAttribute('aria-label', `下一张:${next.name}`)
  }

  private banner(text: string, kind: string): void {
    const el0 = $('b-banner')
    el0.textContent = text
    el0.className = `banner ${kind}`
    el0.hidden = false
    void el0.offsetWidth
    el0.classList.add('show')
    const keep = kind === 'win' || kind === 'lose' || kind === 'draw'
    window.clearTimeout(Number(el0.dataset.t || 0))
    if (!keep) el0.dataset.t = String(window.setTimeout(() => { el0.hidden = true }, kind === 'go' ? 700 : 1300))
  }

  private floatText(text: string): void {
    const bar = $('b-energy-bar')
    const f = el('span', text, 'float')
    bar.parentElement!.append(f)
    window.setTimeout(() => f.remove(), 900)
  }

  // ---------------------------------------------------------------- 出牌

  private bindCard(btn: HTMLButtonElement, slot: number): void {
    btn.append(el('span', '', 'glow'), el('span', '', 'art'), el('span', '', 'cost'), el('span', '', 'lv'),
      el('span', '', 'nm'), el('span', '', 'shade'))
    btn.addEventListener('pointerdown', (e) => {
      if (this.phase !== 'running') return
      e.preventDefault()
      this.drag = { slot, id: e.pointerId, x0: e.clientX, y0: e.clientY, moved: false, over: false }
      sfx('pick', { vol: 0.45, gap: 30 })
      WebApp.HapticFeedback.selectionChanged()
      this.select(slot)
    })
    // 键盘和读屏:点一下选中,再点战场或按方向键出
    btn.addEventListener('click', (e) => {
      if (e.detail === 0 && this.phase === 'running') this.select(this.selected === slot ? -1 : slot)
    })
  }

  private select(slot: number): void {
    this.selected = slot
    this.cards.forEach((b, i) => b.classList.toggle('sel', i === slot))
  }

  private point(e: PointerEvent): { x: number; y: number; inField: boolean } {
    const box = this.canvas.getBoundingClientRect()
    const cx = e.clientX - box.left
    const cy = e.clientY - box.top
    const hand = $('b-bottom').getBoundingClientRect()
    const w = this.r.toWorld(cx, cy)
    return { ...w, inField: e.clientY < hand.top - 4 && cx >= 0 && cx <= box.width }
  }

  private move(e: PointerEvent): void {
    const d = this.drag
    if (!d || e.pointerId !== d.id || !this.battle) return
    if (!d.moved && Math.hypot(e.clientX - d.x0, e.clientY - d.y0) > 8) d.moved = true
    if (!d.moved) return
    const p = this.point(e)
    d.over = p.inField
    this.cards[d.slot].classList.toggle('dragging', p.inField)
    this.r.showZone = true
    if (!p.inField) {
      this.r.preview = null
      return
    }
    // 手指会挡住落点:往上提一点
    const lift = e.pointerType === 'touch' ? 0.9 : 0
    this.preview(d.slot, p.x, p.y - lift)
  }

  private preview(slot: number, x: number, y: number): void {
    const b = this.battle!
    const id = b.sides[0].hand[slot]
    const c = card(id)
    const chk = canPlay(b, 0, slot, x, y)
    this.r.preview = { card: c, x: chk.x, y: chk.y, ok: chk.ok, r: c.spell ? c.spell.radius : 0 }
    if (this.phase !== 'running') this.render()
  }

  private up(e: PointerEvent): void {
    const d = this.drag
    if (!d || e.pointerId !== d.id) return
    this.drag = null
    this.r.showZone = false
    this.cards[d.slot].classList.remove('dragging')
    if (!d.moved) {
      // 点了一下:选中这张,等着点战场
      this.r.preview = null
      return
    }
    const p = this.point(e)
    this.r.preview = null
    if (!p.inField) {
      this.select(-1)
      return
    }
    const lift = e.pointerType === 'touch' ? 0.9 : 0
    this.tryPlay(d.slot, p.x, p.y - lift)
  }

  private cancelDrag(): void {
    if (this.drag) this.cards[this.drag.slot].classList.remove('dragging')
    this.drag = null
    this.r.preview = null
    this.r.showZone = false
  }

  /** 先选了牌、再点战场 */
  private fieldDown(e: PointerEvent): void {
    if (this.phase !== 'running' || this.selected < 0 || this.drag) return
    const p = this.point(e)
    if (!p.inField) return
    this.tryPlay(this.selected, p.x, p.y)
  }

  private tryPlay(slot: number, x: number, y: number): void {
    const b = this.battle
    if (!b || this.phase !== 'running') return
    const id = b.sides[0].hand[slot]
    const chk = canPlay(b, 0, slot, x, y)
    if (!chk.ok) {
      sfx('error', { vol: 0.5 })
      WebApp.HapticFeedback.notificationOccurred('warning')
      const btn = this.cards[slot]
      btn.classList.remove('nope')
      void btn.offsetWidth
      btn.classList.add('nope')
      this.live.textContent = chk.why || '这里不能出'
      if (chk.why === '能量不够') this.pulseEnergy()
      return
    }
    // 同一步里别出两张同一个位置的牌
    if (this.pending.some((c) => c.slot === slot)) return
    this.pending.push({ side: 0, slot, card: id, x: chk.x, y: chk.y })
    this.select(-1)
  }

  private pulseEnergy(): void {
    const bar = $('b-energy-bar')
    bar.classList.remove('short')
    void bar.offsetWidth
    bar.classList.add('short')
  }

  private key(e: KeyboardEvent): void {
    if (this.phase !== 'running' || e.metaKey || e.ctrlKey || e.altKey) return
    if ((e.target as HTMLElement).closest?.('.overlay:not([hidden])')) return
    if (e.key >= '1' && e.key <= '4') {
      e.preventDefault()
      const i = Number(e.key) - 1
      this.select(this.selected === i ? -1 : i)
      sfx('pick', { vol: 0.4 })
      return
    }
    const lane = ({ ArrowLeft: 0, ArrowDown: 1, ArrowUp: 1, ArrowRight: 2, a: 0, s: 1, d: 2 } as Record<string, number>)[e.key]
    if (lane === undefined || this.selected < 0 || !this.battle) return
    e.preventDefault()
    const b = this.battle
    const c = card(b.sides[0].hand[this.selected])
    let y = ZONE[0][0] + 2.4
    if (c.kind === 'spell') {
      // 法术:打这一路最靠前的敌人(没有就打对面的塔跟前)
      const foes = b.units.filter((u) => u.side === foe(0) && u.lane === lane && u.hp > 0)
      y = foes.length ? Math.max(...foes.map((u) => u.y)) : 4
    }
    this.tryPlay(this.selected, LANE_X[lane], y)
  }

  /** 章节名(结算页用) */
  static chapterName(tag: string): string {
    const n = Number(tag.split('-')[0])
    return CHAPTERS[n - 1]?.name || ''
  }
}
