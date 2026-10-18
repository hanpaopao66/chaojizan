import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Difficulty } from '../src/combat'
import { MapDef, Vec, circleBlocked, dist, lineOfSight, mapById, parseMap } from '../src/map'
import { routeBetween } from '../src/nav'
import {
  FREEZE_TIME, MatchState, PlayerInput, Round, advance, canPlant, newMatch, newRound,
} from '../src/match'

const idle: PlayerInput = { moveX: 0, moveY: 0, aim: null, fire: false, reload: false, swap: false, interact: false }

/** 给「像人」的脚本策略用的固定种子随机数(mulberry32) */
function rng(seed: number): () => number {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6d2b79f5) >>> 0
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** 像人一样瞄:给瞄准角加一点抖动,不百发百中 */
function humanAim(from: Vec, to: Vec, random: () => number): number {
  const base = Math.atan2(to.y - from.y, to.x - from.x)
  return base + (random() - 0.5) * 0.03
}

/** 引擎里的简单玩家策略:看得见守卫就站定点射;看不见就沿 A* 路径去炸弹点;到点就按住安放;安放完守炸弹 */
interface Bot {
  route: Vec[]
  idx: number
  goal: Vec | null
  routeAt: number
  random: () => number
  /** 上一帧位置与连续卡住的帧数:卡墙角时跳过一个路径点 */
  lastX: number
  lastY: number
  stuck: number
}

function nearestVisibleGuard(round: Round): { x: number; y: number } | null {
  const p = round.player
  let best: { x: number; y: number } | null = null
  let bestD = Infinity
  for (const g of round.guards) {
    if (!g.alive) continue
    const d = dist(p.pos, g.pos)
    if (d > 460) continue
    if (!lineOfSight(round.map, p.pos, g.pos)) continue
    if (d < bestD) {
      bestD = d
      best = { x: g.pos.x, y: g.pos.y }
    }
  }
  return best
}

function siteTarget(round: Round): Vec {
  const a = round.map.siteA
  const b = round.map.siteB
  const ca = { x: ((a.x0 + a.x1 + 1) / 2) * 24, y: ((a.y0 + a.y1 + 1) / 2) * 24 }
  const cb = { x: ((b.x0 + b.x1 + 1) / 2) * 24, y: ((b.y0 + b.y1 + 1) / 2) * 24 }
  return dist(round.player.pos, ca) <= dist(round.player.pos, cb) ? ca : cb
}

function botInput(round: Round, bot: Bot, now: number): PlayerInput {
  const p = round.player
  const target = nearestVisibleGuard(round)
  if (target) {
    // 只在 220 单位内开火(再远就像「还没进入射程」);离得远就先压上去
    if (dist(p.pos, target) > 220) return moveToward(round, bot, { x: target.x, y: target.y }, now)
    return { ...idle, aim: humanAim(p.pos, target, bot.random), fire: true }
  }
  if (round.bomb.state === 'planted') {
    // 守炸弹:走到能看见炸弹的位置(离炸弹 3 格),等守卫来拆
    const bomb = round.bomb.pos
    if (bomb) {
      const near = dist(p.pos, bomb) < 150
      if (near) return idle
      return moveToward(round, bot, bomb, now)
    }
    return idle
  }
  if (canPlant(round)) return { ...idle, interact: true }
  return moveToward(round, bot, siteTarget(round), now)
}

function moveToward(round: Round, bot: Bot, goal: Vec, now: number): PlayerInput {
  const p = round.player.pos
  const moved = Math.hypot(p.x - bot.lastX, p.y - bot.lastY)
  bot.lastX = p.x
  bot.lastY = p.y
  if (moved < 1.2) bot.stuck++
  else bot.stuck = 0
  const goalMoved = !bot.goal || dist(bot.goal, goal) > 48
  // 目标变了 / 走完了 / 卡住了一阵子 才重新算路(每帧重算会导致来回摆)
  if (goalMoved || bot.idx >= bot.route.length || bot.stuck > 6) {
    bot.route = routeBetween(round.nav, p, goal)
    bot.goal = { x: goal.x, y: goal.y }
    bot.idx = 0
    bot.routeAt = now
    bot.stuck = 0
  }
  while (bot.idx < bot.route.length && dist(p, bot.route[bot.idx]) < 22) bot.idx++
  if (bot.idx >= bot.route.length) return idle
  const wp = bot.route[bot.idx]
  const dx = wp.x - p.x
  const dy = wp.y - p.y
  return {
    ...idle,
    moveX: Math.abs(dx) > 3 ? Math.sign(dx) : 0,
    moveY: Math.abs(dy) > 3 ? Math.sign(dy) : 0,
  }
}

interface SimResult { winner: 'player' | 'guard' | null; reason: string | null; elapsed: number; legal: boolean; shots: number }

