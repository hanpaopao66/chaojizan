// 一回合的模拟:玩家、守卫、子弹、炸弹、回合状态机。
//
// 这里是整个游戏的「引擎」:advance(round, dt, input) 是纯函数 —— 同样的局面、同样的输入、同样的随机数,
// 结果永远一样。界面只负责把摇杆/键盘的输入喂进来,再把 round 画出来;测试里可以直接推演几百帧,
// 检查守卫有没有穿墙、炸弹计时的先后顺序对不对。
import {
  GameMap, TILE, Vec, angleDiff, angleTo, dist, lineOfSight, moveCircle, siteAt,
} from './map'
import { NavGrid, navFromMap, routeBetween } from './nav'
import {
  Difficulty, GunState, GuardSkill, RIFLE, Rifle, ShotTarget, SKILLS, aimWithSpread, canFire, fireGun, hitscan,
  newGun, reloading, spreadOf, startReload, tickGun,
} from './combat'
import { BombInfo, GuardBrain, Noise, decideGuard, guardSeesPlayer, newBrain } from './ai'
import type { Fx, Side, Tracer } from './fx'
import { addFlash, addSpark, addTracer, burstFx, decayFx } from './fx'

export type { Fx, FxKind, Side, Tracer } from './fx'

// ---------------------------------------------------------------- 规则常数

/** 开场冻结:双方都动不了,给玩家看一眼地图 */
export const FREEZE_TIME = 2
/** 一个回合多久(秒) */
export const ROUND_TIME = 75
/** 按住安放炸弹要多久(秒) */
export const PLANT_TIME = 2.5
/** 炸弹安放后多久爆炸(秒) */
export const BOMB_TIME = 30
/** 守卫按住拆弹要多久(秒) */
export const DEFUSE_TIME = 5
/** 先赢几个回合获胜(三局两胜) */
export const SCORE_TO_WIN = 2
export const PLAYER_HP = 100
export const GUARD_HP = 100
export const PLAYER_RADIUS = 8
export const GUARD_RADIUS = 8
/** 4 格/秒 */
export const PLAYER_SPEED = TILE * 4
/** 玩家能「看见」守卫的距离(超出就算在暗处,不画出来) */
export const PLAYER_VIEW_RANGE = TILE * 20
/** 守卫听枪声的距离 */
export const HEAR_RANGE = TILE * 14
/** 守卫离炸弹多近才能拆 */
export const DEFUSE_RANGE = TILE * 1.35
/** 单帧最大步长:切后台回来、掉帧时也不会一步穿墙 */
export const MAX_DT = 0.05


export type RoundPhase = 'freeze' | 'live' | 'over'
export type OverReason = 'exploded' | 'defused' | 'playerKilled' | 'timeout'

export interface BombState {
  state: 'carried' | 'planting' | 'planted' | 'defused' | 'exploded'
  pos: Vec | null
  /** 安放进度 0..1 */
  plant: number
  /** 爆炸倒计时(秒) */
  timer: number
  /** 拆除进度 0..1 */
  defuse: number
  /** 谁在拆(-1 = 没人) */
  defuserId: number
  /** 下一次「滴」的间隔 */
  beepIn: number
}

export interface PlayerState {
  pos: Vec
  angle: number
  hp: number
  alive: boolean
  gun: GunState
  rifle: Rifle
  hitFlash: number
  /** 本回合击杀 / 命中 / 开枪 */
  kills: number
  hits: number
  shots: number
  /** 当前站的炸弹点 */
  site: 'A' | 'B' | null
}

export interface GuardState {
  id: number
  pos: Vec
  angle: number
  hp: number
  alive: boolean
  gun: GunState
  skill: GuardSkill
  brain: GuardBrain
  /** 寻路:要走的格子中心点、走到第几个 */
  path: Vec[]
  pathAt: number
  /** 上次寻路的目标;目标挪了才重新算 */
  pathGoal: Vec | null
  /** 连射:这一组还剩几发,下一组什么时候开始 */
  burstLeft: number
  burstAt: number
  /** 这一帧是不是在拆弹(引擎里定的,AI 只表达意愿) */
  defusing: boolean
  hitFlash: number
  /** 最近被谁打、什么时候(挨打了一定去查) */
  hurtAt: number
  hurtFrom: Vec | null
}

