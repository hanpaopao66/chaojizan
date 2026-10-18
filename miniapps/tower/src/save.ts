// 存档:把一局状态序列化成紧凑的普通 JSON、读回来时逐字段校验(坏档当作没有)、以及结算用的汇总。
// 和 engine.ts 共用同一份数据形状;规则本身在 engine.ts,这里只管「能存能读、存得下」。
//
// 为什么要压缩:云端每个键上限 64 KB,而后期无尽模式场上最多 300 只虫、时间表里最多 800 只待出的虫。
// 用字段全名存一份大约 55 KB 起步,会顶到上限。所以存的是数组 + 短键 + 两位小数:
// - 塔/虫/波次里的种类存成下标(见 *_KINDS 数组);
// - 距离、时间、状态剩余时间保留两位小数(60Hz 一步 0.017 秒,两位小数够用);
// - 敌人的 hp 可以是小数(毒、灼烧、治疗蛹都会让它变成小数),读档时按「有限数值且在范围内」校验。
import { TOWERS, enemyDefOrNull, towerDefOrNull } from './data'
import { levelByIdOrNull, waveCount } from './levels'
import type { Enemy, EnemyKind, GameState, Shot, Spawn, Tower, TowerKind } from './types'

const SAVE_V = 1
const MAX_ENEMIES = 300
const MAX_TOWERS = 64
const MAX_SPAWNS = 800
const MAX_SHOTS = 64
const MAX_WAVE = 5000
const MAX_MONEY = 1e9
const MAX_TIME = 1e7

/** 虫的种类下标(存档里只存下标,省字节) */
const ENEMY_KINDS: readonly EnemyKind[] = ['worm', 'flea', 'beetle', 'moth', 'wasp', 'pupa', 'ant', 'antling', 'boss']
/** 塔的种类下标 */
const TOWER_KINDS: readonly TowerKind[] = TOWERS.map((t) => t.kind)
/** 弹道的种类下标 */
const SHOT_KINDS: readonly TowerKind[] = ['pea', 'bow', 'pepper']
const PHASES: readonly GameState['phase'][] = ['prep', 'wave', 'over']

const NUM = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const INT = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number =>
  typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max
const ARR = (v: unknown): unknown[] | null => (Array.isArray(v) ? v : null)
/** 保留两位小数(60Hz 一步 0.017 秒,两位小数足够;存档能小一半) */
const r2 = (v: number): number => Math.round(v * 100) / 100

function indexOfKind<T extends string>(kinds: readonly T[], kind: T): number {
  const i = kinds.indexOf(kind)
  return i < 0 ? -1 : i
}

/** 一局存档的紧凑形状(只有 saveGame / loadGame 用) */
export interface SavedGame {
  v: 1
  /** 关卡 id */
  l: number | 'endless'
  /** 种子 / 随机数状态 */
  sd: number
  rg: number
  /** 金币 / 西瓜血量 / 最大血量 */
  g: number
  hp: number
  mh: number
  /** 波次 / 阶段下标 / 准备倒计时 / 本波时钟 */
  w: number
  ph: number
  pr: number
  c: number
  /** 下一个 id */
  ni: number
  /** 0 输 / 1 赢 / null 进行中 */
  ov: 0 | 1 | null
  st: number
  t: number
  /** summoned / paused / speed / endless / bossWave */
  su: 0 | 1
  pa: 0 | 1
  sp: 1 | 2
  en: 0 | 1
  bw: 0 | 1
  /** 统计:击杀、Boss 击杀、漏怪、赚到金币、造塔、卖塔、升级 */
  sk: number[]
  /** 造过的塔的种类位掩码 */
  ut: number
  /** 塔:[id, 种类下标, 等级, 建造位, 冷却, 朝向, 累计投入] */
  ts: number[][]
  /** 虫:[id, 种类下标, hp, maxHp, 路程, 路线, slowUntil, slowFactor, freezeUntil,
   *        poisonUntil, poisonDps, burnUntil, burnDps, 受击闪白] */
  es: number[][]
  /** 待出怪:[种类下标, 相对本波时间, 路线] */
  ss: number[][]
  /** 弹道:[种类下标, x, y, tx, ty, life, max] */
  sh: number[][]
}

