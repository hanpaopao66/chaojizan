// 存档:往返、坏档容错、64 KB 上限、编辑串长度、v1 旧档迁移。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { MAX_STACK, loadSave, newSave, saveBytes, saveOf } from '../src/save'
import { MAX_EDITS, encodeEdits } from '../src/world'
import { STARTER_COUNTS } from '../src/blocks'
import { DAY } from '../src/data'
import { spawnForTest } from './helpers'

const spawn = spawnForTest(10, 12.5, 20.5)

test('新存档:默认值合理,写出去再读回来一模一样(v2)', () => {
  const s = newSave(123456, spawn, 1.2)
  assert.equal(s.v, 2)
  assert.equal(s.seed, 123456)
  assert.equal(s.edits, '')
  assert.deepEqual(s.player, { x: 12.5, y: 10, z: 20.5, yaw: 1.2, pitch: 0 })
  assert.equal(s.time, DAY.START)
  assert.deepEqual(s.inv, STARTER_COUNTS.slice())
  assert.equal(s.inv.length, 9)
  assert.equal(s.inv[6], 8, '开局只有木板/玻璃/砖')
  assert.equal(s.inv[0], 0, '草/土/石要自己挖')
  assert.equal(s.hot, 6, '默认选中木板,开局就能放')
  const back = loadSave(JSON.parse(JSON.stringify(saveOf(s))))
  assert.deepEqual(back, s)
})

test('坏存档一律返回 null(界面当作新世界),不会崩', () => {
  const good = saveOf(newSave(7, spawn, 0)) as Record<string, unknown>
  const bad = (patch: Record<string, unknown>): unknown => loadSave({ ...good, ...patch })
  assert.equal(loadSave(null), null)
  assert.equal(loadSave('garbage'), null)
  assert.equal(loadSave({}), null)
  assert.equal(bad({ v: 3 }), null)
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
})

test('合法边界值读得出来', () => {
  const s = newSave(0xffffffff, spawn, -2.5)
  s.player.pitch = -1.5
  s.time = 0.999999
  s.hot = 8
  s.inv = new Array(9).fill(0)
  s.inv[0] = MAX_STACK
  const back = loadSave(JSON.parse(JSON.stringify(saveOf(s))))
  assert.deepEqual(back, s)
})

test('v1 旧存档:读成 v2,挖/放统计放进 legacy 供迁移,不写回去', () => {
  const s = newSave(5, spawn, 1)
  const raw = {
    v: 1,
    seed: s.seed,
    edits: '',
    player: s.player,
    time: s.time,
    inv: s.inv,
    hot: s.hot,
    mined: 42,
    placed: 7,
  }
  const back = loadSave(raw)
  assert.ok(back)
  assert.equal(back.v, 2)
  assert.deepEqual(back.legacy, { mined: 42, placed: 7 })
  assert.ok(!('mined' in (saveOf(back) as Record<string, unknown>)), 'legacy 不进新存档')
  // legacy 字段坏了就忽略
  const broken = loadSave({ ...raw, mined: -3 })
  assert.ok(broken)
  assert.equal(broken.legacy, undefined)
})

test('4000 条编辑的存档远小于云端单个值的 64 KB 上限', () => {
  // 只允许编辑 y >= 2 的格子(下标从 2*W*D 开始)
  const edits = new Map<number, number>()
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