export interface Round {
  map: GameMap
  nav: NavGrid
  difficulty: Difficulty
  phase: RoundPhase
  /** 当前阶段剩余秒数:冻结倒计时 / 回合剩余 */
  clock: number
  /** 回合内已经过的秒数 */
  elapsed: number
  player: PlayerState
  guards: GuardState[]
  bomb: BombState
  tracers: Tracer[]
  fx: Fx[]
  noises: Noise[]
  rng: number
  /** 本回合安放成功几次 */
  plants: number
  over: { side: Side; reason: OverReason } | null
}

export interface PlayerInput {
  moveX: number
  moveY: number
  /** 瞄准角度;null = 保持当前朝向 */
  aim: number | null
  fire: boolean
  reload: boolean
  /** 按住安放(E 键 / 屏幕上的安放按钮) */
  interact: boolean
}

export type GameEvent =
  | { type: 'live' }
  | { type: 'shot'; team: Side; angle: number }
  | { type: 'hit'; target: 'player' | 'guard'; id: number; damage: number }
  | { type: 'kill'; guard: number }
  | { type: 'death' }
  | { type: 'reload'; team: Side }
  | { type: 'empty' }
  | { type: 'planting' }
  | { type: 'plant'; pos: Vec }
  | { type: 'defusing' }
  | { type: 'defused' }
  | { type: 'explode'; pos: Vec }
  | { type: 'beep' }
  | { type: 'roundOver'; side: Side; reason: OverReason }

export interface RoundStep {
  round: Round
  events: GameEvent[]
}

// ---------------------------------------------------------------- 开一局

export interface MatchStats {
  kills: number
  shots: number
  hits: number
  plants: number
  seconds: number
}
export interface RoundSummary {
  side: Side
  reason: OverReason
  kills: number
  seconds: number
  planted: boolean
}
export interface MatchState {
  difficulty: Difficulty
  /** 第几回合(从 1 开始) */
  round: number
  scorePlayer: number
  scoreGuard: number
  seed: number
  over: 'win' | 'loss' | null
  stats: MatchStats
  lastRound: RoundSummary | null
}

export function newMatch(difficulty: Difficulty, seed: number): MatchState {
  return {
    difficulty,
    round: 1,
    scorePlayer: 0,
    scoreGuard: 0,
    seed: seed >>> 0,
    over: null,
    stats: { kills: 0, shots: 0, hits: 0, plants: 0, seconds: 0 },
    lastRound: null,
  }
}

/** 不同回合用不同的随机数种子,但整场可复现 */
function roundSeed(seed: number, round: number): number {
  let s = seed >>> 0
  for (let i = 0; i < round; i++) s = (Math.imul(s ^ 0x9e3779b9, 1664525) + 1013904223) >>> 0
  return s
}

function newBomb(): BombState {
  return { state: 'carried', pos: null, plant: 0, timer: BOMB_TIME, defuse: 0, defuserId: -1, beepIn: 1 }
}

function newPlayer(map: GameMap): PlayerState {
  return {
    pos: { ...map.playerSpawn },
    angle: 0,
    hp: PLAYER_HP,
    alive: true,
    gun: newGun(RIFLE),
    rifle: RIFLE,
    hitFlash: 0,
    kills: 0,
    hits: 0,
    shots: 0,
    site: null,
  }
}

function newGuard(map: GameMap, id: number, skill: GuardSkill, seed: number): GuardState {
  const spawn = { ...map.guardSpawns[id] }
  return {
    id,
    pos: spawn,
    // 守卫守点时大致朝左(玩家来的方向)
    angle: Math.PI,
    hp: GUARD_HP,
    alive: true,
    gun: newGun(RIFLE),
    skill,
    brain: newBrain(spawn, Math.PI, seed, 0),
    path: [],
    pathAt: 0,
    pathGoal: null,
    burstLeft: 0,
    burstAt: 0,
    defusing: false,
    hitFlash: 0,
    hurtAt: -99,
    hurtFrom: null,
  }
}

