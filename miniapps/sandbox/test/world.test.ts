// 世界状态与编辑:稀疏编辑表的增删、容量上限、序列化、位图维护。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AIR, BEDROCK, GLASS, GRASS, STONE, WATER } from '../src/blocks'
import { MAX_EDITS, World, decodeEdits, encodeEdits } from '../src/world'
import { H, W } from '../src/worldgen'

function fresh(): World {
  return new World(2026)
}

test('编辑串:空表、往返、排序', () => {
  assert.equal(encodeEdits(new Map()), '')
  assert.deepEqual(decodeEdits(''), [])
  const edits = new Map<number, number>([[40000, 3], [50000, 0], [70000, 9]])
  const text = encodeEdits(edits)
  const back = decodeEdits(text)
  assert.ok(back)
  assert.deepEqual(new Map(back), edits)
  // 按下标升序,差值为正
  assert.deepEqual(back!.map(([i]) => i), [40000, 50000, 70000])
})

test('编辑串:坏数据一律拒绝', () => {
  assert.equal(decodeEdits('x:3'), null)
  assert.equal(decodeEdits('1'), null)
  assert.equal(decodeEdits('1:3:4'), null)
  assert.equal(decodeEdits('1:g'), null) // 方块编号 16,超范围
  assert.equal(decodeEdits('0:3'), null) // 差值为 0(重复)
  assert.equal(decodeEdits('2:3'), null) // 编号 2 在第 0 层:基岩层不能编辑
  assert.equal(decodeEdits('zzzzzz:3'), null) // 越界
  assert.equal(decodeEdits(('1:3,').repeat(MAX_EDITS + 1)), null)
  assert.equal(decodeEdits(('a:3,').repeat(20000) + 'x'), null)
})

test('放方块/挖方块:改回生成时的样子会删掉编辑,不占容量', () => {
  const w = fresh()
  // 找一处生成时是空气的高空
  const x = 40
  const z = 40
  let y = H - 1
  while (y > 2 && w.blockAt(x, y, z) !== AIR) y--
  assert.equal(w.blockAt(x, y, z), AIR)
  assert.equal(w.setBlock(x, y, z, STONE), 'ok')
  assert.equal(w.blockAt(x, y, z), STONE)
  assert.equal(w.editCount, 1)
  // 再放一次一样的是「没变化」
  assert.equal(w.setBlock(x, y, z, STONE), 'same')
  // 放回空气 = 恢复生成结果 → 编辑删除
  assert.equal(w.setBlock(x, y, z, AIR), 'ok')
  assert.equal(w.editCount, 0)
  assert.equal(w.blockAt(x, y, z), AIR)
})

test('挖掉生成的方块再放回去,编辑也会消失', () => {
  const w = fresh()
  // 找一列地表
  const x = Math.floor(w.spawn.x)
  const z = Math.floor(w.spawn.z)
  const top = w.topAt(x, z)
  assert.ok(top > 2)
  const old = w.blockAt(x, top, z)
  assert.equal(w.setBlock(x, top, z, AIR), 'ok')
  assert.equal(w.blockAt(x, top, z), AIR)
  assert.equal(w.editCount, 1)
  assert.equal(w.setBlock(x, top, z, old), 'ok')
  assert.equal(w.editCount, 0)
  assert.equal(w.blockAt(x, top, z), old)
})

test('基岩和越界不能编辑', () => {
  const w = fresh()
  assert.equal(w.setBlock(10, 0, 10, AIR), 'bedrock')
  assert.equal(w.setBlock(10, 1, 10, GRASS), 'bedrock')
  assert.equal(w.setBlock(-1, 10, 10, STONE), 'outside')
  assert.equal(w.setBlock(W, 10, 10, STONE), 'outside')
  assert.equal(w.setBlock(10, H, 10, STONE), 'outside')
  assert.equal(w.editCount, 0)
})

