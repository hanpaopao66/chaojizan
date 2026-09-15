// 对局模拟:step(对局, 这一步的出牌) → 新的对局 + 这一步发生的事(给界面放动画和声音)。
//
// 纯函数:传进来的对局不改,返回的是新的一份;电脑怎么出牌也在这一步里算(ai.ts 的 think),
// 用的是状态里的随机数种子 —— 同一个种子、同一串玩家操作,结果永远一样,测试和存档都靠这一点。
//
// 规则(和界面上「关于」里写的一致):
// - 三路:单位只在自己那一路里打,推倒这一路对面的哨塔后,沿路走去打对面的大本营;
// - 哨塔只打自己这一路的敌人,大本营打射程里的所有敌人;
// - 能量随时间回复,击倒敌方单位返还它费用的 25%(一张卡出好几只的按只分摊);
// - 推倒大本营直接赢;时间到了比推倒的哨塔数,一样多就比剩下的塔血,再一样是平局;
// - 坚守关:时间到大本营还在就赢;速攻关:时间内推倒够数的塔才赢。
import { shuffle } from '../../shared/src/rand'
import { think } from './ai'
import {
  CardDef, ENERGY_MAX, ENERGY_REGEN, FIELD_H, FIELD_W, LANE_HALF, LANE_X, REFUND_RATE, ShotKind, Side, TOWER_Y,
  UnitStats, card, statMul,
} from './data'
import {
  Battle, BattleConfig, Cmd, DT, Over, SideState, Shot, Tower, Unit, baseOf, clamp, dist, foe, fwd, hitsAir, laneOpen,
  laneTower, levelOf, makeTowers, newStats, placement, standing, statsOf, towerWorth,
} from './field'

export type Ev =
  | { e: 'play'; side: Side; card: string; x: number; y: number; ids: number[] }
  | { e: 'swing'; id: number; to: number }
  | { e: 'shoot'; id: number; shot: number; kind: ShotKind }
  | { e: 'hit'; id: number; dmg: number; x: number; y: number; tower: boolean }
  | { e: 'die'; id: number; card: string; side: Side; x: number; y: number; air: boolean; expired: boolean }
  | { e: 'refund'; side: Side; amount: number; x: number; y: number }
  | { e: 'tower'; id: number; side: Side; lane: number; x: number; y: number }
  | { e: 'spell'; card: string; side: Side; x: number; y: number; r: number }
  | { e: 'pulse'; id: number; x: number; y: number; r: number; stun: boolean }
  | { e: 'spawn'; id: number; from: number }
  | { e: 'leap'; id: number }
  | { e: 'charge'; id: number }
  | { e: 'end'; winner: Side | -1; reason: Over['reason'] }

export interface StepResult {
  state: Battle
  events: Ev[]
}

/** 场上最多多少个单位(建筑算在内):再多就不再生了 —— 存档一个值上限 64 KB,也照顾手机的帧率 */
export const MAX_UNITS = 70
const SHOT_SPEED: Record<ShotKind, number> = { pellet: 8, bolt: 16, arrow: 11, none: 8 }
const AURA = 2.2
const r3 = (v: number) => Math.round(v * 1000) / 1000

// ---------------------------------------------------------------- 开局

export function newBattle(cfg: BattleConfig): Battle {
  let seed = cfg.seed >>> 0
  const sides = [0, 1].map((side) => {
    const deck = cfg.decks[side].cards
    let order: string[]
    ;[order, seed] = shuffle(deck, seed)
    // 电脑的 Boss 放在第一手:Boss 关一开局就能看到它什么时候来
    const boss = order.findIndex((id) => !!card(id).boss)
    if (side === 1 && boss >= 4) {
      const t = order[0]
      order[0] = order[boss]
      order[boss] = t
    }
    return { energy: cfg.startEnergy[side], hand: order.slice(0, 4), queue: order.slice(4) } as SideState
  }) as [SideState, SideState]
  return {
    v: 1, cfg, t: 0, seed, nextId: 100, sides, units: [], shots: [], towers: makeTowers(cfg),
    ai: [cfg.ai[0] ? { next: 1.2, alarm: [-1, -1, -1], lane: 1 } : null,
      cfg.ai[1] ? { next: 1.5, alarm: [-1, -1, -1], lane: 1 } : null],
    stats: [newStats(), newStats()], over: null,
  }
}