export function newRound(match: MatchState, map: GameMap): Round {
  const seed = roundSeed(match.seed, match.round)
  const skill = SKILLS[match.difficulty]
  return {
    map,
    nav: navFromMap(map),
    difficulty: match.difficulty,
    phase: 'freeze',
    clock: FREEZE_TIME,
    elapsed: 0,
    player: newPlayer(map),
    guards: [0, 1, 2].map((id) => newGuard(map, id, skill, (seed + id * 7919) >>> 0)),
    bomb: newBomb(),
    tracers: [],
    fx: [],
    noises: [],
    rng: seed || 1,
    plants: 0,
    over: null,
  }
}

/**
 * 现在能不能安放炸弹:活着、在回合里、站在 A/B 炸弹点上、炸弹还没安。
 * 界面(手机上的「安放」按钮)和引擎(按住 2.5 秒的进度)共用这一个判断,免得两边说不一样。
 */
export function canPlant(round: Round): boolean {
  return round.phase === 'live'
    && round.player.alive
    && round.player.site !== null
    && (round.bomb.state === 'carried' || round.bomb.state === 'planting')
}

// ---------------------------------------------------------------- 每帧推进

/** 推一帧。dt 会被夹到 MAX_DT,暂停/切后台时不调用就行 */
export function advance(round: Round, dt: number, input: PlayerInput): RoundStep {
  const events: GameEvent[] = []
  const step = Math.min(Math.max(dt, 0), MAX_DT)
  const r = cloneRound(round)
  r.elapsed += step
  decayStep(r, step)

  if (r.phase === 'freeze') {
    r.clock -= step
    if (r.clock <= 0) {
      r.phase = 'live'
      r.clock = ROUND_TIME
      events.push({ type: 'live' })
    }
    return { round: r, events }
  }
  if (r.phase !== 'live') return { round: r, events }

  // 炸弹倒计时
  if (r.bomb.state === 'planted') {
    r.bomb.timer -= step
    r.bomb.beepIn -= step
    if (r.bomb.beepIn <= 0) {
      events.push({ type: 'beep' })
      // 越接近爆炸滴得越快
      r.bomb.beepIn = Math.max(0.22, Math.min(1.1, r.bomb.timer / 22))
    }
    if (r.bomb.timer <= 0) {
      r.bomb.timer = 0
      r.bomb.state = 'exploded'
      r.bomb.pos = r.bomb.pos || { ...r.player.pos }
      events.push({ type: 'explode', pos: r.bomb.pos })
      burstFx(r, r.bomb.pos, 'spark', 18, 'player')
      finish(r, 'player', 'exploded', events)
      return { round: r, events }
    }
  }

  stepPlayer(r, step, input, events)
  stepGuards(r, step, events)
  stepBombDefuse(r, step, events)

  // 回合计时:炸弹已经安放就不再看回合倒计时
  if (r.bomb.state !== 'planted' && r.bomb.state !== 'defused' && r.bomb.state !== 'exploded') {
    r.clock -= step
    if (r.clock <= 0) {
      r.clock = 0
      finish(r, 'guard', 'timeout', events)
    }
  }

  if (r.player.hp <= 0 && r.player.alive) {
    r.player.alive = false
    r.player.hp = 0
    events.push({ type: 'death' })
    finish(r, 'guard', 'playerKilled', events)
  }
  return { round: r, events }
}

function cloneRound(round: Round): Round {
  return {
    ...round,
    player: { ...round.player, pos: { ...round.player.pos }, gun: { ...round.player.gun } },
    guards: round.guards.map((g) => ({
      ...g,
      pos: { ...g.pos },
      gun: { ...g.gun },
      brain: { ...g.brain, home: g.brain.home, target: g.brain.target, lastSeen: g.brain.lastSeen, heardPos: g.brain.heardPos },
      path: g.path,
      hurtFrom: g.hurtFrom,
    })),
    bomb: { ...round.bomb, pos: round.bomb.pos },
    tracers: round.tracers,
    fx: round.fx,
    noises: round.noises,
  }
}

function finish(r: Round, side: Side, reason: OverReason, events: GameEvent[]): void {
  if (r.phase === 'over') return
  r.phase = 'over'
  r.over = { side, reason }
  events.push({ type: 'roundOver', side, reason })
}

// ---------------------------------------------------------------- 玩家

