// 电脑怎么打。和界面无关:传进一个对局,返回下一步做什么 —— 一定是 legalActions 里的一个合法动作。
//
// 顺序:
// 1. 斩杀:困难档会往后算一串动作(攻击、伤害法术、冲锋),找到能这回合把对面英雄打死的走法就直接走;
//    标准档只看一步。
// 2. 打分:把每个能做的动作都试一遍,用局面分(双方英雄血量、场面攻防、手牌、嘲讽保护)挑涨分最多的;
//    涨得不够多就结束回合,不乱出牌。
// 判分是纯函数、没有随机数:同一个局面永远做同一个决定,单测能复现。
import { card } from './data'
import { applyAction, attackTargets, canPlayCard, legalActions, playTargets } from './engine'
import { Action, GameState, Level, Side, START_HP, TargetRef, foe } from './types'

interface Weights {
  /** 对面英雄掉 1 点血值多少 */
  face: number
  /** 对面每个随从的威胁系数 */
  enemyBoard: number
  /** 自己随从的攻击 / 生命值多少 */
  ownAtk: number
  ownHp: number
  /** 自己低血量时嘲讽的额外价值(困难档才用) */
  taunt: number
  hand: number
}

const NORMAL: Weights = { face: 1.4, enemyBoard: 0.9, ownAtk: 1.7, ownHp: 1.2, taunt: 0, hand: 0.5 }
const HARD: Weights = { face: 1.0, enemyBoard: 1.15, ownAtk: 2.1, ownHp: 1.7, taunt: 0.8, hand: 1.0 }

/** 局面分(站在 side 的立场)。终局给极大的正负值 */
function evaluate(s: GameState, side: Side, w: Weights): number {
  if (s.over) return s.over.winner === side ? 1e6 : s.over.winner === foe(side) ? -1e6 : 0
  const me = s.sides[side]
  const them = s.sides[foe(side)]
  let v = (START_HP - them.hp) * w.face - (START_HP - me.hp) * 0.9 * w.face
  const lowHp = me.hp <= 12
  for (const m of me.board) {
    v += (m.attack * w.ownAtk + m.health * w.ownHp) / 2.6
    if (m.taunt) v += w.taunt * (lowHp ? 2.2 : 1)
    if (m.shield) v += 1.2
  }
  for (const m of them.board) {
    v -= ((m.attack * w.ownAtk + m.health * w.ownHp) / 2.6) * w.enemyBoard
    if (m.shield) v -= 1.2
  }
  v += me.hand.length * w.hand
  return v
}

/** 这回合理论上最多能往对面英雄脸上打多少(高估,只用来给斩杀搜索剪枝) */
function maxBurst(s: GameState, side: Side): number {
  const me = s.sides[side]
  let dmg = 0
  for (const m of me.board) if (m.health > 0 && m.attacks > 0) dmg += m.attack
  for (const id of me.hand) {
    const c = card(id)
    const e = c.type === 'spell' ? c.spell : c.battlecry
    if (e) {
      if (e.kind === 'damage' || e.kind === 'heroDamage') dmg += e.amount
      else if (e.kind === 'buffSelf') dmg += e.attack
    }
    if (c.type === 'minion' && c.charge) dmg += c.attack ?? 0
  }
  return dmg
}

/** 斩杀搜索里只列「能打脸 / 能清掉挡路嘲讽」的动作,并按先打脸的顺序排 */
function lethalCandidates(s: GameState, side: Side): Action[] {
  const me = s.sides[side]
  const them = s.sides[foe(side)]
  const taunts = them.board.filter((m) => m.health > 0 && m.taunt)
  const out: Action[] = []
  for (const m of me.board) {
    if (m.health <= 0 || m.attacks <= 0) continue
    for (const t of attackTargets(s, side, m.uid)) {
      if (t.kind === 'hero') out.push({ kind: 'attack', uid: m.uid, target: t })
    }
  }
  for (const m of me.board) {
    if (m.health <= 0 || m.attacks <= 0) continue
    for (const t of attackTargets(s, side, m.uid)) {
      if (t.kind === 'minion' && taunts.some((x) => x.uid === t.uid)) out.push({ kind: 'attack', uid: m.uid, target: t })
    }
  }
  for (let h = 0; h < me.hand.length; h++) {
    if (!canPlayCard(s, side, h).ok) continue
    const c = card(me.hand[h])
    const e = c.type === 'spell' ? c.spell : c.battlecry
    if (e && e.kind === 'damage') {
      out.push({ kind: 'play', hand: h, target: { kind: 'hero', side: foe(side) } })
      for (const t of playTargets(s, side, h)) {
        if (t.kind === 'minion' && taunts.some((x) => x.uid === t.uid)) out.push({ kind: 'play', hand: h, target: t })
      }
    } else if (e && e.kind === 'heroDamage') {
      out.push({ kind: 'play', hand: h, target: null })
    } else if (e && e.kind === 'aoe') {
      // 群体伤害本身不打脸,但能清掉挡路的嘲讽
      if (taunts.length > 0) out.push({ kind: 'play', hand: h, target: null })
    } else if (c.type === 'minion' && c.charge) {
      out.push({ kind: 'play', hand: h, target: null })
    }
  }
  return out.slice(0, 14)
}

function searchLethal(s: GameState, side: Side, depth: number): Action[] | null {
  if (s.over) return s.over.winner === side ? [] : null
  const them = s.sides[foe(side)]
  if (them.hp <= 0) return []
  if (depth <= 0) return null
  // 现在手里所有能打出去的东西加起来都打不死:剪掉
  if (them.hp > maxBurst(s, side)) return null
  for (const a of lethalCandidates(s, side)) {
    const r = applyAction(s, a)
    if (!r.ok) continue
    const rest = searchLethal(r.state, side, depth - 1)
    if (rest) return [a, ...rest]
  }
  return null
}

/** 找到这回合就能赢的第一步;找不到返回 null */
export function findLethal(s: GameState, side: Side, level: Level): Action | null {
  const depth = level === 'hard' ? 12 : 1
  const seq = searchLethal(s, side, depth)
  return seq && seq.length > 0 ? seq[0] : null
}

/** 电脑的下一步。对局结束或没动作可做时返回结束回合 */
export function aiNext(s: GameState, level: Level): Action {
  if (s.over) return { kind: 'end' }
  const side = s.active
  const legal = legalActions(s)
  const options = legal.filter((a): a is Exclude<Action, { kind: 'end' }> => a.kind !== 'end')
  if (options.length === 0) return { kind: 'end' }
  const lethal = findLethal(s, side, level)
  if (lethal && lethal.kind !== 'end') return lethal
  const w = level === 'hard' ? HARD : NORMAL
  const base = evaluate(s, side, w)
  let best: Action | null = null
  let bestGain = 0
  for (const a of options) {
    const r = applyAction(s, a)
    if (!r.ok) continue
    const gain = evaluate(r.state, side, w) - base
    if (gain > bestGain) {
      bestGain = gain
      best = a
    }
  }
  const threshold = level === 'hard' ? 0.6 : 0.45
  if (best && bestGain > threshold) return best
  return { kind: 'end' }
}

/** 动作里选的目标(给测试和调试打印用) */
export function actionTarget(a: Action): TargetRef | null {
  return a.kind === 'play' ? a.target : a.kind === 'attack' ? a.target : null
}
