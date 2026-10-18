// 世界生成的不变量:同种子可复现、地层结构正确、出生点安全、树长得像树。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AIR, BEDROCK, GRASS, LEAVES, LOG, SAND, STONE, WATER } from '../src/blocks'
import { D, H, SEA_LEVEL, W, colIndex, generateWorld, parseSeed, seedText, terrainHeight, voxelIndex } from '../src/worldgen'

/** FNV-1a:比 deepEqual 两个 78 万字节的数组快得多 */
function checksum(bytes: Uint8Array): number {
  let h = 2166136261
  for (let i = 0; i < bytes.length; i++) {
    h ^= bytes[i]
    h = Math.imul(h, 16777619) >>> 0
  }
  return h
}

function count(blocks: Uint8Array, id: number): number {
  let n = 0
  for (let i = 0; i < blocks.length; i++) if (blocks[i] === id) n++
  return n
}

test('世界生成:同种子同一座岛,换种子就不一样', () => {
  const a = generateWorld(20261018)
  const b = generateWorld(20261018)
  assert.equal(checksum(a.blocks), checksum(b.blocks))
  assert.deepEqual(a.spawn, b.spawn)
  assert.equal(a.yaw, b.yaw)
  const c = generateWorld(20261019)
  assert.notEqual(checksum(a.blocks), checksum(c.blocks))
  // 同一个种子多次调用地形高度也稳定
  assert.equal(terrainHeight(20261018, 64, 64), terrainHeight(20261018, 64, 64))
  // 岛心是陆地、边角是海,高度不一样
  assert.notEqual(terrainHeight(20261018, 64, 64), terrainHeight(20261018, 0, 0))
})

test('地形高度:在合理范围内,和生成结果里的高度表一致', () => {
  const g = generateWorld(77)
  for (let z = 0; z < D; z += 7) {
    for (let x = 0; x < W; x += 7) {
      const h = g.heights[colIndex(x, z)]
      assert.ok(h >= 4 && h <= H - 12, `(${x},${z}) 高度 ${h}`)
      assert.equal(terrainHeight(77, x, z), h)
    }
  }
})

test('地层不变量:底下两层基岩、每列有实心底座、水只会出现在海平面以下', () => {
  const g = generateWorld(4242)
  const layer = W * D
  for (let col = 0; col < layer; col++) {
    assert.equal(g.blocks[col], BEDROCK, `第 ${col} 列 y=0 不是基岩`)
    assert.equal(g.blocks[col + layer], BEDROCK, `第 ${col} 列 y=1 不是基岩`)
    assert.notEqual(g.blocks[col + layer * 2], AIR, `第 ${col} 列 y=2 是空的`)
  }
  let waterAbove = 0
  for (let y = SEA_LEVEL; y < H; y++) {
    for (let i = 0; i < layer; i++) if (g.blocks[i + layer * y] === WATER) waterAbove++
  }
  assert.equal(waterAbove, 0, '海平面以上不应该有水')
  // 海的面积不小,而且岸上有沙滩和草地
  assert.ok(count(g.blocks, WATER) > 20000, '水太少')
  assert.ok(count(g.blocks, SAND) > 5000, '沙滩太少')
  assert.ok(count(g.blocks, GRASS) > 2500, '草地太少')
  // 所有编号都在合法范围内
  for (let i = 0; i < g.blocks.length; i++) assert.ok(g.blocks[i] <= BEDROCK, `非法方块编号 ${g.blocks[i]}`)
})