function cloneBattle(b: Battle): Battle {
  return {
    ...b,
    sides: [{ ...b.sides[0], hand: b.sides[0].hand.slice(), queue: b.sides[0].queue.slice() },
      { ...b.sides[1], hand: b.sides[1].hand.slice(), queue: b.sides[1].queue.slice() }],
    units: b.units.map((u) => ({ ...u })),
    shots: b.shots.map((s) => ({ ...s })),
    towers: b.towers.map((t) => ({ ...t })),
    ai: [b.ai[0] && { ...b.ai[0], alarm: b.ai[0].alarm.slice() }, b.ai[1] && { ...b.ai[1], alarm: b.ai[1].alarm.slice() }],
    stats: [{ ...b.stats[0] }, { ...b.stats[1] }],
    over: b.over && { ...b.over },
  }
}

// ---------------------------------------------------------------- 出牌

/** 这张牌现在能不能出(能量够不够、落点对不对)。界面拖牌时用它画绿色 / 红色的落点 */
export function canPlay(b: Battle, side: Side, slot: number, x: number, y: number):
  { ok: boolean; x: number; y: number; lane: number; why?: string } {
  const id = b.sides[side].hand[slot]
  if (!id || b.over) return { ok: false, x, y, lane: -1, why: '不能出牌' }
  const c = card(id)
  const p = placement(b, side, c, x, y)
  if (!p.ok) return p
  if (b.sides[side].energy + 1e-9 < c.cost) return { ...p, ok: false, why: '能量不够' }
  return p
}

/** 出一张牌(在 step 里的工作副本上改)。不合法的直接忽略 */
function play(n: Battle, cmd: Cmd, ev: Ev[]): boolean {
  const s = n.sides[cmd.side]
  if (s.hand[cmd.slot] !== cmd.card) return false
  const chk = canPlay(n, cmd.side, cmd.slot, cmd.x, cmd.y)
  if (!chk.ok) return false
  const c = card(cmd.card)
  s.energy -= c.cost
  // 出掉的牌排到队尾,排头的那张补进这个位置
  s.queue.push(cmd.card)
  s.hand[cmd.slot] = s.queue.shift() as string
  n.stats[cmd.side].played++
  const lvl = levelOf(n, cmd.side, cmd.card)
  if (c.kind === 'spell') {
    castSpell(n, cmd.side, c, lvl, chk.x, chk.y, ev)
    ev.push({ e: 'play', side: cmd.side, card: cmd.card, x: chk.x, y: chk.y, ids: [] })
    return true
  }
  const ids = deploy(n, cmd.card, cmd.side, chk.lane, chk.x, chk.y, lvl)
  ev.push({ e: 'play', side: cmd.side, card: cmd.card, x: chk.x, y: chk.y, ids })
  return true
}

/** 一只一只放到场上(小鸡仔一次四只,排成两排) */
function deploy(n: Battle, id: string, side: Side, lane: number, x: number, y: number, lvl: number): number[] {
  const st = statsOf(id)
  const count = st.count || 1
  const offs = count === 1 ? [[0, 0]] : [[-0.22, 0], [0.22, 0], [-0.22, 0.34], [0.22, 0.34], [0, 0.17]].slice(0, count)
  const ids: number[] = []
  for (const [dx, dy] of offs) {
    const u = addUnit(n, id, side, lane, x + dx, y - fwd(side) * dy, lvl)
    if (u) ids.push(u.id)
  }
  return ids
}

function addUnit(n: Battle, id: string, side: Side, lane: number, x: number, y: number, lvl: number): Unit | null {
  if (n.units.length >= MAX_UNITS) return null
  const st = statsOf(id)
  const hp = Math.round(st.hp * statMul(lvl))
  const cx = clamp(x, LANE_X[lane] - LANE_HALF, LANE_X[lane] + LANE_HALF)
  const cy = clamp(y, 0.3, FIELD_H - 0.3)
  const u: Unit = {
    id: n.nextId++, card: id, side, lane, x: cx, y: cy, px: cx, py: cy, ox: r3(cx - LANE_X[lane]),
    hp, max: hp, lvl, building: card(id).kind === 'building', air: !!st.air,
    cd: st.rate * 0.4, tgt: -1, run: 0, charged: false, leapAt: 0, leaping: false,
    slowT: 0, slowK: 0, frozenT: 0, stunT: 0, poisonT: 0, poisonD: 0, rageT: 0, healT: 0, healR: 0,
    life: st.life || 0, spawnT: st.spawn ? 1.2 : 0, pulseT: st.pulse ? st.pulse.every * 0.6 : 0, born: n.t,
  }
  n.units.push(u)
  return u
}

