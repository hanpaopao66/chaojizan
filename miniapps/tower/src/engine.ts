// 瓜田防线的引擎:建塔 / 升级 / 卖塔 / 提前召唤 / 倍速 / 暂停,出怪、移动、索敌、伤害、状态、经济、胜负。
// 纯逻辑:不碰 DOM、不读时钟、不用 Math.random;advance(state, dt) 推进传入的状态并按固定步长跑,
// 界面只读状态和事件。存档读写在同目录的 save.ts。
import { rand } from '../../shared/src/rand'
import {
  EARLY_BONUS, STEP, TILE, TARGET_CENTER, bossHealthScale, endlessHealthScale, enemyDef,
  sellValue, towerDefOrNull, towerStats, upgradeCost,
} from './data'
import { levelById, unlockLevelOf, waveCount } from './levels'
import { chainFrom, enemiesInRadius, enemyPos, pickTarget, rangePx, slotPos } from './targeting'
import { buildSpawns, hasBoss, hpScaleOf, prepForNext, waveAt, waveReward } from './waves'
import type {
  Command, CommandResult, Enemy, EnemyKind, GameEvent, GameState, LevelDef, Tower, Vec,
} from './types'

// ---------------------------------------------------------------- 新局

/** 场上单位上限:极端波次/坏输入时兜底(存档校验里也用同样的数) */
const MAX_ENEMIES = 300
const MAX_SHOTS = 64

/** 开一局。level 从 data.ts 的关卡里来,seed 固定则整局可复现 */
export function newGame(level: LevelDef, seed: number): GameState {
  const s: GameState = {
    v: 1,
    levelId: level.id,
    seed: seed >>> 0 || 1,
    rng: seed >>> 0 || 1,
    gold: level.startGold,
    hp: level.goalHp,
    maxHp: level.goalHp,
    wave: 0,
    phase: 'prep',
    prep: level.firstPrep,
    clock: 0,
    spawns: [],
    enemies: [],
    towers: [],
    shots: [],
    nextId: 1,
    over: null,
    stars: 0,
    time: 0,
    summoned: false,
    paused: false,
    speed: 1,
    endless: level.id === 'endless',
    stats: { kills: 0, bossKills: 0, leaks: 0, goldEarned: 0, built: 0, sold: 0, upgrades: 0, towers: [] },
    acc: 0,
    bossWave: false,
  }
  return s
}

// ---------------------------------------------------------------- 随机

function nextRand(state: GameState): number {
  const [v, next] = rand(state.rng)
  state.rng = next
  return v
}

// ---------------------------------------------------------------- 出怪 / 位置

/** 敌人当前位置(渲染/索敌共用) */
export function posOf(state: GameState, e: Enemy): Vec {
  return enemyPos(levelById(state.levelId), e)
}

/**
 * 在场上放一只怪(分裂蚁的小蚁、测试也用它)。dist 是沿路走了多远。
 * 血量按当前波次成长。
 */
export function spawnEnemy(state: GameState, kind: EnemyKind, path: number, dist: number): Enemy {
  const level = levelById(state.levelId)
  const def = enemyDef(kind)
  const paths = level.world.polys.length
  const p = Math.min(paths - 1, Math.max(0, Math.floor(path)))
  const span = def.flying
    ? Math.hypot(level.world.target.x - level.world.starts[p].x, level.world.target.y - level.world.starts[p].y)
    : level.world.lens[p]
  const wave = Math.max(1, state.wave)
  const scale = def.boss
    ? (state.endless ? endlessHealthScale(wave) : bossHealthScale(wave))
    : hpScaleOf(state.levelId, wave)
  const maxHp = Math.max(1, Math.round(def.hp * scale))
  const e: Enemy = {
    id: state.nextId++,
    kind,
    hp: maxHp,
    maxHp,
    dist: Math.min(span, Math.max(0, dist)),
    span,
    path: p,
    slowUntil: 0,
    slowFactor: 0,
    freezeUntil: 0,
    poisonUntil: 0,
    poisonDps: 0,
    burnUntil: 0,
    burnDps: 0,
    flash: 0,
  }
  state.enemies.push(e)
  return e
}

// ---------------------------------------------------------------- 状态 / 伤害

/** 减速:取最强的那个;时间刷新到更晚(单测与工具直接调用) */
export function applySlow(e: Enemy, factor: number, until: number): void {
  if (factor >= e.slowFactor) e.slowFactor = factor
  e.slowUntil = Math.max(e.slowUntil, until)
}