function stepPlayer(r: Round, dt: number, input: PlayerInput, events: GameEvent[]): void {
  const p = r.player
  p.hitFlash = Math.max(0, p.hitFlash - dt)
  if (!p.alive) return

  // 移动:斜着走归一化,不会比直着快
  let mx = input.moveX
  let my = input.moveY
  const len = Math.hypot(mx, my)
  if (len > 1) {
    mx /= len
    my /= len
  }
  p.pos = moveCircle(r.map, p.pos, mx * PLAYER_SPEED * dt, my * PLAYER_SPEED * dt, PLAYER_RADIUS)
  p.site = siteAt(r.map, p.pos)
  if (input.aim !== null) p.angle = input.aim

  p.gun = tickGun(p.gun, dt, p.rifle)
  if (input.reload) {
    const g = startReload(p.gun, p.rifle)
    if (g !== p.gun) {
      p.gun = g
      events.push({ type: 'reload', team: 'player' })
    }
  }

  // 安放:要在炸弹点上按住 2.5 秒;松手或者走开就从头来
  if (input.interact && canPlant(r)) {
    if (r.bomb.state === 'carried') {
      r.bomb.state = 'planting'
      r.bomb.plant = 0
      events.push({ type: 'planting' })
    }
    r.bomb.plant = Math.min(1, r.bomb.plant + dt / PLANT_TIME)
    if (r.bomb.plant >= 1) {
      r.bomb.state = 'planted'
      r.bomb.pos = { ...p.pos }
      r.bomb.timer = BOMB_TIME
      r.bomb.beepIn = 0.9
      r.bomb.defuse = 0
      r.bomb.defuserId = -1
      r.plants++
      events.push({ type: 'plant', pos: r.bomb.pos })
      r.noises.push({ pos: { ...r.bomb.pos }, kind: 'plant', team: 'player', at: r.elapsed })
    }
  } else if (r.bomb.state === 'planting') {
    r.bomb.state = 'carried'
    r.bomb.plant = 0
  }

  // 开火:安放的时候不能开枪
  if (input.fire && r.bomb.state !== 'planting') firePlayer(r, events)
}

function firePlayer(r: Round, events: GameEvent[]): void {
  const p = r.player
  if (!canFire(p.gun)) {
    if (p.gun.mag === 0 && !reloading(p.gun) && p.gun.reserve > 0) {
      p.gun = startReload(p.gun, p.rifle)
      events.push({ type: 'empty' })
      events.push({ type: 'reload', team: 'player' })
    }
    return
  }
  const aimed = aimWithSpread(p.angle, spreadOf(p.gun, p.rifle), r.rng)
  r.rng = aimed.rng
  const targets: ShotTarget[] = r.guards
    .filter((g) => g.alive)
    .map((g) => ({ id: g.id, pos: g.pos, radius: GUARD_RADIUS }))
  const hit = hitscan(r.map, p.pos, aimed.angle, targets, p.rifle.range)
  p.gun = fireGun(p.gun, p.rifle)
  p.shots++
  addTracer(r, p.pos, hit.point, 'player')
  addFlash(r, p.pos, aimed.angle, 'player')
  events.push({ type: 'shot', team: 'player', angle: aimed.angle })
  r.noises.push({ pos: { ...p.pos }, kind: 'shot', team: 'player', at: r.elapsed })
  if (hit.kind === 'target') {
    const guard = r.guards[hit.id]
    guard.hp -= p.rifle.damage
    guard.hitFlash = 0.25
    guard.hurtAt = r.elapsed
    guard.hurtFrom = { ...p.pos }
    p.hits++
    addSpark(r, hit.point, 'spark')
    events.push({ type: 'hit', target: 'guard', id: hit.id, damage: p.rifle.damage })
    if (guard.hp <= 0) {
      guard.hp = 0
      guard.alive = false
      p.kills++
      addSpark(r, hit.point, 'smoke')
      events.push({ type: 'kill', guard: guard.id })
    }
  } else if (hit.kind === 'wall') {
    addSpark(r, hit.point, 'spark')
  }
}

// ---------------------------------------------------------------- 守卫

