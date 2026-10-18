// 存档格式与校验。纯函数,坏档一律返回 null(界面当作新世界)。
//
// 云端只存一份 state:
//   seed     世界种子,决定整座岛的样子
//   edits    稀疏编辑串(只记和生成结果不一样的格子,格式见 world.ts)
//   player   位置和朝向
//   time     世界时间 0..1
//   inv      九种方块的数量
//   hot      选中的快捷栏下标
//   mined/placed 挖过/放过多少方块
// 单个云端值上限 64 KB:编辑串最大 6 万字符,加上其余字段远低于上限。
import { STARTER_COUNTS } from './blocks'
import { D, H, W, type Spawn } from './worldgen'
import { MAX_EDITS_TEXT, decodeEdits } from './world'

export interface SavedPlayer {
  x: number
  y: number
  z: number
  yaw: number
  pitch: number
}

export interface GameSave {
  v: 1
  seed: number
  edits: string
  player: SavedPlayer
  time: number
  inv: number[]
  hot: number
  mined: number
  placed: number
}

/** 背包数量上限:防止坏档写出巨大数字(也保证存档很小) */
export const MAX_STACK = 9999

export function newSave(seed: number, spawn: Spawn, yaw: number): GameSave {
  return {
    v: 1,
    seed: seed >>> 0,
    edits: '',
    player: { x: spawn.x, y: spawn.y, z: spawn.z, yaw, pitch: 0 },
    time: 0.06,
    inv: STARTER_COUNTS.slice(),
    hot: 0,
    mined: 0,
    placed: 0,
  }
}

export function newGame(seed: number, spawn: Spawn, yaw: number): GameSave {
  return newSave(seed, spawn, yaw)
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

/** 云端的原始值 → GameSave;任何字段不对都返回 null(坏档容错) */
export function loadSave(raw: unknown): GameSave | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (r.v !== 1) return null
  const seed = r.seed
  if (!isNum(seed) || !Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) return null
  const edits = r.edits
  if (typeof edits !== 'string' || edits.length > MAX_EDITS_TEXT) return null
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
  const mined = r.mined
  const placed = r.placed
  if (!isNum(mined) || !Number.isInteger(mined) || mined < 0 || mined > 1e9) return null
  if (!isNum(placed) || !Number.isInteger(placed) || placed < 0 || placed > 1e9) return null
  return {
    v: 1,
    seed: seed >>> 0,
    edits,
    player: { x: pp.x, y: pp.y, z: pp.z, yaw: pp.yaw, pitch },
    time,
    inv,
    hot,
    mined,
    placed,
  }
}

/** GameSave → 可以直接 JSON.stringify 的普通对象 */
export function saveOf(s: GameSave): unknown {
  return {
    v: s.v,
    seed: s.seed >>> 0,
    edits: s.edits,
    player: { x: s.player.x, y: s.player.y, z: s.player.z, yaw: s.player.yaw, pitch: s.player.pitch },
    time: s.time,
    inv: s.inv.slice(),
    hot: s.hot,
    mined: s.mined,
    placed: s.placed,
  }
}

/** 序列化后的字节数(界面在接近上限时提示用);UTF-8 里这些字符都是单字节 */
export function saveBytes(s: GameSave): number {
  return JSON.stringify(saveOf(s)).length
}