export function applyPoison(e: Enemy, dps: number, until: number): void {
  e.poisonDps = Math.max(e.poisonDps, dps)
  e.poisonUntil = Math.max(e.poisonUntil, until)
}

export function applyBurn(e: Enemy, dps: number, until: number): void {
  e.burnDps = Math.max(e.burnDps, dps)
  e.burnUntil = Math.max(e.burnUntil, until)
}

export function applyFreeze(e: Enemy, until: number): void {
  e.freezeUntil = Math.max(e.freezeUntil, until)
}

/** 普通伤害:先减护甲,最少 1;返回有没有打死。pierce 无视护甲(单测直接调用) */
export function dealDamage(state: GameState, e: Enemy, raw: number, events: GameEvent[],
  opts: { pierce?: boolean; source?: Tower; silent?: boolean } = {}): boolean {
  if (e.hp <= 0) return false
  const def = enemyDef(e.kind)
  const armor = opts.pierce ? 0 : def.armor
  const actual = Math.max(1, raw - armor)
  e.hp -= actual
  e.flash = 0.12
  if (!opts.silent) {
    events.push({ e: 'hit', pos: posOf(state, e), amount: Math.round(actual * 10) / 10, armor: !opts.pierce && def.armor > 0 })
  }
  if (e.hp <= 0) {
    killEnemy(state, e, events, opts.source)
    return true
  }
  return false
}

/** 持续伤害:无视护甲;不刷屏(不出飘字事件)。单测直接调用 */
export function dealDot(state: GameState, e: Enemy, amount: number, events: GameEvent[]): boolean {
  if (e.hp <= 0) return false
  e.hp -= amount
  if (e.hp <= 0) {
    killEnemy(state, e, events)
    return true
  }
  return false
}

/** 打死一只:赏金、统计、分裂、死亡毒云 */
function killEnemy(state: GameState, e: Enemy, events: GameEvent[], source?: Tower): void {
  if (e.hp > 0) return
  const level = levelById(state.levelId)
  const def = enemyDef(e.kind)
  const pos = enemyPos(level, e)
  state.enemies = state.enemies.filter((x) => x.id !== e.id)
  state.gold += def.bounty
  state.stats.goldEarned += def.bounty
  state.stats.kills += 1
  if (def.boss) state.stats.bossKills += 1
  events.push({ e: 'kill', pos, bounty: def.bounty, kind: e.kind })
  events.push({ e: 'gold', amount: def.bounty, pos, why: 'kill' })
  if (def.split) {
    for (let i = 0; i < def.split; i++) {
      // 小蚁从分裂位置稍靠后一点出来,给防守方一点反应时间(不然贴着西瓜打爆会直接漏)
      spawnEnemy(state, 'antling', e.path, Math.max(0, e.dist - TILE * 0.7 - i * 6))
    }
    events.push({ e: 'split', pos })
  }
  if (source) {
    const srcStats = towerStats(source.kind, source.level)
    if (srcStats.deathCloud) {
      const radius = 1.6 * TILE
      const now = state.time
      for (const other of enemiesInRadius(level, state.enemies, pos, radius)) {
        applyPoison(other, 9, now + 3)
      }
      events.push({ e: 'cloud', pos, radius })
    }
  }
}

// ---------------------------------------------------------------- 塔的攻击