/** 把一局序列化成紧凑 JSON(子弹只留最后 32 发;固定步长累加器不用存) */
export function saveGame(state: GameState): SavedGame {
  const used = state.stats.towers.reduce((mask, k) => {
    const i = indexOfKind(TOWER_KINDS, k)
    return i < 0 ? mask : mask | (1 << i)
  }, 0)
  return {
    v: 1,
    l: state.levelId,
    sd: state.seed,
    rg: state.rng,
    g: state.gold,
    hp: r2(state.hp),
    mh: state.maxHp,
    w: state.wave,
    ph: PHASES.indexOf(state.phase),
    pr: r2(state.prep),
    c: r2(state.clock),
    ni: state.nextId,
    ov: state.over === 'win' ? 1 : state.over === 'lose' ? 0 : null,
    st: state.stars,
    t: r2(state.time),
    su: state.summoned ? 1 : 0,
    pa: state.paused ? 1 : 0,
    sp: state.speed,
    en: state.endless ? 1 : 0,
    bw: state.bossWave ? 1 : 0,
    sk: [
      state.stats.kills, state.stats.bossKills, state.stats.leaks, state.stats.goldEarned,
      state.stats.built, state.stats.sold, state.stats.upgrades,
    ],
    ut: used,
    ts: state.towers.map((t) => [
      t.id, indexOfKind(TOWER_KINDS, t.kind), t.level, t.slot, r2(t.cd), r2(t.aim), Math.round(t.invested),
    ]),
    es: state.enemies.map((e) => [
      e.id, indexOfKind(ENEMY_KINDS, e.kind), r2(e.hp), e.maxHp, r2(e.dist), e.path,
      r2(e.slowUntil), r2(e.slowFactor), r2(e.freezeUntil), r2(e.poisonUntil), r2(e.poisonDps),
      r2(e.burnUntil), r2(e.burnDps), r2(e.flash),
    ]),
    ss: state.spawns.map((s) => [indexOfKind(ENEMY_KINDS, s.kind), r2(s.at), s.path]),
    sh: state.shots.slice(-32).map((s) => [
      indexOfKind(SHOT_KINDS, s.kind), r2(s.x), r2(s.y), r2(s.tx), r2(s.ty), r2(s.life), r2(s.max),
    ]),
  }
}