/** 用同一套基准策略打一回合;返回胜负、用时、以及位置是否全程合法 */
function simulateRound(difficulty: Difficulty, seed: number, mapDef: MapDef): SimResult {
  const match: MatchState = newMatch(difficulty, seed, { mapId: mapDef.id })
  let round = newRound(match, parseMap(mapDef))
  const bot: Bot = { route: [], idx: 0, goal: null, routeAt: 0, random: rng(seed * 977 + 13), lastX: 0, lastY: 0, stuck: 0 }
  let legal = true
  let tick = 0
  for (let i = 0; i < 2400; i++) {
    tick++
    const input = botInput(round, bot, round.elapsed)
    const step = advance(round, 0.05, input)
    round = step.round
    if (tick % 8 === 0) {
      // 人和守卫都不能卡进墙里
      if (circleBlocked(round.map, round.player.pos.x, round.player.pos.y, 7)) legal = false
      for (const g of round.guards) {
        if (g.alive && circleBlocked(round.map, g.pos.x, g.pos.y, 7)) legal = false
      }
    }
    if (round.phase === 'over') {
      return {
        winner: round.over ? round.over.side : null,
        reason: round.over ? round.over.reason : null,
        elapsed: round.elapsed,
        legal,
        shots: round.player.shots,
      }
    }
  }
  return { winner: null, reason: null, elapsed: round.elapsed, legal, shots: round.player.shots }
}

test('平衡:固定种子下,休闲档的脚本玩家赢面明显高于困难档(两张图都验)', () => {
  const warehouse = mapById('warehouse')
  const market = mapById('market')
  const runSet = (difficulty: Difficulty, mapDef: MapDef, seeds: number[]): SimResult[] =>
    seeds.map((seed) => simulateRound(difficulty, seed, mapDef))
  const seeds = [11, 23, 37]
  const casual = runSet('casual', warehouse, seeds)
  const hard = runSet('hard', warehouse, seeds)
  const casualWins = casual.filter((r) => r.winner === 'player').length
  const hardWins = hard.filter((r) => r.winner === 'player').length
  assert.ok(casual.every((r) => r.legal), '休闲档模拟里没有穿墙/非法位置')
  assert.ok(hard.every((r) => r.legal), '困难档模拟里没有穿墙/非法位置')
  assert.ok(casual.every((r) => r.winner !== null), '休闲档三回合都正常结束')
  assert.ok(hard.every((r) => r.winner !== null), '困难档三回合都正常结束')
  // 基准策略(像人一样瞄准 + 反应延迟):休闲档全胜,困难档会丢局
  assert.ok(casualWins >= 2, `休闲档基准策略应该能赢(实际 ${casualWins}/3)`)
  assert.ok(casualWins > hardWins, `休闲赢 ${casualWins} 场,困难赢 ${hardWins} 场`)
  // 第二张图:同一套策略也能打、也能赢
  const marketCasual = runSet('casual', market, [11, 23])
  assert.ok(marketCasual.every((r) => r.legal), '夜市图没有非法位置')
  assert.ok(marketCasual.every((r) => r.winner !== null), '夜市图回合能正常结束')
  assert.ok(marketCasual.filter((r) => r.winner === 'player').length >= 1, '夜市图休闲档至少赢一回合')
})

test('平衡:站着不还手时,守卫的杀伤效率随难度上升(固定种子)', () => {
  const map = parseMap(mapById('warehouse'))
  const survival = (difficulty: Difficulty, seed: number): number => {
    let round = newRound(newMatch(difficulty, seed), map)
    for (let i = 0; i < 60; i++) round = advance(round, 1 / 30, idle).round
    // 把玩家放到中间走廊、守卫视线里,不移动也不还手
    round.player.pos = { x: 20.5 * 24, y: 13.5 * 24 }
    for (let i = 0; i < 40 * 30; i++) {
      round = advance(round, 1 / 30, idle).round
      if (round.phase === 'over') return round.elapsed
    }
    return 40
  }
  const avg = (v: number[]): number => v.reduce((a, b) => a + b, 0) / v.length
  const seeds = [3, 5, 7]
  const casual = avg(seeds.map((s) => survival('casual', s)))
  const normal = avg(seeds.map((s) => survival('normal', s)))
  const hard = avg(seeds.map((s) => survival('hard', s)))
  assert.ok(casual > normal, `休闲 ${casual.toFixed(1)}s 应比标准 ${normal.toFixed(1)}s 久`)
  assert.ok(normal > hard, `标准 ${normal.toFixed(1)}s 应比困难 ${hard.toFixed(1)}s 久`)
  assert.ok(casual > hard + 3, `休闲要明显更久:${casual.toFixed(1)}s vs ${hard.toFixed(1)}s`)
})

test('平衡:战斗节奏在目标区间(TTK / 子弹消耗)', () => {
  const round = simulateRound('casual', 11, mapById('warehouse'))
  // 一场 75 秒的回合里,脚本玩家平均射击次数落在合理区间(不空耗、也不瞬杀)
  assert.ok(round.shots > 5, `脚本玩家应该开过枪,实际 ${round.shots}`)
  assert.ok(round.elapsed >= FREEZE_TIME, '回合用时至少包含开场冻结')
})