function stepGuards(r: Round, dt: number, events: GameEvent[]): void {
  const now = r.elapsed
  for (const g of r.guards) {
    if (!g.alive) continue
    g.hitFlash = Math.max(0, g.hitFlash - dt)
    g.gun = tickGun(g.gun, dt, RIFLE)
    // 空仓自动换弹(守卫没有「忘了换弹」这一说)
    if (g.gun.mag === 0 && !reloading(g.gun)) g.gun = startReload(g.gun, RIFLE)

    const sees = r.player.alive && guardSeesPlayer(r.map, g.pos, g.angle, g.skill, r.player.pos)
    const heard = latestHeard(r, g)
    const decision = decideGuard(g.brain, {
      now,
      pos: g.pos,
      angle: g.angle,
      seesPlayer: sees,
      playerPos: r.player.pos,
      heard,
      bomb: bombInfo(r.bomb),
      skill: g.skill,
    }, r.rng)
    r.rng = decision.rng
    g.brain = decision.brain
    const intent = decision.intent

    moveGuard(r, g, intent.moveTo, dt)
    g.angle = turnToward(g.angle, intent.lookAngle, g.skill.turnSpeed * dt)

    if (intent.fire && sees && canFire(g.gun)) {
      const off = Math.abs(angleDiff(g.angle, angleTo(g.pos, r.player.pos)))
      if (off < 0.16) fireGuard(r, g, events)
    }
    g.defusing = false
  }
}

function moveGuard(r: Round, g: GuardState, goal: Vec | null, dt: number): void {
  if (!goal) {
    g.path = []
    g.pathAt = 0
    g.pathGoal = null
    return
  }
  // 目标挪了(比如追着玩家)才重新寻路,不然每帧算 A* 太浪费
  if (!g.pathGoal || dist(g.pathGoal, goal) > TILE * 0.75) {
    g.path = routeBetween(r.nav, g.pos, goal)
    g.pathGoal = { ...goal }
    g.pathAt = 0
  }
  if (!g.path.length) return
  // 已经站在的点不用再走
  while (g.pathAt < g.path.length - 1 && dist(g.pos, g.path[g.pathAt]) < TILE * 0.45) g.pathAt++
  const wp = g.path[g.pathAt]
  if (dist(g.pos, wp) < 1) return
  const dx = wp.x - g.pos.x
  const dy = wp.y - g.pos.y
  const d = Math.hypot(dx, dy)
  if (d === 0) return
  const stepLen = Math.min(d, g.skill.speed * dt)
  g.pos = moveCircle(r.map, g.pos, (dx / d) * stepLen, (dy / d) * stepLen, GUARD_RADIUS)
}

function fireGuard(r: Round, g: GuardState, events: GameEvent[]): void {
  const now = r.elapsed
  if (now < g.burstAt) return
  if (g.burstLeft <= 0) g.burstLeft = g.skill.burst
  const aimAngle = angleTo(g.pos, r.player.pos)
  const spread = spreadOf(g.gun, RIFLE) + g.skill.aimError
  const aimed = aimWithSpread(aimAngle, spread, r.rng)
  r.rng = aimed.rng
  const hit = hitscan(r.map, g.pos, aimed.angle, [{ id: 0, pos: r.player.pos, radius: PLAYER_RADIUS }], RIFLE.range)
  g.gun = fireGun(g.gun, RIFLE)
  g.burstLeft--
  if (g.burstLeft <= 0) g.burstAt = now + g.skill.pause
  addTracer(r, g.pos, hit.point, 'guard')
  addFlash(r, g.pos, aimed.angle, 'guard')
  events.push({ type: 'shot', team: 'guard', angle: aimed.angle })
  if (hit.kind === 'target') {
    r.player.hp -= RIFLE.damage
    r.player.hitFlash = 0.3
    addSpark(r, hit.point, 'spark')
    events.push({ type: 'hit', target: 'player', id: 0, damage: RIFLE.damage })
  } else if (hit.kind === 'wall') {
    addSpark(r, hit.point, 'spark')
  }
}

