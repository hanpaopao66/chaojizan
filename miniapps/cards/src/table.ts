// 对局流程:开始 / 暂停 / 结束、玩家点击 → 合法动作、电脑回合的调度、每一步之后的存档快照。
// 画的部分在 view.ts,规则在 engine.ts(纯函数),电脑在 ai.ts。这里只做「输入 → 动作 → 重画」。
import { aiNext } from './ai'
import { card } from './data'
import { applyAction, attackTargets, canAttackWith, canPlayCard, findMinion, playTargets, surrender } from './engine'
import { targetKindOf } from './data'
import type { Action, Ev, GameState, Level, Side, TargetRef } from './types'
import { play as sfx, sfxForEvent } from './audio'
import { WebApp, reduced } from '../../shared/src/ui'
import { TableView, type Mode, type ViewFlags } from './view'

export interface MatchResult {
  won: boolean
  draw: boolean
  turns: number
  played: number
  dealt: number
  lost: number
  hero: string
  level: Level
}

export interface TableHooks {
  /** 对局真正结束(结束动画放完) */
  onEnd(r: MatchResult): void
  /** 每一步之后:该存一份快照了 */
  onSnapshot(s: GameState): void
  /** 暂停键 / 宿主返回键 */
  onPause(): void
}

const TARGET_HINT: Record<string, string> = {
  enemy: '点一个敌方目标出牌',
  friendly: '点一个友方目标出牌',
  friendlyMinion: '点一个自己的随从出牌',
  none: '点一下出牌',
}

export class Table {
  private readonly view = new TableView({
    onCard: (i) => this.onCard(i),
    onMinion: (side, uid) => this.onMinion(side, uid),
    onHero: (side) => this.onHero(side),
    onEndTurn: () => this.onEndTurn(),
    onPause: () => this.hooks.onPause(),
  })

  private st: GameState | null = null
  private level: Level = 'normal'
  private paused = false
  private ended = false
  private mode: Mode = 'idle'
  private selectedHand = -1
  private attackerUid = -1
  private aiTimer = 0
  private endTurnTimer = 0
  private turnEnding = false
  private gen = 0

  constructor(private readonly hooks: TableHooks) {
    window.addEventListener('keydown', (e) => this.onKey(e))
  }

  // ---------------------------------------------------------------- 开始 / 暂停 / 结束

  start(s: GameState, level: Level, resumed: boolean): void {
    this.gen++
    this.st = s
    this.level = level
    this.paused = false
    this.ended = false
    this.mode = 'idle'
    this.selectedHand = -1
    this.attackerUid = -1
    this.turnEnding = false
    window.clearTimeout(this.endTurnTimer)
    this.view.reset()
    this.view.show()
    this.render()
    this.view.log(resumed ? '接着上一局,继续。' : '对局开始:你先手。')
    this.view.banner(resumed ? '接着打' : s.active === 0 ? '你的回合' : '对手回合', 'turn')
    if (s.active === 1) this.scheduleAi(520)
    WebApp.BackButton.show()
    sfx('turn')
  }

  stop(): void {
    this.gen++
    this.clearAi()
    window.clearTimeout(this.endTurnTimer)
    this.turnEnding = false
    this.view.hide()
    this.st = null
    this.paused = false
    WebApp.BackButton.hide()
  }

  get state(): GameState | null {
    return this.st
  }

  /** 对局还在进行(结束动画已经开始的也算「不在进行」,暂停菜单不再弹出) */
  get active(): boolean {
    return !!this.st && !this.ended
  }

  pause(): void {
    if (!this.st || this.ended) return
    this.paused = true
    this.clearAi()
    window.clearTimeout(this.endTurnTimer)
    this.turnEnding = false
    this.cancelSelection()
    if (!this.st.over) this.hooks.onSnapshot(this.st)
    this.render()
  }

  resume(): void {
    if (!this.st || this.ended) return
    this.paused = false
    this.render()
    if (this.st.over) return
    if (this.st.active === 1) this.scheduleAi(420)
  }

  /** 认输(暂停菜单里点「认输」) */
  surrender(): void {
    if (!this.st || this.st.over || this.ended) return
    this.paused = false
    const r = surrender(this.st, 0)
    if (r.ok) this.commit(this.st, r.state, r.events)
  }

