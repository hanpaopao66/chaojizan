// 世界存档格式与校验。纯函数,坏档一律返回 null(界面当作新世界)。
//
// 云端的 state 只存**这个世界本身**:
//   seed     世界种子,决定整座岛的样子
//   edits    稀疏编辑串(只记和生成结果不一样的格子,格式见 world.ts)
//   player   位置和朝向
//   time     世界时间 0..1
//   inv      九种方块的数量
//   hot      选中的快捷栏下标
// 跨局/跨设备的累计统计与成就放在 SaveSlot 的 best 槽里(= profile.ts),因为那边是「合并」语义。
// 单个云端值上限 64 KB:编辑串最大 6 万字符,加上其余字段远低于上限。
//
// v1(1.0.0)存档把 mined/placed 也放在 state 里;loadSave 会把它读成 v2,
// 并把旧统计放进 `legacy` 字段,由 main.ts 在档案为空时迁移过去。
import { STARTER_COUNTS } from './blocks'
import { DAY, LIMITS } from './data'
import { D, H, W, type Spawn } from './worldgen'
import { decodeEdits } from './world'

/** 1.0.0 存档里的挖/放统计(迁移用) */
export interface LegacyStats {
  mined: number
  placed: number
}

export interface SavedPlayer {
  x: number
  y: number
  z: number
  yaw: number
  pitch: number
}

export interface GameSave {
  v: 2
  seed: number
  edits: string
  player: SavedPlayer
  time: number
  inv: number[]
  hot: number
  /** 只在读旧 v1 存档时出现,用来把旧统计迁移进 profile;不会写回去 */
  legacy?: LegacyStats
}

/** 背包数量上限(和 data.ts 的 LIMITS.MAX_STACK 一致;保留这个导出给旧测试用) */
export const MAX_STACK = LIMITS.MAX_STACK

export function newSave(seed: number, spawn: Spawn, yaw: number): GameSave {
  return {
    v: 2,
    seed: seed >>> 0,
    edits: '',
    player: { x: spawn.x, y: spawn.y, z: spawn.z, yaw, pitch: 0 },
    time: DAY.START,
    inv: STARTER_COUNTS.slice(),
    // 默认选中木板(第 7 格):开局只有木板/玻璃/砖能放,选一个能立刻用的
    hot: 6,
  }
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

function readInv(raw: unknown): number[] | null {
  if (!Array.isArray(raw) || raw.length !== STARTER_COUNTS.length) return null
  const out: number[] = []
  for (const v of raw) {
    if (!isNum(v) || !Number.isInteger(v) || v < 0 || v > MAX_STACK) return null
    out.push(v)
  }
  return out
}

/** 云端原始值 → GameSave。v2 与 v1 都收;任何字段不对返回 null(坏档容错)。 */
export function loadSave(raw: unknown): GameSave | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (r.v !== 1 && r.v !== 2) return null
  const seed = r.seed
  if (!isNum(seed) || !Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) return null
  const edits = r.edits
  if (typeof edits !== 'string' || edits.length > LIMITS.MAX_EDITS_TEXT) return null
  // 编辑串格式(越界、重复、条数超限)在这里就判掉;真正灌进世界时 world 还会再校一遍
  if (!decodeEdits(edits)) return null
  const p = r.player
  if (!p || typeof p !== 'object') return null
  const pp = p as Record<string, unknown>
  if (!isNum(pp.x) || !isNum(pp.y) || !isNum(pp.z) || !isNum(pp.yaw) || !isNum(pp.pitch)) return null
  if (pp.x < 0 || pp.x > W || pp.z < 0 || pp.z > D) return null
  if (pp.y < -8 || pp.y > H + 4) return null
  const pitch = pp.pitch as number
  if (pitch < -1.6 || pitch > 1.6) return null
  const time = r.time
  if (!isNum(time) || time < 0 || time >= 1) return null
  const inv = readInv(r.inv)
  if (!inv) return null
  const hot = r.hot
  if (!isNum(hot) || !Number.isInteger(hot) || hot < 0 || hot > STARTER_COUNTS.length - 1) return null
  const save: GameSave = {
    v: 2,
    seed: seed >>> 0,
    edits,
    player: { x: pp.x, y: pp.y, z: pp.z, yaw: pp.yaw, pitch },
    time,
    inv,
    hot,
  }
  if (r.v === 1) {
    const mined = r.mined
    const placed = r.placed
    if (isNum(mined) && Number.isInteger(mined) && mined >= 0 && mined <= 1e9
      && isNum(placed) && Number.isInteger(placed) && placed >= 0 && placed <= 1e9) {
      save.legacy = { mined, placed }
    }
  }
  return save
}

/** GameSave → 可以直接 JSON.stringify 的普通对象 */
export function saveOf(s: GameSave): unknown {
  return {
    v: 2,
    seed: s.seed >>> 0,
    edits: s.edits,
    player: { x: s.player.x, y: s.player.y, z: s.player.z, yaw: s.player.yaw, pitch: s.player.pitch },
    time: s.time,
    inv: s.inv.slice(),
    hot: s.hot,
  }
}

/** 序列化后的字节数(界面在接近上限时提示用);UTF-8 里这些字符都是单字节 */
export function saveBytes(s: GameSave): number {
  return JSON.stringify(saveOf(s)).length
}