function latestHeard(r: Round, g: GuardState): Noise | null {
  let best: Noise | null = null
  // 刚挨了打:一定知道子弹从哪来,比听枪声还准
  if (r.elapsed - g.hurtAt < 5 && g.hurtFrom) {
    best = { pos: g.hurtFrom, kind: 'shot', team: 'player', at: g.hurtAt }
  }
  for (const n of r.noises) {
    if (n.team === 'guard') continue
    if (r.elapsed - n.at > 6) continue
    const range = n.kind === 'plant' ? Infinity : HEAR_RANGE
    if (dist(g.pos, n.pos) > range) continue
    if (!best || n.at > best.at) best = n
  }
  return best
}

function bombInfo(bomb: BombState): BombInfo {
  return { planted: bomb.state === 'planted', pos: bomb.pos, plantedFor: BOMB_TIME - bomb.timer }
}

/** 拆弹:只有离炸弹最近、正在拆的那名守卫能推进进度;没人拆就快速回退 */
function stepBombDefuse(r: Round, dt: number, events: GameEvent[]): void {
  const bomb = r.bomb
  if (bomb.state !== 'planted' || !bomb.pos) return
  let best: GuardState | null = null
  let bestD = DEFUSE_RANGE
  for (const g of r.guards) {
    if (!g.alive) continue
    const d = dist(g.pos, bomb.pos)
    const wants = g.brain.mode === 'defuse'
    g.defusing = wants && d <= DEFUSE_RANGE
    if (g.defusing && d < bestD) {
      best = g
      bestD = d
    }
  }
  const wasDefusing = bomb.defuse > 0
  if (best) {
    bomb.defuserId = best.id
    bomb.defuse = Math.min(1, bomb.defuse + dt / DEFUSE_TIME)
    if (!wasDefusing) events.push({ type: 'defusing' })
    if (bomb.defuse >= 1) {
      bomb.state = 'defused'
      events.push({ type: 'defused' })
      finish(r, 'guard', 'defused', events)
    }
  } else {
    bomb.defuserId = -1
    bomb.defuse = Math.max(0, bomb.defuse - dt * 2)
  }
}

function turnToward(from: number, to: number, maxStep: number): number {
  const diff = angleDiff(from, to)
  if (Math.abs(diff) <= maxStep) return to
  return from + Math.sign(diff) * maxStep
}

// ---------------------------------------------------------------- 每帧特效推进

/** 曳光/火花按时间衰减;超过 8 秒的旧声音也清掉(守卫只关心最近几秒) */
function decayStep(r: Round, dt: number): void {
  decayFx(r, dt)
  r.noises = r.noises.filter((n) => r.elapsed - n.at < 8)
}

// ---------------------------------------------------------------- 胜负与统计

/** 回合结束后记账:比分、累计数据、整场是否结束 */
export function finishRound(match: MatchState, round: Round): MatchState {
  if (!round.over || match.over) return match
  const scorePlayer = match.scorePlayer + (round.over.side === 'player' ? 1 : 0)
  const scoreGuard = match.scoreGuard + (round.over.side === 'guard' ? 1 : 0)
  const stats: MatchStats = {
    kills: match.stats.kills + round.player.kills,
    shots: match.stats.shots + round.player.shots,
    hits: match.stats.hits + round.player.hits,
    plants: match.stats.plants + round.plants,
    seconds: match.stats.seconds + round.elapsed,
  }
  const over = scorePlayer >= SCORE_TO_WIN ? 'win' as const : scoreGuard >= SCORE_TO_WIN ? 'loss' as const : null
  return {
    ...match,
    scorePlayer,
    scoreGuard,
    stats,
    over,
    lastRound: {
      side: round.over.side,
      reason: round.over.reason,
      kills: round.player.kills,
      seconds: round.elapsed,
      planted: round.plants > 0,
    },
  }
}

/** 下一回合(比分先记过) */
export function nextRound(match: MatchState): MatchState {
  return { ...match, round: match.round + 1 }
}

/** 玩家看不看得见某个守卫(渲染层用;超出视距或者被墙挡住就不画) */
export function playerSeesGuard(map: GameMap, playerPos: Vec, guardPos: Vec): boolean {
  if (dist(playerPos, guardPos) > PLAYER_VIEW_RANGE) return false
  return lineOfSight(map, playerPos, guardPos)
}

/** 命中率(0..1;没开枪是 0) */
export function accuracyOf(stats: MatchStats): number {
  return stats.shots === 0 ? 0 : stats.hits / stats.shots
}

