// 电脑怎么出牌。和界面无关;只在 battle.ts 的 step 里、对工作副本调用(会改副本里的电脑记忆和随机数种子)。
//
// 每隔 think 秒想一次,顺序是:
// 1. 守:哪一路敌人压过来了(按离自己塔的远近加权),过 react 秒还没解决就挑一张克制的牌去守;
// 2. 法术:能一次烧到值回票价的一堆敌人、或者能救一波自己人,就放;
// 3. 攻:能量攒到 reserve(或者快满了)就挑一路进攻 —— 没人时先放坦克在后面,已经有人就补输出;
// skill 决定挑牌、挑落点有多准,剩下的随手出;Boss 攒够能量优先上。
import { rand } from '../../shared/src/rand'
import {
  AiParams, BASE_Y, CardDef, ENERGY_MAX, FIELD_H, LANE_X, Side, TOWER_Y, ZONE, card, statMul,
} from './data'
import { Battle, Cmd, Unit, clamp, dist, foe, fwd, hitsAir, laneTower, levelOf, placement, statsOf } from './field'

interface LaneInfo {
  threat: number
  mine: number
  /** 敌方最靠前的单位走到了多深(0 在对方大本营,1 在自己大本营) */
  front: number
  frontY: number
  air: number
  swarm: number
  tank: number
  ranged: number
  siege: number
}

function roll(n: Battle): number {
  const [r, s] = rand(n.seed)
  n.seed = s
  return r
}

/** 一只单位值多少:费用(按只分摊)× 剩余血量比例 */
export function worth(u: Unit): number {
  const c = card(u.card)
  return (c.cost / (c.unit?.count || 1)) * Math.max(0, u.hp / u.max)
}

/** 敌方单位 u 往 side 这边走了多深:0 在它自己的大本营,1 到了 side 的大本营 */
export function depth(u: Unit, side: Side): number {
  const from = BASE_Y[foe(side)]
  const to = BASE_Y[side]
  return clamp((u.y - from) / (to - from), 0, 1)
}

function lanesOf(n: Battle): number[] {
  return [0, 1, 2].filter((l) => n.cfg.closed.indexOf(l) < 0)
}

function survey(n: Battle, side: Side): LaneInfo[] {
  const info: LaneInfo[] = [0, 1, 2].map(() => ({ threat: 0, mine: 0, front: 0, frontY: TOWER_Y[foe(side)], air: 0, swarm: 0, tank: 0, ranged: 0, siege: 0 }))
  for (const u of n.units) {
    if (u.hp <= 0) continue
    const li = info[u.lane]
    const v = worth(u)
    if (u.side === side) {
      li.mine += v
      continue
    }
    let d = depth(u, side)
    // 正在打自己塔的(比如站在塔射程外的长颈鹿):不管站多远都是最要紧的
    const onTower = u.tgt > 0 && u.tgt < 100 && n.towers.some((t) => t.id === u.tgt && t.side === side)
    if (onTower) d = Math.max(d, 0.75)
    const w = d < 0.35 ? 0.3 : d < 0.5 ? 0.7 : d < 0.7 ? 1.2 : 1.6
    li.threat += v * w
    if (d > li.front) {
      li.front = d
      li.frontY = u.y
    }
    const st = statsOf(u.card)
    if (u.air) li.air += v
    if ((st.count || 1) > 1 || card(u.card).kind === 'building' && st.spawn) li.swarm += v
    if (u.max >= 1200) li.tank += v
    if (st.range >= 2) li.ranged += v
    if (st.siege) li.siege += v
  }
  return info
}

/** 这张牌对着这一路的敌人有多合适 */
function counterScore(n: Battle, side: Side, c: CardDef, li: LaneInfo): number {
  if (c.kind === 'spell') return -99 // 法术另算
  const st = c.unit!
  const mul = statMul(levelOf(n, side, c.id))
  const air = hitsAir(st)
  const ground = li.threat - li.air
  let s = 0
  // 全是天上的而这张打不到天上:基本没用
  if (li.air > 0) s += air ? li.air * 2 : -li.air * 1.2
  if (!air && ground <= 0.2 && li.air > 0) s -= 50
  if (st.splash) s += li.swarm * 1.4
  if ((st.count || 1) > 1) s -= li.swarm * 0.6
  const dps = (st.atk * mul) / st.rate
  s += (li.tank * dps) / 140
  if (st.speed >= 1.3 && !st.air) s += li.ranged * 0.8
  if (c.kind === 'building') s += li.siege * 2.2 + 0.3
  if (st.siege) s -= 3 // 拆塔的不会回头守
  s += ((st.hp * mul) / 1000) * 0.6
  s -= c.cost * 0.25
  return s
}