function castSpell(n: Battle, side: Side, c: CardDef, lvl: number, x: number, y: number, ev: Ev[]): void {
  const sp = c.spell!
  const mul = statMul(lvl)
  ev.push({ e: 'spell', card: c.id, side, x, y, r: sp.radius })
  const enemy = foe(side)
  for (const u of n.units) {
    if (u.hp <= 0 || dist(u.x, u.y, x, y) > sp.radius + unitR(u) * 0.5) continue
    if (u.side === enemy) {
      if (sp.damage) hurt(n, u, sp.damage * mul, side, ev)
      if (sp.freeze) u.frozenT = Math.max(u.frozenT, sp.freeze)
    } else if (!u.building) {
      if (sp.heal) {
        u.healT = 2
        u.healR = (sp.heal * mul) / 2
      }
      if (sp.rage) u.rageT = Math.max(u.rageT, sp.rage)
    }
  }
  for (const t of n.towers) {
    if (!t.alive || t.side !== enemy || dist(t.x, t.y, x, y) > sp.radius + t.radius) continue
    if (sp.damage) hurt(n, t, sp.damage * mul * (sp.towerPct ?? 1), side, ev)
    if (sp.freeze) t.frozenT = Math.max(t.frozenT, sp.freeze)
  }
}

// ---------------------------------------------------------------- 一步

/** 走一步(DT 秒)。cmds 是玩家这一步出的牌;电脑的牌在里面自己算 */
export function step(b: Battle, cmds: Cmd[] = []): StepResult {
  const n = cloneBattle(b)
  const ev: Ev[] = []
  if (n.over) return { state: n, events: ev }
  for (const u of n.units) {
    u.px = u.x
    u.py = u.y
  }
  for (const s of n.shots) {
    s.px = s.x
    s.py = s.y
  }
  for (const c of cmds) play(n, c, ev)
  for (const side of [0, 1] as Side[]) {
    if (!n.cfg.ai[side]) continue
    const c = think(n, side)
    if (c) play(n, c, ev)
  }
  for (const side of [0, 1] as Side[]) {
    const s = n.sides[side]
    s.energy = Math.min(ENERGY_MAX, s.energy + ENERGY_REGEN * n.cfg.regen[side] * DT)
  }
  statuses(n, ev)
  for (const u of n.units) if (u.hp > 0) act(n, u, ev)
  separate(n)
  for (const t of n.towers) if (t.alive) towerAct(n, t, ev)
  flyShots(n, ev)
  cleanup(n, ev)
  n.t = r3(n.t + DT)
  checkEnd(n, ev)
  return { state: n, events: ev }
}

/** 直接往场上放一只(测试里摆局面用;正常出牌走 step)。纯函数:返回新的一份 */
export function place(b: Battle, id: string, side: Side, lane: number, x: number, y: number, lvl = 1): Battle {
  const n = cloneBattle(b)
  addUnit(n, id, side, lane, x, y, lvl)
  return n
}

/** 连走 k 步(测试和电脑对电脑用) */
export function run(b: Battle, steps: number): Battle {
  let s = b
  for (let i = 0; i < steps && !s.over; i++) s = step(s).state
  return s
}

/** 认输(界面上的「放弃」) */
export function forfeit(b: Battle): Battle {
  if (b.over) return b
  const n = cloneBattle(b)
  n.over = { winner: 1, reason: 'quit', t: n.t }
  return n
}

// ---------------------------------------------------------------- 状态(中毒、回血、Boss 发作、建筑)

