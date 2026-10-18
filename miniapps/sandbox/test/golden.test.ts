// Golden 回归:世界生成必须和 **1.0.0 发布版** 逐字节一致。
//
// 为什么:存档只存 seed + 稀疏编辑;如果同一个 seed 生成出来的树变了,旧档里树屋/树旁的
// 建筑就会悬空或卡进树里。所以地形和树的位置不许随版本改。
//
// golden 值的来源:用 1.0.0 提交 `96dcc3b1:miniapps/sandbox/src/worldgen.ts`
// 生成同一批 seed,对 blocks / heights 取 FNV-1a 32 位哈希,再抄到这里。
// 改世界生成后这个测试会红 —— 先想清楚旧档怎么办(一般就是别改)。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { generateWorld } from '../src/worldgen'
import { TREE } from '../src/data'
import { World, encodeEdits } from '../src/world'
import { loadSave } from '../src/save'

/** FNV-1a 32 位:和 1.0 校验脚本用的是同一个 */
function fnv(bytes: Uint8Array): string {
  let h = 2166136261
  for (let i = 0; i < bytes.length; i++) {
    h ^= bytes[i]
    h = Math.imul(h, 16777619) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

interface Golden {
  seed: number
  blocks: string
  heights: string
  spawn: { x: number; y: number; z: number }
}

const GOLDEN: readonly Golden[] = [
  { seed: 20261018, blocks: '52672943', heights: '8e63f259', spawn: { x: 79.5, y: 16, z: 97.5 } },
  { seed: 4242, blocks: '9f392f38', heights: '7270f6ce', spawn: { x: 64.5, y: 13, z: 30.5 } },
  { seed: 1, blocks: 'ceded193', heights: '766741df', spawn: { x: 35.5, y: 17, z: 35.5 } },
  { seed: 777, blocks: '18209005', heights: '78695923', spawn: { x: 30.5, y: 16, z: 67.5 } },
  { seed: 0xffffffff, blocks: '84de4c25', heights: '6ab7d304', spawn: { x: 91.5, y: 17, z: 90.5 } },
  { seed: 12345, blocks: 'f62dbeac', heights: 'b47301db', spawn: { x: 63.5, y: 22, z: 63.5 } },
  { seed: 999, blocks: 'fd5f1bd8', heights: 'fe2862e8', spawn: { x: 98.5, y: 17, z: 39.5 } },
  { seed: 31337, blocks: 'a0294034', heights: '27ec7c5e', spawn: { x: 31.5, y: 15, z: 39.5 } },
]

test('世界生成 golden:和 1.0.0 发布版逐字节一致(8 个种子)', () => {
  for (const g of GOLDEN) {
    const world = generateWorld(g.seed)
    assert.equal(fnv(world.blocks), g.blocks, `seed ${g.seed} 的方块和 1.0 不一致(旧档的树屋会悬空)`)
    assert.equal(fnv(world.heights), g.heights, `seed ${g.seed} 的地形高度变了`)
    assert.deepEqual(world.spawn, g.spawn, `seed ${g.seed} 的出生点变了`)
  }
})

test('出生点留空的半径是 1.0.0 的原值 18:改了会挪动 RNG 流', () => {
  // 这一条是防手滑:它不是「参数」,是旧档兼容性的一部分。
  assert.equal(TREE.SPAWN_CLEAR_SQ, 18)
})

test('同一个 seed 多次生成完全一致;换 seed 会变', () => {
  const a = generateWorld(778899)
  const b = generateWorld(778899)
  assert.equal(fnv(a.blocks), fnv(b.blocks))
  const c = generateWorld(778900)
  assert.notEqual(fnv(a.blocks), fnv(c.blocks))
})

test('旧 v1 档升级:seed + 编辑读进新版后,世界 = 1.0 生成结果 + 原编辑,数据不丢', () => {
  // 用 golden 里的 seed 造一个「1.0 时代的存档」:只存 seed、玩家编辑、位置/背包/时间
  const seed = 20261018
  const base = generateWorld(seed)
  // 找几格高空空气来做编辑(挖掉/放砖)
  const edits = new Map<number, number>()
  let found = 0
  for (let y = 46; y >= 40 && found < 3; y--) {
    for (let z = 5; z < 20 && found < 3; z++) {
      for (let x = 5; x < 20 && found < 3; x++) {
        const idx = x + 128 * (z + 128 * y)
        if (base.blocks[idx] !== 0) continue
        edits.set(idx, found === 2 ? 10 : 0) // 两个挖空、一个放砖
        found++
      }
    }
  }
  assert.equal(edits.size, 3)
  const world = new World(seed)
  let encoded = ''
  {
    const text = encodeEdits(edits)
    encoded = text
    assert.equal(world.loadEdits(text), true)
  }
  // v1 存档原始 JSON
  const rawV1 = {
    v: 1,
    seed,
    edits: encoded,
    player: { x: 10.5, y: 20, z: 10.5, yaw: 1, pitch: 0.2 },
    time: 0.3,
    inv: [2, 0, 0, 0, 0, 0, 8, 6, 6],
    hot: 6,
    mined: 42,
    placed: 7,
  }
  const loaded = loadSave(rawV1)
  assert.ok(loaded, 'v1 档要能读出来')
  assert.equal(loaded!.v, 2)
  assert.equal(loaded!.seed, seed)
  assert.deepEqual(loaded!.player, rawV1.player)
  assert.deepEqual(loaded!.inv, rawV1.inv)
  assert.equal(loaded!.hot, 6)
  assert.equal(loaded!.time, 0.3)
  assert.deepEqual(loaded!.legacy, { mined: 42, placed: 7 })

  // 新版用同一个 seed 重新生成 + 灌入旧编辑:底座必须和 1.0 一致(golden),编辑原样生效
  const world2 = new World(seed)
  assert.equal(world2.loadEdits(loaded!.edits), true)
  assert.equal(fnv(world2.base), '52672943', '底座仍然是 1.0 的那座岛')
  for (const [index, id] of edits) {
    const y = Math.floor(index / (128 * 128))
    const rem = index - y * 128 * 128
    const z = Math.floor(rem / 128)
    const x = rem - z * 128
    assert.equal(world2.blockAt(x, y, z), id, '旧编辑要原样保留')
  }
  assert.deepEqual(world2.spawn, base.spawn)
})