test('编辑数到上限:新的改动被拒绝,删掉一条又能继续', () => {
  const w = fresh()
  let made = 0
  let last: [number, number, number] | null = null
  outer:
  for (let y = H - 1; y >= 2; y--) {
    for (let z = 2; z < 30; z++) {
      for (let x = 2; x < 30; x++) {
        if (w.blockAt(x, y, z) !== AIR) continue
        if (w.setBlock(x, y, z, GLASS) !== 'ok') break outer
        made++
        last = [x, y, z]
        if (made === MAX_EDITS) break outer
      }
    }
  }
  assert.equal(made, MAX_EDITS)
  // 再改一格新的:满了,拒绝,世界不变
  let extra: [number, number, number] | null = null
  outer2:
  for (let y = H - 1; y >= 2; y--) {
    for (let z = 2; z < 30; z++) {
      for (let x = 2; x < 30; x++) {
        if (w.blockAt(x, y, z) === AIR) {
          extra = [x, y, z]
          break outer2
        }
      }
    }
  }
  assert.ok(extra)
  assert.equal(w.setBlock(extra[0], extra[1], extra[2], STONE), 'full')
  assert.equal(w.blockAt(extra[0], extra[1], extra[2]), AIR)
  // 删掉刚才最后一条,又能加
  assert.ok(last)
  assert.equal(w.setBlock(last[0], last[1], last[2], AIR), 'ok')
  assert.equal(w.editCount, MAX_EDITS - 1)
  assert.equal(w.setBlock(extra[0], extra[1], extra[2], STONE), 'ok')
  assert.equal(w.editCount, MAX_EDITS)
  // 序列化后的长度远小于 64000
  assert.ok(w.serializeEdits().length < 60000, `编辑串 ${w.serializeEdits().length} 字符`)
})

test('编辑会更新渲染位图:最高方块、实心/水的标记', () => {
  const w = fresh()
  const x = 20
  const z = 20
  const top = w.topAt(x, z)
  assert.ok(top > 2)
  const col = x + W * z
  const before = w.topAt(x, z)
  assert.equal(w.setBlock(x, top, z, AIR), 'ok')
  assert.ok(w.topAt(x, z) < before, '挖掉最高的方块后最高点应该下降')
  // 挖出来的空位不再是实心
  const y = top
  const bit = y < 32 ? 1 << y : 1 << (y - 32)
  const mask = y < 32 ? w.opaqueLo[col] : w.opaqueHi[col]
  assert.equal(mask & bit, 0)
  // 再放一块石头:最高点回到 y
  assert.equal(w.setBlock(x, y, z, STONE), 'ok')
  assert.equal(w.topAt(x, z), top)
  // 水:找一格海里的水,它的列位图上应该带水标记
  let waterCol = -1
  for (let c = 0; c < W * 128; c++) {
    if ((w.waterLo[c] | w.waterHi[c]) !== 0) { waterCol = c; break }
  }
  assert.ok(waterCol >= 0, '世界里应该有水')
  // 位图里水的标记和 blocks 对得上
  const wc = waterCol
  const wy = w.waterLo[wc] ? 31 - Math.clz32(w.waterLo[wc] & -w.waterLo[wc]) : 32 + 31 - Math.clz32(w.waterHi[wc] & -w.waterHi[wc])
  const wcz = Math.floor(wc / W)
  const wcx = wc % W
  assert.equal(w.blockAt(wcx, wy, wcz), WATER)
})

test('loadEdits:合法数据能灌进去,坏数据返回 false 且不破坏当前世界', () => {
  const w = fresh()
  const x = 40
  const z = 40
  let y = H - 1
  while (y > 2 && w.blockAt(x, y, z) !== AIR) y--
  assert.equal(w.setBlock(x, y, z, STONE), 'ok')
  const text = w.serializeEdits()
  assert.equal(w.loadEdits(''), true)
  assert.equal(w.editCount, 0)
  assert.equal(w.blockAt(x, y, z), AIR)
  assert.equal(w.loadEdits(text), true)
  assert.equal(w.blockAt(x, y, z), STONE)
  assert.equal(w.loadEdits('bad'), false)
  assert.equal(w.blockAt(x, y, z), STONE, '坏档不该清掉已有编辑')
  assert.ok(w.blockAt(5, 0, 5) === BEDROCK)
})