function statuses(n: Battle, ev: Ev[]): void {
  const add: Array<[string, Side, number, number, number, number, number]> = []
  for (const u of n.units) {
    if (u.hp <= 0) continue
    const st = statsOf(u.card)
    const mul = statMul(u.lvl)
    if (u.frozenT > 0) u.frozenT = r3(Math.max(0, u.frozenT - DT))
    if (u.stunT > 0) u.stunT = r3(Math.max(0, u.stunT - DT))
    if (u.rageT > 0) u.rageT = r3(Math.max(0, u.rageT - DT))
    if (u.slowT > 0) {
      u.slowT = r3(Math.max(0, u.slowT - DT))
      if (u.slowT === 0) u.slowK = 0
    }
    if (u.poisonT > 0) {
      u.poisonT = r3(Math.max(0, u.poisonT - DT))
      hurt(n, u, u.poisonD * DT, foe(u.side), ev, true)
    }
    if (u.healT > 0) {
      u.healT = r3(Math.max(0, u.healT - DT))
      u.hp = Math.min(u.max, u.hp + u.healR * DT)
    }
    if (st.regen) u.hp = Math.min(u.max, u.hp + st.regen * mul * DT)
    if (st.heal) {
      for (const o of n.units) {
        if (o.side !== u.side || o.building || o.hp <= 0 || o.hp >= o.max) continue
        if (dist(o.x, o.y, u.x, u.y) <= AURA) o.hp = Math.min(o.max, o.hp + st.heal * mul * DT)
      }
    }
    if (u.building) {
      u.life = r3(u.life - DT)
      if (st.spawn && u.life > 0) {
        u.spawnT = r3(u.spawnT - DT)
        if (u.spawnT <= 0) {
          u.spawnT = st.spawn.every
          add.push([st.spawn.card, u.side, u.lane, u.x, u.y + fwd(u.side) * (unitR(u) + 0.2), u.lvl, u.id])
        }
      }
    }
    if (st.pulse && u.frozenT <= 0 && u.stunT <= 0) {
      u.pulseT = r3(u.pulseT - DT)
      if (u.pulseT <= 0) {
        u.pulseT = st.pulse.every
        pulse(n, u, st, mul, ev)
      }
    }
  }
  for (const [id, side, lane, x, y, lvl, from] of add) {
    const u = addUnit(n, id, side, lane, x, y, lvl)
    if (u) ev.push({ e: 'spawn', id: u.id, from })
  }
}

function pulse(n: Battle, u: Unit, st: UnitStats, mul: number, ev: Ev[]): void {
  const p = st.pulse!
  ev.push({ e: 'pulse', id: u.id, x: u.x, y: u.y, r: p.radius, stun: !!p.stun })
  for (const o of n.units) {
    if (o.side === u.side || o.hp <= 0 || dist(o.x, o.y, u.x, u.y) > p.radius + unitR(o)) continue
    if (p.damage) hurt(n, o, p.damage * mul, u.side, ev)
    if (p.stun && !o.building) o.stunT = Math.max(o.stunT, p.stun)
  }
  if (p.damage) {
    for (const t of n.towers) {
      if (t.alive && t.side !== u.side && dist(t.x, t.y, u.x, u.y) <= p.radius + t.radius) hurt(n, t, p.damage * mul, u.side, ev)
    }
  }
}

// ---------------------------------------------------------------- 单位:找目标、走、打

export const unitR = (u: Unit): number => statsOf(u.card).radius

type Target = Unit | Tower
const isTower = (t: Target): t is Tower => (t as Unit).card === undefined

function find(n: Battle, id: number): Target | undefined {
  if (id < 0) return undefined
  if (id < 100) return n.towers.find((t) => t.id === id)
  return n.units.find((u) => u.id === id)
}

function radiusOf(t: Target): number {
  return isTower(t) ? t.radius : unitR(t)
}

/** 边到边的距离 */
function gap(u: Unit, t: Target): number {
  return dist(u.x, u.y, t.x, t.y) - unitR(u) - radiusOf(t)
}

function sight(st: UnitStats): number {
  return Math.max(4.0, st.range + 1.6)
}

/** u 能不能打 t */
function canHit(n: Battle, u: Unit, st: UnitStats, t: Target): boolean {
  if (isTower(t)) {
    if (!t.alive || t.side === u.side) return false
    if (t.lane === -1) return laneOpen(n, u.side, u.lane)
    return t.lane === u.lane
  }
  if (t.hp <= 0 || t.side === u.side || t.lane !== u.lane) return false
  if (t.air && !hitsAir(st)) return false
  if (st.siege && !t.building) return false
  return true
}

function acquire(n: Battle, u: Unit, st: UnitStats): Target | undefined {
  const reach = u.building ? st.range : sight(st)
  let best: Target | undefined
  let bd = Infinity
  const consider = (t: Target) => {
    if (!canHit(n, u, st, t)) return
    const g = gap(u, t)
    if (g > reach) return
    // 离得一样近时先打单位(建筑和塔不会跑)
    const d = g + (isTower(t) ? 0.05 : 0)
    if (d < bd) {
      bd = d
      best = t
    }
  }
  for (const o of n.units) consider(o)
  for (const t of n.towers) consider(t)
  return best
}

