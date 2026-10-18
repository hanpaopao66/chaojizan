// 存档:往返、坏档容错、64 KB 上限、编辑串长度。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { MAX_STACK, newSave, loadSave, saveBytes, saveOf } from '../src/save'
import { MAX_EDITS, encodeEdits } from '../src/world'
import { spawnForTest } from './helpers'

const spawn = spawnForTest(10, 12.5, 20.5)

test('新存档:默认值合理,写出去再读回来一模一样', () => {
  const s = newSave(123456, spawn, 1.2)
  assert.equal(s.seed, 123456)
  assert.equal(s.edits, '')
  assert.deepEqual(s.player, { x: 12.5, y: 10, z: 20.5, yaw: 1.2, pitch: 0 })
  assert.equal(s.inv.length, 9)
  assert.deepEqual(s.inv, new Array(9).fill(10))
  assert.equal(s.time, 0.06)
  const back = loadSave(JSON.parse(JSON.stringify(saveOf(s))))
  assert.deepEqual(back, s)
})

test('坏存档一律返回 null(界面当作新世界),不会崩', () => {
  const good = saveOf(newSave(7, spawn, 0)) as Record<string, unknown>
  const bad = (patch: Record<string, unknown>): unknown => loadSave({ ...good, ...patch })
  assert.equal(loadSave(null), null)
  assert.equal(loadSave('garbage'), null)
  assert.equal(loadSave({}), null)
  assert.equal(bad({ v: 2 }), null)
  assert.equal(bad({ seed: -1 }), null)
  assert.equal(bad({ seed: 1.5 }), null)
  assert.equal(bad({ seed: 2 ** 33 }), null)
  assert.equal(bad({ edits: 5 }), null)
  assert.equal(bad({ edits: 'x:3' }), null)
  assert.equal(bad({ edits: '0:3' }), null)
  assert.equal(bad({ player: null }), null)
  assert.equal(bad({ player: { x: 1, y: 1, z: 1, yaw: 0, pitch: Number.NaN } }), null)
  assert.equal(bad({ player: { x: 999, y: 10, z: 1, yaw: 0, pitch: 0 } }), null)
  assert.equal(bad({ player: { x: 1, y: 999, z: 1, yaw: 0, pitch: 0 } }), null)
  assert.equal(bad({ player: { x: 1, y: 10, z: 1, yaw: 0, pitch: 3 } }), null)
  assert.equal(bad({ time: 1 }), null)
  assert.equal(bad({ time: -0.1 }), null)
  assert.equal(bad({ inv: [1, 2, 3] }), null)
  assert.equal(bad({ inv: new Array(9).fill(0).map((_, i) => (i === 0 ? -1 : 0)) }), null)
  assert.equal(bad({ inv: new Array(9).fill(MAX_STACK + 1) }), null)
  assert.equal(bad({ hot: 9 }), null)
  assert.equal(bad({ hot: -1 }), null)
  assert.equal(bad({ mined: -1 }), null)
  assert.equal(bad({ placed: 1.5 }), null)
})

test('合法边界值读得出来', () => {
  const s = newSave(0xffffffff, spawn, -2.5)
  s.player.pitch = -1.5
  s.time = 0.999999
  s.hot = 8
  s.inv = new Array(9).fill(0)
  s.inv[0] = MAX_STACK
  s.mined = 1e9
  s.placed = 1e9
  const back = loadSave(JSON.parse(JSON.stringify(saveOf(s))))
  assert.deepEqual(back, s)
})

test('4000 条编辑的存档远小于云端单个值的 64 KB 上限', () => {
  // 最坏情况:编辑分散在整张地图,下标差最大
  const edits = new Map<number, number>()
  // 只允许编辑 y >= 2 的格子(下标从 2*W*D 开始)
  let index = 2 * 128 * 128
  while (edits.size < MAX_EDITS) {
    edits.set(index, edits.size % 11)
    index += 7
  }
  const text = encodeEdits(edits)
  const s = newSave(1, spawn, 0)
  s.edits = text
  const bytes = saveBytes(s)
  assert.ok(bytes < 64 * 1024, `存档 ${bytes} 字节,超过 64 KB`)
  assert.ok(text.length < 40000, `编辑串 ${text.length} 字符`)
  const back = loadSave(JSON.parse(JSON.stringify(saveOf(s))))
  assert.ok(back)
  assert.equal(back!.edits, text)
})