/** 一种塔对一只虫打一发 */
function fireOnce(state: GameState, level: LevelDef, tower: Tower, stats: ReturnType<typeof towerStats>,
  target: Enemy, events: GameEvent[]): void {
  const from = slotPos(level, tower.slot)
  const to = enemyPos(level, target)
  const source = tower
  if (tower.kind === 'pea' || tower.kind === 'bow') {
    events.push({ e: 'shot', kind: tower.kind, from, to })
    addShot(state, tower.kind, from, to)
    dealDamage(state, target, stats.damage, events, { pierce: stats.pierce, source })
    return
  }
  if (tower.kind === 'frost') {
    events.push({ e: 'shot', kind: 'frost', from, to })
    dealDamage(state, target, stats.damage, events, { source })
    if (target.hp <= 0) return
    if (stats.slowFactor) applySlow(target, stats.slowFactor, state.time + (stats.slowDur || 1))
    if (stats.freezeChance && nextRand(state) < stats.freezeChance) {
      applyFreeze(target, state.time + (stats.freezeDur || 0.5))
      events.push({ e: 'freeze', pos: enemyPos(level, target) })
    }
    return
  }
  if (tower.kind === 'pepper') {
    const radius = (stats.splash || 0.8) * TILE
    events.push({ e: 'shot', kind: 'pepper', from, to })
    events.push({ e: 'boom', kind: 'pepper', pos: to, radius })
    addShot(state, 'pepper', from, to)
    for (const e of enemiesInRadius(level, state.enemies, to, radius)) {
      dealDamage(state, e, stats.damage, events, { source })
      if (stats.burnDps && e.hp > 0) {
        applyBurn(e, stats.burnDps, state.time + (stats.burnDur || 3))
        events.push({ e: 'burn', pos: enemyPos(level, e) })
      }
    }
    return
  }
  if (tower.kind === 'vine') {
    const chained = chainFrom(level, state.enemies, target, stats.chain || 0, 2.0 * TILE)
    const points: Vec[] = [from]
    let raw = stats.damage
    for (const e of [target, ...chained]) {
      points.push(enemyPos(level, e))
      dealDamage(state, e, raw, events, { source })
      raw *= 0.8
    }
    events.push({ e: 'chain', points })
    return
  }
  if (tower.kind === 'mushroom') {
    events.push({ e: 'shot', kind: 'mushroom', from, to })
    dealDamage(state, target, stats.damage, events, { source })
    const radius = (stats.poisonRadius || 1.0) * TILE
    for (const e of enemiesInRadius(level, state.enemies, to, radius)) {
      if (e.hp <= 0) continue
      applyPoison(e, stats.poisonDps || 0, state.time + (stats.poisonDur || 4))
      events.push({ e: 'poison', pos: enemyPos(level, e) })
    }
  }
}

/** 记一发视觉弹道(只为了渲染和存档里「子弹状态」,不参与判定) */
function addShot(state: GameState, kind: 'pea' | 'bow' | 'pepper', from: Vec, to: Vec): void {
  state.shots.push({ kind, x: from.x, y: from.y, tx: to.x, ty: to.y, life: 0.16, max: 0.16 })
  if (state.shots.length > MAX_SHOTS) state.shots.splice(0, state.shots.length - MAX_SHOTS)
}

function updateTowers(state: GameState, level: LevelDef, dt: number, events: GameEvent[]): void {
  for (const tower of state.towers) {
    const stats = towerStats(tower.kind, tower.level)
    if (!stats.rate) continue
    tower.cd = Math.max(0, tower.cd - dt)
    if (tower.cd > 0) continue
    const from = slotPos(level, tower.slot)
    const target = pickTarget(level, state.enemies, from, rangePx(stats.range))
    if (!target) continue
    tower.cd = 1 / stats.rate
    let current: Enemy | null = target
    for (let shot = 0; shot < (stats.shots || 1); shot++) {
      if (!current || current.hp <= 0) current = pickTarget(level, state.enemies, from, rangePx(stats.range))
      if (!current) break
      const to = enemyPos(level, current)
      tower.aim = Math.atan2(to.y - from.y, to.x - from.x)
      fireOnce(state, level, tower, stats, current, events)
    }
  }
}

// ---------------------------------------------------------------- 波次

function startWave(state: GameState, events: GameEvent[]): void {
  const level = levelById(state.levelId)
  state.wave += 1
  const def = waveAt(level, state.wave)
  state.phase = 'wave'
  state.prep = 0
  state.clock = 0
  state.summoned = false
  state.spawns = buildSpawns(def)
  state.bossWave = hasBoss(def)
  events.push({ e: 'wave', wave: state.wave })
  if (state.bossWave) events.push({ e: 'boss', name: '巨虫' })
}

function endWave(state: GameState, events: GameEvent[]): void {
  const level = levelById(state.levelId)
  const reward = waveReward(state.wave)
  let marigold = 0
  for (const t of state.towers) marigold += towerStats(t.kind, t.level).goldPerWave || 0
  state.gold += reward + marigold
  state.stats.goldEarned += reward + marigold
  events.push({ e: 'waveClear', wave: state.wave, reward, marigold })
  if (reward + marigold > 0) events.push({ e: 'gold', amount: reward + marigold, pos: { ...TARGET_CENTER }, why: 'wave' })
  const next = state.wave + 1
  if (state.endless || next <= waveCount(level)) {
    state.phase = 'prep'
    state.prep = prepForNext(level, next)
    state.summoned = false
    state.bossWave = false
    state.spawns = []
  } else {
    win(state, events)
  }
}