/** 没有目标时往哪儿走:这一路对面的哨塔还在就去塔下,倒了就经过塔的位置去大本营 */
function waypoint(n: Battle, u: Unit): [number, number] {
  const enemy = foe(u.side)
  const tw = laneTower(n, enemy, u.lane)
  const ty = TOWER_Y[enemy]
  const lx = LANE_X[u.lane] + u.ox
  if (tw && tw.alive) return [lx, ty]
  const passed = u.side === 0 ? u.y <= ty + 0.05 : u.y >= ty - 0.05
  if (!passed) return [lx, ty]
  const base = baseOf(n, enemy)
  return [base.x, base.y]
}

function act(n: Battle, u: Unit, ev: Ev[]): void {
  const st = statsOf(u.card)
  if (u.building && st.atk <= 0) return
  if (u.frozenT > 0 || u.stunT > 0) return
  const rage = u.rageT > 0 ? 1.4 : 1
  u.cd = Math.max(0, u.cd - DT * rage)
  let t = find(n, u.tgt)
  // 已经在打的目标:还能打、还看得见就接着打,不来回换
  if (!t || !canHit(n, u, st, t) || gap(u, t) > (u.building ? st.range : sight(st) + 1)) t = acquire(n, u, st)
  u.tgt = t ? t.id : -1
  if (u.building) {
    if (t && gap(u, t) <= st.range + 0.02 && u.cd <= 0) attack(n, u, st, t, ev)
    return
  }
  if (t) {
    const g = gap(u, t)
    if (g <= st.range + 0.02) {
      u.leaping = false
      if (!u.charged) u.run = 0
      if (u.cd <= 0) attack(n, u, st, t, ev)
      return
    }
    if (st.leap && !isTower(t) && !u.leaping && g <= 2.5 && n.t >= u.leapAt) {
      u.leaping = true
      u.charged = true
      u.leapAt = n.t + 4
      ev.push({ e: 'leap', id: u.id })
    }
    move(n, u, st, t.x, t.y, g - st.range, rage, ev)
    return
  }
  u.leaping = false
  const [wx, wy] = waypoint(n, u)
  move(n, u, st, wx, wy, dist(u.x, u.y, wx, wy), rage, ev)
}

function move(n: Battle, u: Unit, st: UnitStats, tx: number, ty: number, room: number, rage: number, ev: Ev[]): void {
  if (room <= 0) return
  let sp = st.speed * n.cfg.speed * (1 - u.slowK) * rage
  if (u.charged && st.charge) sp *= 2
  if (u.leaping) sp *= 4
  const d = dist(u.x, u.y, tx, ty)
  if (d < 1e-6) return
  const k = Math.min(sp * DT, room, d) / d
  const ox = u.x
  const oy = u.y
  u.x += (tx - u.x) * k
  u.y += (ty - u.y) * k
  keepInLane(u)
  const moved = dist(ox, oy, u.x, u.y)
  if (st.charge && !u.charged) {
    u.run += moved
    if (u.run >= 2) {
      u.charged = true
      ev.push({ e: 'charge', id: u.id })
    }
  }
}

/** 两排哨塔之间只能在自己那一路里走;过了塔那一排(去大本营)才能斜着走 */
function keepInLane(u: Unit): void {
  if (u.y > TOWER_Y[1] + 0.2 && u.y < TOWER_Y[0] - 0.2) {
    u.x = clamp(u.x, LANE_X[u.lane] - LANE_HALF, LANE_X[u.lane] + LANE_HALF)
  }
  u.x = clamp(u.x, 0.2, FIELD_W - 0.2)
  u.y = clamp(u.y, 0.2, FIELD_H - 0.2)
}

function attack(n: Battle, u: Unit, st: UnitStats, t: Target, ev: Ev[]): void {
  u.cd = st.rate
  let dmg = st.atk * statMul(u.lvl)
  if (u.charged) {
    dmg *= 2
    u.charged = false
    u.run = 0
  }
  if (st.shot && st.shot !== 'none') {
    const s: Shot = {
      id: n.nextId++, side: u.side, kind: st.shot, x: u.x, y: u.y, px: u.x, py: u.y, tgt: t.id, tx: t.x, ty: t.y,
      speed: SHOT_SPEED[st.shot], dmg, splash: st.splash || 0, hitsAir: hitsAir(st), slow: st.slow || 0,
      poison: (st.poison || 0) * statMul(u.lvl),
    }
    n.shots.push(s)
    ev.push({ e: 'shoot', id: u.id, shot: s.id, kind: s.kind })
    return
  }
  ev.push({ e: 'swing', id: u.id, to: t.id })
  strike(n, u.side, t, dmg, st, ev, u)
}