/** 读一份存档;任何不对劲的地方都返回 null(当作没有存档),不抛错 */
export function loadGame(raw: unknown): GameState | null {
  if (!raw || typeof raw !== 'object') return null
  const s = raw as Partial<SavedGame>
  if (s.v !== SAVE_V) return null
  const level = levelByIdOrNull(s.l)
  if (!level) return null
  const endless = s.en === 1
  if (endless !== (level.id === 'endless')) return null
  if (!INT(s.g, 0, MAX_MONEY) || !INT(s.mh, 1, 1e4) || s.mh !== level.goalHp) return null
  // 西瓜血量只会被漏怪扣(整数);读档放宽成「有限数值在范围内」,以后加机制也不会误判坏档
  if (!NUM(s.hp) || s.hp < 0 || s.hp > s.mh) return null
  if (!INT(s.w, 0, level.id === 'endless' ? MAX_WAVE : waveCount(level))) return null
  if (!INT(s.ph, 0, PHASES.length - 1)) return null
  if (!NUM(s.pr) || s.pr < 0 || s.pr > 1e6 || !NUM(s.c) || s.c < 0 || s.c > 1e6) return null
  if (!INT(s.ni, 1, MAX_MONEY)) return null
  if (s.ov !== null && s.ov !== undefined && s.ov !== 0 && s.ov !== 1) return null
  const over = s.ov === 1 ? 'win' : s.ov === 0 ? 'lose' : null
  const phase = PHASES[s.ph]
  if ((over === null) === (phase === 'over')) return null
  if (!INT(s.st, 0, 3)) return null
  if (over === 'win' ? s.st < 1 : s.st !== 0) return null
  if (!NUM(s.t) || s.t < 0 || s.t > MAX_TIME) return null
  if ((s.su !== 0 && s.su !== 1) || (s.pa !== 0 && s.pa !== 1) ||
    (s.en !== 0 && s.en !== 1) || (s.bw !== 0 && s.bw !== 1)) return null
  if (s.sp !== 1 && s.sp !== 2) return null
  const seed = NUM(s.sd) ? Math.floor(s.sd) >>> 0 : 1
  const rng = NUM(s.rg) ? Math.floor(s.rg) >>> 0 : 1
  const sk = ARR(s.sk)
  if (!sk || sk.length !== 7 || !sk.every((v) => INT(v, 0, MAX_MONEY))) return null
  const stat = sk as number[]
  if (!INT(s.ut, 0, (1 << TOWER_KINDS.length) - 1)) return null

  const ids = new Set<number>()
  let maxId = 0
  const towersRaw = ARR(s.ts)
  if (!towersRaw || towersRaw.length > MAX_TOWERS) return null
  const towers: Tower[] = []
  const slots = new Set<number>()
  for (const entry of towersRaw) {
    const a = ARR(entry)
    if (!a || a.length < 7) return null
    const [id, kindIdx, lv, slot, cd, aim, invested] = a
    if (!INT(id, 1, MAX_MONEY) || ids.has(id) || !INT(kindIdx, 0, TOWER_KINDS.length - 1)) return null
    if (!INT(lv, 1, 3) || !INT(slot, 0, level.slots.length - 1) || slots.has(slot)) return null
    if (!NUM(cd) || cd < 0 || cd > 60 || !NUM(aim) || Math.abs(aim) > 1e4) return null
    const kind = TOWER_KINDS[kindIdx]
    const def = towerDefOrNull(kind)
    if (!def || !NUM(invested) || invested < def.cost || invested > MAX_MONEY) return null
    ids.add(id)
    maxId = Math.max(maxId, id)
    slots.add(slot)
    towers.push({ id, kind, level: lv as 1 | 2 | 3, slot, cd, aim, invested })
  }

  const enemiesRaw = ARR(s.es)
  if (!enemiesRaw || enemiesRaw.length > MAX_ENEMIES) return null
  const enemies: Enemy[] = []
  for (const entry of enemiesRaw) {
    const a = ARR(entry)
    if (!a || a.length < 14) return null
    const [id, kindIdx, hp, maxHp, dist, path, slowUntil, slowFactor, freezeUntil,
      poisonUntil, poisonDps, burnUntil, burnDps, flash] = a
    if (!INT(id, 1, MAX_MONEY) || ids.has(id) || !INT(kindIdx, 0, ENEMY_KINDS.length - 1)) return null
    const kind = ENEMY_KINDS[kindIdx]
    const def = enemyDefOrNull(kind)
    if (!def) return null
    // 虫的血可以是小数:毒/灼烧按 dt 扣、治疗蛹按 dt 加,会出现 29.433333 这种值
    if (!NUM(hp) || hp <= 0 || hp > 1e9) return null
    if (!INT(maxHp, 1, 1e6) || hp > maxHp + 1e-6) return null
    if (!INT(path, 0, level.world.polys.length - 1)) return null
    const span = def.flying
      ? Math.hypot(level.world.target.x - level.world.starts[path].x,
        level.world.target.y - level.world.starts[path].y)
      : level.world.lens[path]
    if (!NUM(dist) || dist < 0 || dist > span + 1) return null
    for (const v of [slowUntil, slowFactor, freezeUntil, poisonUntil, poisonDps, burnUntil, burnDps, flash]) {
      if (!NUM(v) || v < 0 || v > 1e9) return null
    }
    ids.add(id)
    maxId = Math.max(maxId, id)
    enemies.push({
      id,
      kind,
      hp: Math.min(maxHp as number, hp as number),
      maxHp: maxHp as number,
      dist: Math.min(span, dist as number),
      span,
      path,
      slowUntil: slowUntil as number,
      slowFactor: slowFactor as number,
      freezeUntil: freezeUntil as number,
      poisonUntil: poisonUntil as number,
      poisonDps: poisonDps as number,
      burnUntil: burnUntil as number,
      burnDps: burnDps as number,
      flash: flash as number,
    })
  }

  const spawnsRaw = ARR(s.ss)
  if (!spawnsRaw || spawnsRaw.length > MAX_SPAWNS) return null
  const spawns: Spawn[] = []
  for (const entry of spawnsRaw) {
    const a = ARR(entry)
    if (!a || a.length < 3) return null
    const [kindIdx, at, path] = a
    if (!INT(kindIdx, 0, ENEMY_KINDS.length - 1) || !NUM(at) || at < 0 || at > 1e6) return null
    if (!INT(path, 0, level.world.polys.length - 1)) return null
    spawns.push({ kind: ENEMY_KINDS[kindIdx], at, path })
  }

  const shotsRaw = ARR(s.sh)
  if (!shotsRaw || shotsRaw.length > MAX_SHOTS) return null
  const shots: Shot[] = []
  for (const entry of shotsRaw) {
    const a = ARR(entry)
    if (!a || a.length < 7) return null
    const [kindIdx, x, y, tx, ty, life, max] = a
    if (!INT(kindIdx, 0, SHOT_KINDS.length - 1)) return null
    if (![x, y, tx, ty, life, max].every((v) => NUM(v) && Math.abs(v) <= 1e6)) return null
    const nx = x as number
    const ny = y as number
    const ntx = tx as number
    const nty = ty as number
    const nlife = life as number
    const nmax = max as number
    if (nlife < 0 || nmax <= 0 || nlife > nmax) return null
    shots.push({ kind: SHOT_KINDS[kindIdx], x: nx, y: ny, tx: ntx, ty: nty, life: nlife, max: nmax })
  }

  const towersUsed = TOWER_KINDS.filter((_, i) => ((s.ut as number) & (1 << i)) !== 0)
  const result: GameState = {
    v: 1,
    levelId: level.id,
    seed: seed || 1,
    rng: rng || 1,
    gold: s.g,
    hp: Math.min(s.mh, Math.max(0, s.hp)),
    maxHp: s.mh,
    wave: s.w,
    phase,
    prep: s.pr,
    clock: s.c,
    spawns,
    enemies,
    towers,
    shots,
    nextId: Math.max(s.ni, maxId + 1, 1),
    over,
    stars: s.st,
    time: s.t,
    summoned: s.su === 1,
    paused: s.pa === 1,
    speed: s.sp,
    endless,
    stats: {
      kills: stat[0], bossKills: stat[1], leaks: stat[2], goldEarned: stat[3],
      built: stat[4], sold: stat[5], upgrades: stat[6], towers: towersUsed,
    },
    acc: 0,
    bossWave: s.bw === 1,
  }
  return result
}

/** 一局结束时的战报(结算页用) */
export interface RunResult {
  levelId: number | 'endless'
  won: boolean
  stars: number
  hp: number
  maxHp: number
  kills: number
  bossKills: number
  leaks: number
  goldEarned: number
  built: number
  waves: number
  time: number
  endlessWave: number
  towerKinds: GameState['stats']['towers']
}

/** 结算用的汇总 */
export function resultOf(state: GameState): RunResult {
  return {
    levelId: state.levelId,
    won: state.over === 'win',
    stars: state.stars,
    hp: state.hp,
    maxHp: state.maxHp,
    kills: state.stats.kills,
    bossKills: state.stats.bossKills,
    leaks: state.stats.leaks,
    goldEarned: state.stats.goldEarned,
    built: state.stats.built,
    waves: state.wave,
    time: state.time,
    endlessWave: state.endless ? state.wave : 0,
    towerKinds: state.stats.towers,
  }
}