function affordable(n: Battle, side: Side): Array<{ slot: number; c: CardDef }> {
  const me = n.sides[side]
  const out: Array<{ slot: number; c: CardDef }> = []
  me.hand.forEach((id, slot) => {
    const c = card(id)
    if (c.cost <= me.energy + 1e-9) out.push({ slot, c })
  })
  return out
}

function cmdAt(n: Battle, side: Side, slot: number, x: number, y: number): Cmd | null {
  const id = n.sides[side].hand[slot]
  const p = placement(n, side, card(id), x, y)
  return p.ok ? { side, slot, card: id, x: p.x, y: p.y } : null
}

/** 在 side 自己半场、第 lane 路上,离自己塔 k 格(正数往前、负数往后)的 y */
function yNearTower(side: Side, k: number): number {
  const [lo, hi] = ZONE[side]
  return clamp(TOWER_Y[side] + fwd(side) * k, lo, hi)
}

export function think(n: Battle, side: Side): Cmd | null {
  const p = n.cfg.ai[side]
  const m = n.ai[side]
  if (!p || !m || n.over || n.t < m.next) return null
  m.next = n.t + p.think * (0.8 + 0.4 * roll(n))
  const info = survey(n, side)
  const lanes = lanesOf(n)
  const me = n.sides[side]

  // 1. 守
  let worst = -1
  let worstScore = 0
  for (const l of lanes) {
    const li = info[l]
    const danger = li.threat - li.mine * 0.9
    if (li.front >= 0.42 && danger > 0.8 && danger > worstScore) {
      worst = l
      worstScore = danger
    }
  }
  for (const l of lanes) if (l !== worst) m.alarm[l] = -1
  if (worst >= 0) {
    if (m.alarm[worst] < 0) m.alarm[worst] = n.t
    if (n.t - m.alarm[worst] >= p.react) {
      const c = defend(n, side, p, worst, info[worst])
      if (c) return c
    }
  }

  // 2. 法术
  const sp = spells(n, side, p)
  if (sp) return sp

  // 3. 攻(能量快满了也得出,不然白白浪费)。手里有 Boss 就攒够了再一起上
  const boss = me.hand.map((id) => card(id)).find((c) => c.boss)
  const reserve = boss ? Math.max(p.reserve, boss.cost) : p.reserve
  if (me.energy >= reserve || me.energy >= ENERGY_MAX - 0.4) return attack(n, side, p, info, lanes)
  return null
}

function defend(n: Battle, side: Side, p: AiParams, lane: number, li: LaneInfo): Cmd | null {
  const opts = affordable(n, side).filter((o) => o.c.kind !== 'spell')
  if (!opts.length) return null
  let pick = opts[0]
  if (roll(n) < p.skill) {
    let best = -Infinity
    for (const o of opts) {
      const s = counterScore(n, side, o.c, li)
      if (s > best) {
        best = s
        pick = o
      }
    }
    if (best < -10) return null // 手里没有对得上的,不白送
  } else {
    pick = opts[Math.floor(roll(n) * opts.length)]
  }
  const st = pick.c.unit!
  const x = LANE_X[lane] + (roll(n) - 0.5) * 0.5
  // 近战顶到敌人跟前(但不越过自己半场),远程站在塔边,建筑插在路当中
  let y: number
  if (pick.c.kind === 'building') y = yNearTower(side, 1.6)
  else if (st.range >= 2) y = yNearTower(side, -0.4)
  else {
    const toward = li.frontY - fwd(side) * 0.8
    const [lo, hi] = ZONE[side]
    y = clamp(toward, lo, hi)
    // 敌人还远:就在塔前面等着
    if (Math.abs(y - TOWER_Y[side]) > 3) y = yNearTower(side, 1.2)
  }
  return cmdAt(n, side, pick.slot, x, y)
}