/** 一击落下:伤害、溅射、减速、中毒、击退、吸血 */
function strike(n: Battle, side: Side, t: Target, dmg: number, st: UnitStats, ev: Ev[], by?: Unit,
  fx?: { splash: number; hitsAir: boolean; slow: number; poison: number }): void {
  const splash = fx ? fx.splash : st.splash || 0
  const slow = fx ? fx.slow : st.slow || 0
  const poison = fx ? fx.poison : (st.poison || 0) * (by ? statMul(by.lvl) : 1)
  const air = fx ? fx.hitsAir : hitsAir(st)
  let dealt = hurt(n, t, dmg, side, ev)
  if (!isTower(t)) effects(t, slow, poison, by && st.knock ? st.knock : 0, side)
  if (splash > 0) {
    // 溅射不分路:按落点的距离算(两路隔着近 3 格,只有大本营跟前才会波及旁边那路)
    for (const o of n.units) {
      if (o === t || o.side === side || o.hp <= 0) continue
      if (o.air && !air) continue
      if (dist(o.x, o.y, t.x, t.y) > splash + unitR(o) * 0.5) continue
      dealt += hurt(n, o, dmg, side, ev)
      effects(o, slow, poison, 0, side)
    }
  }
  if (by && st.lifesteal) by.hp = Math.min(by.max, by.hp + dealt * st.lifesteal)
}

function effects(t: Unit, slow: number, poison: number, knock: number, side: Side): void {
  if (t.hp <= 0) return
  if (slow > 0) {
    t.slowT = 1.5
    t.slowK = Math.max(t.slowK, slow)
  }
  if (poison > 0) {
    t.poisonT = 4
    t.poisonD = Math.max(t.poisonD, poison)
  }
  if (knock > 0 && !t.building && !card(t.card).boss) {
    t.y = clamp(t.y + fwd(side) * knock, 0.2, FIELD_H - 0.2)
    keepInLane(t)
  }
}

/** 扣血。返回实际扣掉的(给吸血用) */
function hurt(n: Battle, t: Target, dmg: number, side: Side, ev: Ev[], quiet = false): number {
  if (isTower(t)) {
    if (!t.alive) return 0
    const d = Math.min(dmg, t.hp)
    t.hp -= d
    n.stats[side].towerDmg += d
    ev.push({ e: 'hit', id: t.id, dmg: d, x: t.x, y: t.y, tower: true })
    if (t.hp <= 0.0001) knockDown(n, t, ev)
    return d
  }
  if (t.hp <= 0) return 0
  const d = Math.min(dmg, t.hp)
  t.hp -= d
  if (!quiet) ev.push({ e: 'hit', id: t.id, dmg: d, x: t.x, y: t.y, tower: false })
  return d
}

function knockDown(n: Battle, t: Tower, ev: Ev[]): void {
  t.alive = false
  t.hp = 0
  const by = foe(t.side)
  if (t.lane === -1) n.stats[by].base = true
  else {
    n.stats[by].towers++
    n.stats[t.side].lost++
  }
  ev.push({ e: 'tower', id: t.id, side: t.side, lane: t.lane, x: t.x, y: t.y })
}

// ---------------------------------------------------------------- 挤开:同一路的地面单位不叠在一起

function separate(n: Battle): void {
  const us = n.units
  for (let i = 0; i < us.length; i++) {
    const a = us[i]
    if (a.hp <= 0) continue
    for (let j = i + 1; j < us.length; j++) {
      const b = us[j]
      if (b.hp <= 0 || a.lane !== b.lane || a.air !== b.air) continue
      if (a.building && b.building) continue
      const ra = unitR(a)
      const rb = unitR(b)
      const need = (ra + rb) * 0.85
      let dx = b.x - a.x
      let dy = b.y - a.y
      let d = Math.hypot(dx, dy)
      if (d >= need) continue
      if (d < 1e-4) {
        // 叠在同一点:按 id 往左右分开(确定的,不用随机数)
        dx = (a.id < b.id ? 1 : -1) * 0.01
        dy = 0
        d = 0.01
      }
      const push = (need - d) / d
      // 大的推小的:按半径分摊;建筑不动
      const wa = a.building ? 0 : b.building ? 1 : rb / (ra + rb)
      const wb = b.building ? 0 : a.building ? 1 : ra / (ra + rb)
      a.x -= dx * push * wa
      a.y -= dy * push * wa * 0.6
      b.x += dx * push * wb
      b.y += dy * push * wb * 0.6
      keepInLane(a)
      keepInLane(b)
    }
  }
}