/** 星级:满血 3 星;剩余 ≥60% 2 星;通关 1 星 */
export function starsOf(state: GameState): number {
  if (state.hp >= state.maxHp) return 3
  if (state.hp * 10 >= state.maxHp * 6) return 2
  return 1
}

function win(state: GameState, events: GameEvent[]): void {
  state.over = 'win'
  state.phase = 'over'
  state.stars = starsOf(state)
  state.spawns = []
  events.push({ e: 'win', stars: state.stars })
}

function lose(state: GameState, events: GameEvent[]): void {
  state.over = 'lose'
  state.phase = 'over'
  state.stars = 0
  state.spawns = []
  events.push({ e: 'lose' })
}

// ---------------------------------------------------------------- 每步推进

function spawnDue(state: GameState, dt: number): void {
  state.clock += dt
  while (state.spawns.length && state.spawns[0].at <= state.clock && state.enemies.length < MAX_ENEMIES) {
    const sp = state.spawns.shift()
    if (!sp) break
    spawnEnemy(state, sp.kind, sp.path, 0)
  }
}

function updateEnemies(state: GameState, level: LevelDef, dt: number, events: GameEvent[]): void {
  const now = state.time
  // ① 持续伤害 + 状态计时
  for (const e of [...state.enemies]) {
    if (e.hp <= 0) continue
    if (e.flash > 0) e.flash = Math.max(0, e.flash - dt)
    if (e.poisonUntil > now && e.poisonDps > 0) {
      if (dealDot(state, e, e.poisonDps * dt, events)) continue
    }
    if (e.burnUntil > now && e.burnDps > 0) dealDot(state, e, e.burnDps * dt, events)
  }
  // ② 治疗蛹给周围的虫子回血
  for (const pupa of state.enemies) {
    if (pupa.hp <= 0) continue
    const def = enemyDef(pupa.kind)
    if (!def.heal) continue
    const p = enemyPos(level, pupa)
    for (const other of state.enemies) {
      if (other.id === pupa.id || other.hp <= 0 || other.hp >= other.maxHp) continue
      const q = enemyPos(level, other)
      if (Math.hypot(q.x - p.x, q.y - p.y) <= def.heal.radius * TILE) {
        other.hp = Math.min(other.maxHp, other.hp + def.heal.rate * dt)
      }
    }
  }
  // ③ 移动 / 漏怪
  for (const e of [...state.enemies]) {
    if (e.hp <= 0) continue
    const def = enemyDef(e.kind)
    const frozen = e.freezeUntil > now
    const slowed = e.slowUntil > now ? 1 - Math.min(0.8, e.slowFactor) : 1
    const speed = def.speed * TILE * (frozen ? 0 : slowed)
    e.dist += speed * dt
    if (e.dist >= e.span) {
      state.enemies = state.enemies.filter((x) => x.id !== e.id)
      state.hp = Math.max(0, state.hp - def.leak)
      state.stats.leaks += 1
      events.push({ e: 'leak', pos: { ...level.world.target }, amount: def.leak, boss: def.boss === true, kind: e.kind })
      if (state.hp <= 0) {
        lose(state, events)
        return
      }
    }
  }
}

function updateShots(state: GameState, dt: number): void {
  if (!state.shots.length) return
  for (const shot of state.shots) shot.life -= dt
  state.shots = state.shots.filter((s) => s.life > 0)
}

function step(state: GameState, dt: number, events: GameEvent[]): void {
  state.time += dt
  if (state.phase === 'prep') {
    state.prep = Math.max(0, state.prep - dt)
    if (state.prep <= 0) startWave(state, events)
  }
  if (state.over) return
  if (state.phase !== 'wave') return
  const level = levelById(state.levelId)
  spawnDue(state, dt)
  updateEnemies(state, level, dt, events)
  if (state.over) return
  updateTowers(state, level, dt, events)
  updateShots(state, dt)
  if (state.phase === 'wave' && state.spawns.length === 0 && state.enemies.length === 0) {
    endWave(state, events)
  }
}

/**
 * 推进一局。dt 是真实秒数;内部按 60Hz 固定步长跑,所以 30fps / 120fps 的设备结果一致。
 * 单次调用的上限是 10 秒(防坏输入死循环);界面层每帧自己把 dt 夹在 0.05 秒以内,
 * 切后台回来不会瞬移。
 */
