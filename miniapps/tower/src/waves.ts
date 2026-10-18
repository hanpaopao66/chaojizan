// 波次调度:一波里的怪怎么排进时间轴、清完一波给多少金币、无尽模式的波次生成。
// 纯数据变换,和界面无关;engine.ts 按这里排好的时间表出怪。
import { PREP_TIME, enemyDef, endlessHealthScale, healthScale } from './data'
import { ENDLESS, waveCount } from './levels'
import type { EnemyKind, LevelDef, Spawn, WaveDef, WaveGroup } from './types'

/** 一波开始前的准备时间 */
export function prepOf(wave: WaveDef | undefined): number {
  return wave?.prep ?? PREP_TIME
}

/** 清完第 n 波(1 开始)给的金币:10 + 波次 × 2 */
export function waveReward(wave: number): number {
  return 10 + wave * 2
}

/** 把一波的组展开成一只只怪的时间表(按时间排好;同刻的按组顺序) */
export function buildSpawns(wave: WaveDef): Spawn[] {
  const spawns: Spawn[] = []
  wave.groups.forEach((g, gi) => {
    const gap = Math.max(0.05, g.gap)
    for (let i = 0; i < g.count; i++) {
      spawns.push({ kind: g.kind, at: (g.delay || 0) + i * gap + gi * 1e-4, path: g.path || 0 })
    }
  })
  spawns.sort((a, b) => a.at - b.at)
  return spawns
}

/** 这一波的怪一共有几只 */
export function waveUnits(wave: WaveDef): number {
  return wave.groups.reduce((sum, g) => sum + g.count, 0)
}

/** 这一波里有没有 Boss */
export function hasBoss(wave: WaveDef): boolean {
  return wave.boss === true || wave.groups.some((g) => enemyDef(g.kind).boss)
}

/** 血量成长:普通关卡按关卡和波次,无尽模式按自己的公式 */
export function hpScaleOf(levelId: number | 'endless', wave: number): number {
  if (levelId === 'endless') return endlessHealthScale(wave)
  return healthScale(wave, levelId)
}

/** 第 n 波(1 开始)的定义;无尽模式现场生成,别的关卡查表 */
export function waveAt(level: LevelDef, wave: number): WaveDef {
  if (level.id === 'endless') return endlessWave(wave)
  return level.waves[wave - 1] || { groups: [] }
}

/** 下一波的准备时间(下一波是 boss 波时多给 1 秒,给玩家反应时间) */
export function prepForNext(level: LevelDef, nextWave: number): number {
  if (nextWave > waveCount(level)) return 0
  const w = waveAt(level, nextWave)
  return prepOf(w) + (hasBoss(w) ? 1 : 0)
}

/** 无尽模式:第 n 波的组合(固定公式,不用随机,便于复现与测试) */
export function endlessWave(n: number): WaveDef {
  const w = Math.max(1, Math.floor(n))
  const groups: WaveGroup[] = []
  const dual = w >= 10
  const pathOf = (i: number): number => (dual ? i % 2 : 0)
  const add = (kind: EnemyKind, count: number, gap: number, delay: number, i: number): void => {
    if (count > 0) groups.push({ kind, count, gap, delay, path: pathOf(i) })
  }
  // 地面波:数量随波次缓慢增长;空中虫第 9 波起才出现,而且每次只有一两只,
  // 用来逼玩家带能打空中的塔,而不是靠海量飞行虫硬堆难度。
  add('worm', 6 + Math.floor(w * 0.55), 0.7, 0, 0)
  if (w >= 2) add('flea', 4 + Math.floor(w * 0.35), 0.5, 0.5, 1)
  if (w >= 3) add('ant', 3 + Math.floor(w * 0.3), 1.0, 1.0, 2)
  if (w >= 4) add('beetle', 2 + Math.floor(w * 0.28), 1.0, 1.5, 3)
  if (w >= 5) add('pupa', 1 + Math.floor(w / 6), 1.6, 2.0, 4)
  if (w >= 9) add('moth', 1 + Math.floor(w / 12), 1.4, 2.5, 5)
  if (w >= 9) add('wasp', 1, 1.6, 3.0, 6)
  if (w % 5 === 0) {
    groups.push({ kind: 'boss', count: 1, gap: 2, delay: 4, path: 0 })
    if (dual) groups.push({ kind: 'boss', count: Math.floor(w / 10), gap: 2, delay: 7, path: 1 })
  }
  return { groups, boss: w % 5 === 0 }
}

/** 无尽模式到第 n 波为止累计出过多少只虫(界面/测试用) */
export function endlessTotalUnits(n: number): number {
  let sum = 0
  for (let i = 1; i <= n; i++) sum += waveUnits(endlessWave(i))
  return sum
}

/** 无尽模式第 n 波的血量倍率(测试与界面说明用) */
export function endlessScaleOf(n: number): number {
  return hpScaleOf('endless', n)
}

/** 关卡的全部波次(含无尽现场生成的前 n 波) */
export function wavesOf(level: LevelDef, upTo?: number): WaveDef[] {
  if (level.id === 'endless') {
    const n = upTo ?? 20
    const out: WaveDef[] = []
    for (let i = 1; i <= n; i++) out.push(endlessWave(i))
    return out
  }
  return level.waves.slice(0, upTo)
}

/** 第 12 关通关后才解锁无尽模式 */
export const ENDLESS_LEVEL = ENDLESS
export const ENDLESS_UNLOCK_LEVEL = 12
