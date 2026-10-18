import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  COLS, FLOOR, MAPS, ROWS, mapById, parseMap, parseMapRows, siteAt, siteCenter, tileAt,
} from '../src/map'

test('两张地图都合法:44×26、出生点/守卫点/炸弹点在地面、所有地面互相可达', () => {
  assert.equal(MAPS.length, 2)
  assert.equal(MAPS[0].id, 'warehouse')
  assert.equal(MAPS[1].id, 'market')
  const ids = MAPS.map((m) => m.id)
  assert.equal(new Set(ids).size, ids.length, '地图 id 不重复')
  for (const def of MAPS) {
    assert.equal(def.rows.length, ROWS, `${def.name} 行数`)
    for (const row of def.rows) assert.equal(row.length, COLS, `${def.name} 每行 ${COLS} 格`)
    const map = parseMap(def)
    assert.equal(map.id, def.id)
    assert.equal(map.name, def.name)
    assert.equal(map.theme, def.theme)
    assert.equal(tileAt(map, Math.floor(map.playerSpawn.x / 24), Math.floor(map.playerSpawn.y / 24)), FLOOR)
    assert.equal(map.guardSpawns.length, 3)
    for (const spawn of map.guardSpawns) {
      assert.equal(tileAt(map, Math.floor(spawn.x / 24), Math.floor(spawn.y / 24)), FLOOR)
    }
    assert.equal(siteAt(map, siteCenter(map.siteA)), 'A')
    assert.equal(siteAt(map, siteCenter(map.siteB)), 'B')
    assert.notEqual(JSON.stringify(map.siteA), JSON.stringify(map.siteB), '两个点不能是同一块区域')
    // 所有地面格都从出生点走得通(没有孤岛)
    const reachable = reachableCount(map, map.playerSpawn)
    let floor = 0
    for (let row = 0; row < ROWS; row++) {
      for (let col = 0; col < COLS; col++) if (tileAt(map, col, row) === FLOOR) floor++
    }
    assert.equal(reachable, floor, `${def.name} 有走不到的地面`)
  }
})

// 小地图 BFS:不引 nav,免得测一样的东西
function reachableCount(map: ReturnType<typeof parseMap>, from: { x: number; y: number }): number {
  const start = { col: Math.floor(from.x / 24), row: Math.floor(from.y / 24) }
  const seen = new Set<number>()
  const queue = [start.row * COLS + start.col]
  seen.add(queue[0])
  const floor = (col: number, row: number): boolean => {
    if (col < 0 || row < 0 || col >= COLS || row >= ROWS) return false
    return tileAt(map, col, row) === FLOOR
  }
  while (queue.length) {
    const cur = queue.pop()!
    const col = cur % COLS
    const row = Math.floor(cur / COLS)
    for (const [dc, dr] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const nc = col + dc
      const nr = row + dr
      if (!floor(nc, nr)) continue
      const next = nr * COLS + nc
      if (seen.has(next)) continue
      seen.add(next)
      queue.push(next)
    }
  }
  return seen.size
}

test('两张地图布局确实不同,各自的炸弹点区域不一样', () => {
  const a = parseMap(MAPS[0])
  const b = parseMap(MAPS[1])
  let diff = 0
  for (let i = 0; i < a.tiles.length; i++) if (a.tiles[i] !== b.tiles[i]) diff++
  assert.ok(diff > 120, `两张图应该长得不一样,实际只差 ${diff} 格`)
  assert.notEqual(JSON.stringify(a.siteA), JSON.stringify(b.siteA))
  assert.notEqual(JSON.stringify(a.siteB), JSON.stringify(b.siteB))
  assert.equal(a.theme, 'warehouse')
  assert.equal(b.theme, 'market')
})

test('mapById 认两张图;不认识的回默认图', () => {
  assert.equal(mapById('warehouse').id, 'warehouse')
  assert.equal(mapById('market').name, '霓虹夜市')
  assert.equal(mapById('nope' as never).id, 'warehouse')
})

test('坏图仍然会被拒绝(行数/字符/边界)', () => {
  for (const def of MAPS) {
    assert.throws(() => parseMapRows(def.rows.slice(1)), /地图不合法/)
    const bad = def.rows.slice()
    bad[1] = '#' + '?'.repeat(COLS - 1) + '#'
    assert.throws(() => parseMapRows(bad), /不认识的字符/)
  }
})