export function advance(state: GameState, dt: number): GameEvent[] {
  const events: GameEvent[] = []
  if (state.over || state.paused) return events
  const real = Math.min(10, Math.max(0, dt))
  if (real <= 0) return events
  state.acc += real * state.speed
  let guard = 0
  // 多给一个极小的容差:0.6 秒和 6×0.1 秒切分时浮点尾数不一样,不能让「切法」影响步数
  while (state.acc + 1e-9 >= STEP && guard < 720) {
    state.acc = Math.max(0, state.acc - STEP)
    guard++
    step(state, STEP, events)
    if (state.over) {
      state.acc = 0
      break
    }
  }
  return events
}

// ---------------------------------------------------------------- 命令

function towerAt(state: GameState, slot: number): boolean {
  return state.towers.some((t) => t.slot === slot)
}

/**
 * 玩家操作。成功时返回 ok;失败返回一句原因(界面直接展示)。
 * events 传进来时会把这次操作产生的事件(建造音效、卖塔金币等)追加进去。
 */
export function command(state: GameState, cmd: Command, events: GameEvent[] = []): CommandResult {
  if (state.over) return { ok: false, reason: '这一局已经结束了' }
  switch (cmd.kind) {
    case 'pause':
      state.paused = cmd.paused
      return { ok: true }
    case 'speed':
      if (cmd.speed !== 1 && cmd.speed !== 2) return { ok: false, reason: '倍速只能是 1 或 2' }
      state.speed = cmd.speed
      return { ok: true }
    case 'build': {
      const level = levelById(state.levelId)
      if (!Number.isInteger(cmd.slot) || cmd.slot < 0 || cmd.slot >= level.slots.length) {
        return { ok: false, reason: '这里不能造塔' }
      }
      const def = towerDefOrNull(cmd.tower)
      if (!def) return { ok: false, reason: '没有这种塔' }
      if (!level.towers.includes(cmd.tower)) {
        return { ok: false, reason: `第 ${unlockLevelOf(cmd.tower)} 关解锁` }
      }
      if (towerAt(state, cmd.slot)) return { ok: false, reason: '这个建造位已经有塔了' }
      if (state.gold < def.cost) return { ok: false, reason: `还差 ${def.cost - state.gold} 金币` }
      state.gold -= def.cost
      state.towers.push({
        id: state.nextId++, kind: cmd.tower, level: 1, slot: cmd.slot, cd: 0, aim: -Math.PI / 2,
        invested: def.cost,
      })
      state.stats.built += 1
      if (!state.stats.towers.includes(cmd.tower)) state.stats.towers.push(cmd.tower)
      events.push({ e: 'build', slot: cmd.slot, kind: cmd.tower })
      return { ok: true }
    }
    case 'upgrade': {
      const tower = state.towers.find((t) => t.id === cmd.id)
      if (!tower) return { ok: false, reason: '没有这座塔' }
      if (tower.level >= 3) return { ok: false, reason: '已经满级了' }
      const cost = upgradeCost(tower.kind, tower.level)
      if (state.gold < cost) return { ok: false, reason: `还差 ${cost - state.gold} 金币` }
      state.gold -= cost
      tower.level = (tower.level + 1) as 1 | 2 | 3
      tower.invested += cost
      state.stats.upgrades += 1
      events.push({ e: 'upgrade', id: tower.id })
      return { ok: true }
    }
    case 'sell': {
      const tower = state.towers.find((t) => t.id === cmd.id)
      if (!tower) return { ok: false, reason: '没有这座塔' }
      const refund = sellValue(tower.invested)
      state.towers = state.towers.filter((t) => t.id !== tower.id)
      state.gold += refund
      state.stats.sold += 1
      events.push({ e: 'sell', id: tower.id })
      if (refund > 0) {
        events.push({ e: 'gold', amount: refund, pos: slotPos(levelById(state.levelId), tower.slot), why: 'sell' })
      }
      return { ok: true }
    }
    case 'summon': {
      if (state.phase !== 'prep' || state.over) return { ok: false, reason: '现在还不能召唤' }
      state.gold += EARLY_BONUS
      state.stats.goldEarned += EARLY_BONUS
      events.push({ e: 'gold', amount: EARLY_BONUS, pos: { ...TARGET_CENTER }, why: 'early' })
      state.prep = 0
      startWave(state, events)
      return { ok: true }
    }
    default:
      return { ok: false, reason: '不认识的操作' }
  }
}