test('海:地形低于海平面的格子会被水填满,高处没有水', () => {
  const g = generateWorld(999)
  for (let z = 0; z < D; z += 5) {
    for (let x = 0; x < W; x += 5) {
      const h = g.heights[colIndex(x, z)]
      const top = g.blocks[voxelIndex(x, h - 1, z)]
      if (h < SEA_LEVEL) {
        // 水下的地表应该是沙,上面到海平面全是水
        assert.equal(top, SAND, `(${x},${z}) 水底不是沙`)
        for (let y = h; y < SEA_LEVEL; y++) {
          assert.equal(g.blocks[voxelIndex(x, y, z)], WATER, `(${x},${y},${z}) 没水`)
        }
        assert.equal(g.blocks[voxelIndex(x, SEA_LEVEL, z)], AIR)
      } else if (h > SEA_LEVEL + 1) {
        assert.notEqual(top, WATER)
      }
    }
  }
})

test('树:有树干也有树冠,树干站在草地上', () => {
  const g = generateWorld(31415)
  assert.ok(count(g.blocks, LOG) > 200, `树干太少:${count(g.blocks, LOG)}`)
  assert.ok(count(g.blocks, LEAVES) > 2000, `树叶太少:${count(g.blocks, LEAVES)}`)
  let found = 0
  for (let z = 1; z < D - 1 && found < 8; z++) {
    for (let x = 1; x < W - 1 && found < 8; x++) {
      for (let y = 2; y < H - 1; y++) {
        if (g.blocks[voxelIndex(x, y, z)] !== LOG) continue
        if (g.blocks[voxelIndex(x, y - 1, z)] !== GRASS) continue
        // 树根:上面至少还有两格树干,再上面有树叶
        assert.equal(g.blocks[voxelIndex(x, y + 1, z)], LOG)
        let leaf = false
        for (let dy = 2; dy <= 8 && !leaf; dy++) {
          for (let dz = -2; dz <= 2 && !leaf; dz++) {
            for (let dx = -2; dx <= 2 && !leaf; dx++) {
              if (g.blocks[voxelIndex(x + dx, y + dy, z + dz)] === LEAVES) leaf = true
            }
          }
        }
        assert.ok(leaf, `(${x},${y},${z}) 树干上没有树叶`)
        found++
        break
      }
    }
  }
  assert.equal(found, 8, '没找到足够的树')
  // 石头出现在石丘上
  assert.ok(count(g.blocks, STONE) > 1000, '石头太少')
})

test('出生点:高出海面、脚下是实心方块、头顶三格是空的', () => {
  for (const seed of [1, 2, 3, 12345, 0xffffffff]) {
    const g = generateWorld(seed)
    const { x, y, z } = g.spawn
    assert.equal(x % 1, 0.5)
    assert.equal(z % 1, 0.5)
    const bx = Math.floor(x)
    const bz = Math.floor(z)
    assert.ok(y > SEA_LEVEL + 2, `种子 ${seed} 出生点太低:${y}`)
    assert.equal(g.blocks[voxelIndex(bx, y - 1, bz)], GRASS, `种子 ${seed} 脚下不是草地`)
    for (let dy = 0; dy < 3; dy++) {
      assert.equal(g.blocks[voxelIndex(bx, y + dy, bz)], AIR, `种子 ${seed} 头顶被挡`)
    }
    assert.ok(Number.isFinite(g.yaw))
    // 身边一格之内高差不超过一层(走起来不别扭)
    const col = colIndex(Math.floor(x), Math.floor(z))
    for (const other of [col - 1, col + 1, col - W, col + W]) {
      const diff = g.heights[other] - Math.floor(y)
      assert.ok(diff >= -1 && diff <= 1, `种子 ${seed} 出生点旁边有陡坎:${diff}`)
    }
  }
})

test('种子的解析和展示:十进制、36 进制都行,坏输入返回 null', () => {
  assert.equal(parseSeed('12345'), 12345)
  assert.equal(parseSeed('  0 '), 0)
  assert.equal(parseSeed('5f'), parseInt('5f', 36))
  assert.equal(parseSeed(''), null)
  assert.equal(parseSeed('-3'), null)
  assert.equal(parseSeed('4294967296'), null)
  assert.equal(parseSeed('hello world'), null)
  assert.equal(seedText(4294967295), '4294967295')
})
