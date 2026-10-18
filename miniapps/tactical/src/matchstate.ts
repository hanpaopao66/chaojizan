// 一场比赛的账本:比分、累计数据、结算。和「一回合内」的模拟(match.ts)分开,两边都好读。

import { Difficulty } from './combat'
import { MapId } from './map'
import type { OverReason, Round, Side } from './match'

/** 先赢几个回合获胜(三局两胜) */
export const SCORE_TO_WIN = 2

export interface MatchStats {
  kills: number
  shots: number
  hits: number
  plants: number
  seconds: number
  /** 自己在回合里倒下的次数(成就「0 阵亡」用) */
  deaths: number
  /** 手枪击杀数(成就用) */
  pistolKills: number
  /** 靠炸弹爆炸拿下的回合数(成就「安放并守住」用) */
  explodedWins: number
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
  /** 这一场选的地图 */
  mapId: MapId
  /** 训练模式:不记战绩、守卫会复活、没有胜负 */
  training: boolean
  /** 第几回合(从 1 开始) */
  round: number
  scorePlayer: number
  scoreGuard: number
  seed: number
  over: 'win' | 'loss' | null
  stats: MatchStats
  lastRound: RoundSummary | null
}

export function newMatch(
  difficulty: Difficulty,
  seed: number,
  opts: { mapId?: MapId; training?: boolean } = {},
): MatchState {
  return {
    difficulty,
    mapId: opts.mapId ?? 'warehouse',
    training: opts.training ?? false,
    round: 1,
    scorePlayer: 0,
    scoreGuard: 0,
    seed: seed >>> 0,
    over: null,
    stats: { kills: 0, shots: 0, hits: 0, plants: 0, seconds: 0, deaths: 0, pistolKills: 0, explodedWins: 0 },
    lastRound: null,
  }
}

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
    deaths: match.stats.deaths + round.player.deaths,
    pistolKills: match.stats.pistolKills + round.player.pistolKills,
    explodedWins: match.stats.explodedWins
      + (round.over.side === 'player' && round.over.reason === 'exploded' ? 1 : 0),
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

/** 命中率(0..1;没开枪是 0) */
export function accuracyOf(stats: MatchStats): number {
  return stats.shots === 0 ? 0 : stats.hits / stats.shots
}
