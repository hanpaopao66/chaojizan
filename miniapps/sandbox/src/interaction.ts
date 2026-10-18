// 挖 / 放的手感状态机:挖掘进度、松手/换目标取消、放置冷却。纯函数,单测覆盖。
//
// 放在这里而不是主循环里,是为了让「按住多久挖穿、换目标会不会重置、两次放置隔多久」
// 这些手感参数都能用固定步长测出来;参数本身在 data.ts 的 FEEL 里。
import { breakTime } from './blocks'
import { FEEL } from './data'

export interface MineState {
  /** 当前对准的方块(坐标拼成的字符串);空串 = 没对准 */
  targetKey: string
  /** 0..1 的挖掘进度 */
  progress: number
  /** 距离下一次「沙沙」声还剩多少秒(界面拿去决定要不要出声) */
  soundWait: number
}

export function newMineState(): MineState {
  return { targetKey: '', progress: 0, soundWait: 0 }
}

export interface MineTick {
  /** 这一帧挖穿了;调用方负责真的删方块、加背包 */
  broke: boolean
  /** 这一帧该响一声「沙沙」 */
  tickSound: boolean
  /** 进度或目标变了(界面要刷新进度条) */
  changed: boolean
}

/**
 * 推进挖掘状态。targetKey 为 null 或没按住就取消;换目标也会把进度清零。
 * 传进来的 block 是当前瞄准的方块编号;hardness = Infinity(基岩)时进度不动。
 */
export function tickMining(state: MineState, targetKey: string | null, holding: boolean,
  block: number, inWater: boolean, dt: number): MineTick {
  const out: MineTick = { broke: false, tickSound: false, changed: false }
  const step = Math.max(0, dt)
  if (!holding || !targetKey) {
    if (state.targetKey !== '' || state.progress !== 0) {
      state.targetKey = ''
      state.progress = 0
      out.changed = true
    }
    state.soundWait = 0
    return out
  }
  if (targetKey !== state.targetKey) {
    state.targetKey = targetKey
    state.progress = 0
    state.soundWait = 0
    out.changed = true
  }
  const hardness = breakTime(block, inWater)
  if (!Number.isFinite(hardness) || hardness <= 0) return out
  const before = state.progress
  state.progress += step / hardness
  state.soundWait -= step
  if (state.soundWait <= 0) {
    state.soundWait = FEEL.MINE_SOUND_INTERVAL
    out.tickSound = true
  }
  if (state.progress >= 1) {
    state.progress = 0
    state.targetKey = ''
    state.soundWait = 0
    out.broke = true
    out.changed = true
    return out
  }
  if (state.progress !== before) out.changed = true
  return out
}

/** 两次放置之间至少隔 PLACE_COOLDOWN 秒,防止连点/触屏手抖一口气放一排 */
export function canPlace(cooldown: number): boolean {
  return cooldown <= 0
}

export function tickPlaceCooldown(cooldown: number, dt: number): number {
  return Math.max(0, cooldown - Math.max(0, dt))
}

export function newPlaceCooldown(): number {
  return FEEL.PLACE_COOLDOWN
}

/**
 * 连续挖掘计数:按住挖键每挖掉一块 +1;松开挖键或放置方块就归零。
 * 「一口气」成就需要 50。
 */
export function nextStreak(streak: number, holding: boolean, justBroke: boolean, justPlaced: boolean): number {
  if (justPlaced) return 0
  if (!holding) return 0
  return justBroke ? streak + 1 : streak
}