// ---------------------------------------------------------------- 塔

function towerAct(n: Battle, t: Tower, ev: Ev[]): void {
  if (t.frozenT > 0) {
    t.frozenT = r3(Math.max(0, t.frozenT - DT))
    return
  }
  t.cd = Math.max(0, t.cd - DT)
  const ok = (u: Unit | undefined): u is Unit => !!u && u.hp > 0 && u.side !== t.side &&
    (t.lane === -1 || u.lane === t.lane) && dist(u.x, u.y, t.x, t.y) - unitR(u) - t.radius <= t.range
  let u = find(n, t.tgt) as Unit | undefined
  if (!ok(u)) {
    u = undefined
    let bd = Infinity
    for (const o of n.units) {
      if (!ok(o)) continue
      const d = dist(o.x, o.y, t.x, t.y)
      if (d < bd) {
        bd = d
        u = o
      }
    }
  }
  t.tgt = u ? u.id : -1
  if (!u || t.cd > 0) return
  t.cd = t.rate
  const s: Shot = {
    id: n.nextId++, side: t.side, kind: 'arrow', x: t.x, y: t.y - 0.6, px: t.x, py: t.y - 0.6, tgt: u.id, tx: u.x, ty: u.y,
    speed: SHOT_SPEED.arrow, dmg: t.atk, splash: 0, hitsAir: true, slow: 0, poison: 0,
  }
  n.shots.push(s)
  ev.push({ e: 'shoot', id: t.id, shot: s.id, kind: 'arrow' })
}

// ---------------------------------------------------------------- 弹道

function flyShots(n: Battle, ev: Ev[]): void {
  const keep: Shot[] = []
  for (const s of n.shots) {
    const t = find(n, s.tgt)
    const alive = !!t && (isTower(t) ? t.alive : t.hp > 0)
    if (t && alive) {
      s.tx = t.x
      s.ty = t.y
    }
    const d = dist(s.x, s.y, s.tx, s.ty)
    const stepLen = s.speed * DT
    if (d > stepLen + 0.15) {
      s.x += ((s.tx - s.x) / d) * stepLen
      s.y += ((s.ty - s.y) / d) * stepLen
      keep.push(s)
      continue
    }
    s.x = s.tx
    s.y = s.ty
    const fx = { splash: s.splash, hitsAir: s.hitsAir, slow: s.slow, poison: s.poison }
    if (t && alive) strike(n, s.side, t, s.dmg, NO_STATS, ev, undefined, fx)
    else if (s.splash > 0) {
      // 目标先没了:溅射照样在落点炸开
      for (const o of n.units) {
        if (o.side === s.side || o.hp <= 0 || (o.air && !s.hitsAir)) continue
        if (dist(o.x, o.y, s.x, s.y) <= s.splash + unitR(o) * 0.5) hurt(n, o, s.dmg, s.side, ev)
      }
    }
  }
  n.shots = keep
}

const NO_STATS: UnitStats = { hp: 1, atk: 0, rate: 1, range: 0, speed: 0, radius: 0 }

// ---------------------------------------------------------------- 结算这一步:倒下的、返还能量

function cleanup(n: Battle, ev: Ev[]): void {
  const keep: Unit[] = []
  for (const u of n.units) {
    const expired = u.building && u.life <= 0 && u.hp > 0
    if (u.hp > 0 && !expired) {
      keep.push(u)
      continue
    }
    ev.push({ e: 'die', id: u.id, card: u.card, side: u.side, x: u.x, y: u.y, air: u.air, expired })
    if (expired) continue
    const by = foe(u.side)
    const c = card(u.card)
    const worth = (c.cost / (c.unit?.count || 1)) * REFUND_RATE
    const s = n.sides[by]
    const got = Math.min(ENERGY_MAX, s.energy + worth) - s.energy
    s.energy += got
    n.stats[by].kills++
    n.stats[by].refund += got
    if (got > 0.001) ev.push({ e: 'refund', side: by, amount: got, x: u.x, y: u.y })
  }
  n.units = keep
}

// ---------------------------------------------------------------- 胜负与星级

