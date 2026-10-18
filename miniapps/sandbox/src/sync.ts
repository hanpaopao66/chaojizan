// 存档对账的纯函数:云/本机合并、v1 旧档迁移。放这里是为了能单测(main.ts 只负责调用)。
import { copyProfile, mergeProfile, type Profile } from './profile'
import type { LegacyStats } from './save'

/** 从 v1 旧存档里取出挖/放统计(没有或者坏了返回 null) */
export function legacyOf(state: { legacy?: LegacyStats } | null | undefined): LegacyStats | null {
  const l = state?.legacy
  if (!l) return null
  if (!Number.isFinite(l.mined) || !Number.isFinite(l.placed)) return null
  return { mined: Math.max(0, Math.floor(l.mined)), placed: Math.max(0, Math.floor(l.placed)) }
}

/** 两份 legacy 取较大值(本机档和云档可能都带着 v1 统计) */
export function mergeLegacy(a: LegacyStats | null, b: LegacyStats | null): LegacyStats | null {
  if (!a) return b
  if (!b) return a
  return { mined: Math.max(a.mined, b.mined), placed: Math.max(a.placed, b.placed) }
}

/**
 * v1→v2 迁移:把旧存档里的挖/放统计并进档案。
 * - 幂等:对应字段已经有数字就不再动,不会重复计数;
 * - 不改存档时间戳(at),避免旧本机档因为「迁移」变成最新、把另一台设备较新的云档盖掉。
 */
export function migrateLegacy(profile: Profile, legacy: LegacyStats | null): { profile: Profile; changed: boolean } {
  if (!legacy) return { profile, changed: false }
  const next = copyProfile(profile)
  let changed = false
  if (next.mined === 0 && legacy.mined > 0) {
    next.mined = legacy.mined
    changed = true
  }
  if (next.placed === 0 && legacy.placed > 0) {
    next.placed = legacy.placed
    changed = true
  }
  return changed ? { profile: next, changed } : { profile, changed: false }
}

/**
 * 写回云端的档案必须先和云端的合并:
 * SaveSlot.setBest 是「替换」语义,直接拿本机(可能是云对账前拷的旧)档案写回,
 * 会把云端较新的统计/成就盖掉。这里统一走 merge(统计取大、成就并集)。
 */
export function profileForWrite(slotBest: Profile, gameProfile: Profile): Profile {
  return mergeProfile(slotBest, gameProfile)
}