function spells(n: Battle, side: Side, p: AiParams): Cmd | null {
  const opts = affordable(n, side).filter((o) => o.c.kind === 'spell')
  if (!opts.length || roll(n) > p.spell) return null
  const enemy = foe(side)
  for (const o of opts) {
    const sp = o.c.spell!
    let best = 0
    let at: [number, number] | null = null
    const pool = sp.damage || sp.freeze ? n.units.filter((u) => u.side === enemy && u.hp > 0)
      : n.units.filter((u) => u.side === side && u.hp > 0 && !u.building)
    for (const c of pool) {
      let v = 0
      for (const u of pool) {
        if (dist(u.x, u.y, c.x, c.y) > sp.radius) continue
        if (sp.damage) v += worth(u) * (u.hp <= sp.damage * statMul(levelOf(n, side, o.c.id)) ? 1.3 : 0.6)
        else if (sp.freeze) v += depth(u, side) > 0.6 ? worth(u) : worth(u) * 0.3
        else if (sp.heal) v += ((u.max - u.hp) / u.max) * card(u.card).cost
        else if (sp.rage) v += depth(u, enemy) > 0.6 ? worth(u) : 0
      }
      if (v > best) {
        best = v
        at = [c.x, c.y]
      }
    }
    const need = o.c.cost * (sp.damage ? 1.15 : 1.4) * (1.3 - p.skill * 0.4)
    if (at && best >= need) return cmdAt(n, side, o.slot, at[0], at[1])
  }
  return null
}

function attack(n: Battle, side: Side, p: AiParams, info: LaneInfo[], lanes: number[]): Cmd | null {
  const opts = affordable(n, side).filter((o) => o.c.kind === 'unit')
  if (!opts.length) {
    // 手里全是建筑和法术:能量满了就把建筑插在最危险的一路,不然等着
    const b = affordable(n, side).find((o) => o.c.kind === 'building')
    if (!b || n.sides[side].energy < ENERGY_MAX - 0.4) return null
    const lane = lanes.reduce((a, l) => (info[l].threat > info[a].threat ? l : a), lanes[0])
    return cmdAt(n, side, b.slot, LANE_X[lane], yNearTower(side, 1.4))
  }
  const m = n.ai[side]!
  const enemy = foe(side)
  let lane: number
  if (p.focus === 'one') lane = lanes.indexOf(m.lane) >= 0 ? m.lane : lanes[0]
  else if (p.focus === 'weak' && roll(n) < p.skill) {
    // 专挑对面最弱的一路:塔倒了的路(直通大本营)最优先,其次塔血最少的
    lane = lanes[0]
    let low = Infinity
    for (const l of lanes) {
      const t = laneTower(n, enemy, l)
      const hp = !t || !t.alive ? -1 : t.hp / t.max - info[l].mine * 0.03
      if (hp < low) {
        low = hp
        lane = l
      }
    }
  } else {
    // 轮着来;这一路已经有自己人在推就接着补
    const pushing = lanes.filter((l) => info[l].mine > 2)
    if (pushing.length && roll(n) < 0.6) lane = pushing[Math.floor(roll(n) * pushing.length)]
    else {
      const i = (lanes.indexOf(m.lane) + 1) % lanes.length
      lane = lanes[i < 0 ? 0 : i]
    }
  }
  m.lane = lane
  const li = info[lane]
  const front = li.mine < 1.5
  let pick = opts[0]
  if (roll(n) < p.skill) {
    let best = -Infinity
    for (const o of opts) {
      const st = o.c.unit!
      const mul = statMul(levelOf(n, side, o.c.id))
      let s = o.c.boss ? 100 : 0
      if (front) s += ((st.hp * mul) / 1000) * 1.5 + (st.siege ? 1.5 : 0) - (st.range >= 2 ? 1 : 0)
      else s += (st.range >= 2 ? 1.5 : 0) + ((st.atk * mul) / st.rate) / 80 + (st.heal ? 1.2 : 0)
      if (li.air > 0 && hitsAir(st)) s += 0.8
      s += roll(n) * 0.5
      if (s > best) {
        best = s
        pick = o
      }
    }
  } else {
    const boss = opts.find((o) => o.c.boss)
    pick = boss || opts[Math.floor(roll(n) * opts.length)]
  }
  const st = pick.c.unit!
  const x = LANE_X[lane] + (roll(n) - 0.5) * 0.6
  let y: number
  if (front || st.hp * statMul(levelOf(n, side, pick.c.id)) >= 1200) {
    // 坦克从塔后面出发,给后面补兵留时间
    y = yNearTower(side, -1.0)
  } else {
    // 跟在自己最靠前的那只后面
    let lead: Unit | null = null
    for (const u of n.units) {
      if (u.side !== side || u.lane !== lane || u.hp <= 0 || u.building) continue
      if (!lead || (u.y - lead.y) * fwd(side) > 0) lead = u
    }
    const [lo, hi] = ZONE[side]
    y = lead ? clamp(lead.y - fwd(side) * 1.2, lo, hi) : yNearTower(side, -0.5)
  }
  return cmdAt(n, side, pick.slot, x, clamp(y, 0.5, FIELD_H - 0.5))
}