  private finish(): void {
    const s = this.st
    if (!s || !s.over || this.ended) return
    this.ended = true
    this.clearAi()
    this.cancelSelection()
    const win = s.over.winner === 0
    this.view.banner(win ? '胜利!' : s.over.winner === -1 ? '平局' : '失败', win ? 'win' : 'lose', true)
    this.view.say(win ? '你赢了,对局结束' : s.over.winner === -1 ? '平局' : '你输了,对局结束')
    WebApp.HapticFeedback.notificationOccurred(win ? 'success' : 'error')
    const later = reduced() ? 320 : 1100
    window.setTimeout(() => {
      if (this.ended) this.hooks.onEnd(this.result())
    }, later)
  }

  private result(): MatchResult {
    const s = this.st as GameState
    const me = s.sides[0]
    return {
      won: s.over?.winner === 0, draw: s.over?.winner === -1, turns: s.turn,
      played: me.played, dealt: me.dealt, lost: me.lost, hero: me.hero, level: this.level,
    }
  }

  // ---------------------------------------------------------------- 动作 / 电脑

  private flags(): ViewFlags {
    return { mode: this.mode, selectedHand: this.selectedHand, attackerUid: this.attackerUid, paused: this.paused }
  }

  private render(): void {
    if (this.st) this.view.render(this.st, this.flags())
  }

  private apply(a: Action): boolean {
    const s = this.st
    if (!s || s.over || this.paused) return false
    const r = applyAction(s, a)
    if (!r.ok) {
      this.view.flashHint(r.why)
      return false
    }
    this.commit(s, r.state, r.events)
    return true
  }

  /** 一次动作之后:换状态、放动画、出声、重画、播报、存档、安排电脑 */
  private commit(prev: GameState, next: GameState, events: Ev[]): void {
    this.st = next
    this.mode = 'idle'
    this.selectedHand = -1
    this.attackerUid = -1
    this.view.animate(events)
    for (const e of events) sfxForEvent(e)
    this.render()
    this.view.announce(prev, next, events)
    this.hooks.onSnapshot(next)
    if (next.over) {
      this.finish()
      return
    }
    if (next.active === 1) this.scheduleAi()
    else WebApp.HapticFeedback.selectionChanged()
  }

  private scheduleAi(delay = this.thinkDelay()): void {
    this.clearAi()
    if (this.paused || !this.st || this.st.over) return
    const gen = this.gen
    this.aiTimer = window.setTimeout(() => {
      this.aiTimer = 0
      if (gen !== this.gen || this.paused) return
      this.aiStep()
    }, delay)
  }

  private thinkDelay(): number {
    // 减少动态效果时也缩短电脑「思考」的等待,别让人干等
    if (reduced()) return 160
    return 620 + Math.floor(Math.random() * 520) // 600–1200ms
  }

  private clearAi(): void {
    if (this.aiTimer) window.clearTimeout(this.aiTimer)
    this.aiTimer = 0
  }

  private aiStep(): void {
    const s = this.st
    if (!s || s.over || s.active !== 1 || this.paused) return
    const a = aiNext(s, this.level)
    const r = applyAction(s, a)
    if (!r.ok) {
      // 电脑不该给出非法动作;真出了就转成结束回合,免得卡死在对局里
      const end = applyAction(s, { kind: 'end' })
      if (end.ok) this.commit(s, end.state, end.events)
      return
    }
    this.commit(s, r.state, r.events)
  }

  // ---------------------------------------------------------------- 玩家点击

  private onCard(i: number): void {
    const s = this.st
    if (!s || s.over || this.paused) return
    if (this.turnEnding) {
      this.view.flashHint('正在结束回合…')
      return
    }
    if (s.active !== 0) {
      this.view.flashHint('还没轮到你')
      return
    }
    if (this.mode === 'card' && this.selectedHand === i) {
      this.cancelSelection()
      return
    }
    const id = s.sides[0].hand[i]
    if (!id) return
    const chk = canPlayCard(s, 0, i)
    if (!chk.ok) {
      this.view.flashHint(chk.why)
      return
    }
    const c = card(id)
    if (playTargets(s, 0, i).length === 0) {
      WebApp.HapticFeedback.impactOccurred('light')
      this.apply({ kind: 'play', hand: i, target: null })
      return
    }
    this.mode = 'card'
    this.selectedHand = i
    this.attackerUid = -1
    sfx('tap')
    this.render()
    this.view.say(`已选「${c.name}」,${TARGET_HINT[targetKindOf(c)] || '点一个目标'}`)
  }