function checkEnd(n: Battle, ev: Ev[]): void {
  if (n.over) return
  const cfg = n.cfg
  const b0 = baseOf(n, 0)
  const b1 = baseOf(n, 1)
  let over: Over | null = null
  if (!b1.alive) over = { winner: 0, reason: 'base', t: n.t }
  else if (!b0.alive) over = { winner: 1, reason: 'base', t: n.t }
  else if (cfg.objective === 'blitz' && downWorth(n, 1) >= cfg.target) over = { winner: 0, reason: 'blitz', t: n.t }
  else if (n.t >= cfg.duration - 1e-9) {
    if (cfg.objective === 'defend') over = { winner: 0, reason: 'defend', t: n.t }
    else if (cfg.objective === 'blitz') over = { winner: 1, reason: 'timeout', t: n.t }
    else {
      const a = n.stats[0].towers
      const b = n.stats[1].towers
      if (a !== b) over = { winner: a > b ? 0 : 1, reason: 'time', t: n.t }
      else {
        const sa = standing(n, 0)
        const sb = standing(n, 1)
        over = Math.abs(sa - sb) < 1e-6 ? { winner: -1, reason: 'draw', t: n.t } : { winner: sa > sb ? 0 : 1, reason: 'time', t: n.t }
      }
    }
  }
  if (over) {
    n.over = over
    n.shots = []
    ev.push({ e: 'end', winner: over.winner, reason: over.reason })
  }
}

/** side 这一边被推倒的塔一共算几座(速攻目标用:大本营算三座) */
export function downWorth(b: Battle, side: Side): number {
  let s = 0
  for (const t of b.towers) if (t.side === side && !t.alive) s += towerWorth(t)
  return s
}

/** 这一局拿了几颗星(没赢是 0) */
export function starsOf(b: Battle): number {
  if (!b.over || b.over.winner !== 0) return 0
  let k = 0
  for (const g of b.cfg.stars) if (goalMet(b, g)) k++
  return k
}

export function goalMet(b: Battle, g: BattleConfig['stars'][number]): boolean {
  if (!b.over || b.over.winner !== 0) return false
  switch (g.kind) {
    case 'win': return true
    case 'lost': return b.stats[0].lost <= g.n
    case 'time': return b.over.t <= g.n
    case 'kills': return b.stats[0].kills >= g.n
  }
  return false
}

// ---------------------------------------------------------------- 存档

/** 对局的存档:数字留三位小数(JSON 短一半,接着玩差这点看不出来) */
export function saveBattle(b: Battle): unknown {
  return JSON.parse(JSON.stringify(b, (_k, v) => (typeof v === 'number' && !Number.isInteger(v) ? r3(v) : v)))
}

const num = (v: unknown): v is number => typeof v === 'number' && isFinite(v)

/** 读对局存档;坏的、版本不对的返回 null(当作没有) */
export function loadBattle(raw: unknown): Battle | null {
  const b = raw as Battle
  if (!b || typeof b !== 'object' || b.v !== 1 || !b.cfg || !num(b.t) || !num(b.seed) || !num(b.nextId)) return null
  const cfg = b.cfg
  try {
    if (!Array.isArray(cfg.decks) || cfg.decks.length !== 2 || !Array.isArray(cfg.stars) || cfg.stars.length !== 3) return null
    for (const d of cfg.decks) {
      if (!Array.isArray(d.cards) || d.cards.length !== 8 || !d.levels || typeof d.levels !== 'object') return null
      d.cards.forEach((id) => card(id))
    }
    if (!Array.isArray(b.sides) || b.sides.length !== 2) return null
    for (const s of b.sides) {
      if (!num(s.energy) || !Array.isArray(s.hand) || s.hand.length !== 4 || !Array.isArray(s.queue) || s.queue.length !== 4) return null
      s.hand.concat(s.queue).forEach((id) => card(id))
    }
    if (!Array.isArray(b.units) || !Array.isArray(b.shots) || !Array.isArray(b.towers)) return null
    for (const u of b.units) {
      if (!num(u.x) || !num(u.y) || !num(u.hp) || !num(u.id) || [0, 1, 2].indexOf(u.lane) < 0) return null
      statsOf(u.card)
    }
    if (b.towers.some((t) => !num(t.hp) || !num(t.x) || !num(t.y))) return null
    if (b.units.length > MAX_UNITS + 10) return null
  } catch (_) {
    return null
  }
  return b
}

export { standing }
export type { Battle, BattleConfig, Cmd }