  private onMinion(side: Side, uid: number): void {
    const s = this.st
    if (!s || s.over || this.paused) return
    if (this.turnEnding) {
      this.view.flashHint('正在结束回合…')
      return
    }
    if (s.active !== 0) {
      this.view.flashHint('还没轮到你')
      return
    }
    if (this.mode === 'card') {
      const targets = playTargets(s, 0, this.selectedHand)
      if (targets.some((t) => t.kind === 'minion' && t.side === side && t.uid === uid)) {
        this.apply({ kind: 'play', hand: this.selectedHand, target: { kind: 'minion', side, uid } })
      } else {
        this.view.flashHint('这个随从不是合法目标')
      }
      return
    }
    if (this.mode === 'attacker') {
      if (side === 1) {
        const targets = attackTargets(s, 0, this.attackerUid)
        if (targets.some((t) => t.kind === 'minion' && t.side === 1 && t.uid === uid)) {
          WebApp.HapticFeedback.impactOccurred('medium')
          this.apply({ kind: 'attack', uid: this.attackerUid, target: { kind: 'minion', side: 1, uid } })
        } else {
          this.view.flashHint('这个随从现在不能打(有嘲讽要先打嘲讽)')
        }
      } else {
        this.cancelSelection()
      }
      return
    }
    if (side === 0) {
      const chk = canAttackWith(s, 0, uid)
      if (!chk.ok) {
        this.view.flashHint(chk.why)
        return
      }
      this.mode = 'attacker'
      this.attackerUid = uid
      this.selectedHand = -1
      sfx('tap')
      this.render()
      const m = findMinion(s, 0, uid)
      this.view.say(`已选${m ? card(m.card).name : '随从'},点一个敌方目标攻击`)
    }
  }

  private onHero(side: Side): void {
    const s = this.st
    if (!s || s.over || this.paused) return
    if (this.turnEnding) {
      this.view.flashHint('正在结束回合…')
      return
    }
    if (s.active !== 0) {
      this.view.flashHint('还没轮到你')
      return
    }
    const target: TargetRef = { kind: 'hero', side }
    if (this.mode === 'card') {
      const targets = playTargets(s, 0, this.selectedHand)
      if (targets.some((t) => t.kind === 'hero' && t.side === side)) {
        this.apply({ kind: 'play', hand: this.selectedHand, target })
      } else {
        this.view.flashHint('这个英雄不是合法目标')
      }
      return
    }
    if (this.mode === 'attacker' && side === 1) {
      const targets = attackTargets(s, 0, this.attackerUid)
      if (targets.some((t) => t.kind === 'hero' && t.side === 1)) {
        WebApp.HapticFeedback.impactOccurred('medium')
        this.apply({ kind: 'attack', uid: this.attackerUid, target })
      } else {
        this.view.flashHint('对面有嘲讽随从,必须先打嘲讽')
      }
      return
    }
    if (this.mode === 'idle' && side === 0) this.view.flashHint('英雄不能攻击;点随从去攻击')
  }

  private onEndTurn(): void {
    const s = this.st
    if (!s || s.over || this.paused || this.turnEnding) return
    if (s.active !== 0) {
      this.view.flashHint('还没轮到你')
      return
    }
    this.cancelSelection()
    // 先亮「回合结束」横幅,让对手回合的横幅晚一点盖上来;减少动态效果时直接切
    this.view.banner('回合结束', 'turn')
    if (reduced()) {
      this.apply({ kind: 'end' })
      return
    }
    this.turnEnding = true
    const gen = this.gen
    window.clearTimeout(this.endTurnTimer)
    this.endTurnTimer = window.setTimeout(() => {
      this.endTurnTimer = 0
      this.turnEnding = false
      if (gen !== this.gen || this.paused || !this.st || this.st.over || this.st.active !== 0) return
      this.apply({ kind: 'end' })
    }, 320)
  }

  private onKey(e: KeyboardEvent): void {
    const s = this.st
    if (!s || this.view.root.hidden || e.metaKey || e.ctrlKey || e.altKey) return
    const overlayEl = document.getElementById('overlay')
    if (overlayEl && !overlayEl.hidden) return
    if (e.key === 'Escape') {
      if (this.mode !== 'idle') {
        e.preventDefault()
        this.cancelSelection()
      } else this.hooks.onPause()
      return
    }
    if (this.paused || s.over || s.active !== 0) return
    if (e.key === 'e' || e.key === 'E') {
      e.preventDefault()
      this.onEndTurn()
      return
    }
    if (/^[1-9]$/.test(e.key)) {
      const i = Number(e.key) - 1
      if (i < s.sides[0].hand.length) {
        e.preventDefault()
        this.onCard(i)
      }
    } else if (e.key === '0' && s.sides[0].hand.length >= 10) {
      e.preventDefault()
      this.onCard(9)
    }
  }

  private cancelSelection(): void {
    if (this.mode === 'idle') return
    this.mode = 'idle'
    this.selectedHand = -1
    this.attackerUid = -1
    this.render()
  }
}
