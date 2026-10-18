// 存档单测:整局往返、坏档容错、大小上限、子弹裁剪、读档后继续打一致。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { advance, command, newGame } from '../src/engine'
import { loadGame, saveGame } from '../src/save'
import { levelById } from '../src/levels'
import type { GameState } from '../src/types'

/** 造一份「打到一半」的真实存档:有几座塔、场上有虫、有金币有波次 */
function midGame(levelId: number | 'endless' = 12, seed = 7): GameState {
  const state = newGame(levelById(levelId), seed)
  state.gold = 2000
  command(state, { kind: 'summon' })
  command(state, { kind: 'build', slot: 0, tower: 'pea' })
  command(state, { kind: 'build', slot: 1, tower: 'pea' })
  command(state, { kind: 'build', slot: 2, tower: 'frost' })
  command(state, { kind: 'upgrade', id: state.towers[0].id })
  advance(state, 4)
  return state
}

/** 比较时忽略固定步长累加器(存档时会清零,数值 < 1/60 秒,不影响对局) */
function norm(state: GameState): GameState {
  return {
    ...state,
    acc: 0,
    stats: { ...state.stats, towers: [...state.stats.towers] },
    enemies: state.enemies.map((e) => ({ ...e })),
    towers: state.towers.map((t) => ({ ...t })),
    spawns: state.spawns.map((s) => ({ ...s })),
    shots: state.shots.map((s) => ({ ...s })),
  }
}

test('整局存档往返:写进去、读回来,结构完全一致', () => {
  const state = midGame()
  const raw = JSON.parse(JSON.stringify(saveGame(state)))
  const back = loadGame(raw)
  assert.ok(back)
  assert.deepEqual(norm(back), norm(state))
})

test('坏档容错:版本不对、结构不对、数值越界的存档一律当作没有', () => {
  const good = midGame()
  const clone = (): GameState => JSON.parse(JSON.stringify(good))
  const bads: unknown[] = [
    null, undefined, 0, 42, 'x', [], {}, { ...good, v: 2 }, { ...good, levelId: 99 },
    { ...good, levelId: 'endless', endless: false },
    { ...good, hp: -1 }, { ...good, hp: 999 }, { ...good, maxHp: 30, hp: 31 },
    { ...good, gold: -5 }, { ...good, gold: 1.5 }, { ...good, wave: -1 }, { ...good, wave: 99 },
    { ...good, phase: 'waving' }, { ...good, over: 'draw' },
    { ...good, over: 'win', phase: 'wave' }, { ...good, over: null, phase: 'over' },
    { ...good, stars: 4 }, { ...good, over: 'lose', stars: 2 },
    { ...good, speed: 3 }, { ...good, paused: 'no' },
    { ...good, enemies: 'oops' }, { ...good, towers: {} }, { ...good, spawns: null },
    { ...good, stats: null }, { ...good, rng: 'x' }, { ...good, nextId: 0 },
  ]
  // 敌人:不认识的种类 / 血量越界 / 走错路 / 路程越界
  const badKind = clone()
  badKind.enemies[0].kind = 'dragon' as never
  bads.push(badKind)
  const badHp = clone()
  badHp.enemies[0].hp = badHp.enemies[0].maxHp + 1
  bads.push(badHp)
  const badPath = clone()
  badPath.enemies[0].path = 9
  bads.push(badPath)
  const badDist = clone()
  badDist.enemies[0].dist = badDist.enemies[0].span + 100
  bads.push(badDist)
  // 塔:重复建造位 / 不认识的塔 / 等级越界
  const dup = clone()
  if (dup.towers.length >= 2) dup.towers[1].slot = dup.towers[0].slot
  bads.push(dup)
  const badTower = clone()
  badTower.towers[0].kind = 'laser' as never
  bads.push(badTower)
  const badLevel = clone()
  badLevel.towers[0].level = 4 as never
  bads.push(badLevel)
  for (const raw of bads) {
    assert.equal(loadGame(raw), null, `这个存档应该被拒绝:${JSON.stringify(raw)?.slice(0, 80)}`)
  }
  assert.ok(loadGame(JSON.parse(JSON.stringify(saveGame(good)))), '正常存档仍然读得出来')
})

test('存档大小:塞满一屏的虫和塔也远小于云端每键 64 KB', () => {
  const state = midGame()
  state.gold = 99999
  for (let i = 0; i < 9; i++) state.enemies.push({ ...state.enemies[0], id: 5000 + i, dist: i * 3 })
  const json = JSON.stringify(saveGame(state))
  assert.ok(json.length < 64 * 1024, `存档 ${json.length} 字节,超过 64 KB`)
  assert.ok(loadGame(JSON.parse(json)), '压满的状态也要能读回来')
})

test('子弹只留最后一小段:存档不会因为弹道越写越大', () => {
  const state = newGame(levelById(1), 3)
  for (let i = 0; i < 100; i++) {
    state.shots.push({ kind: 'pea', x: 0, y: 0, tx: 10, ty: 10, life: 0.1, max: 0.16 })
  }
  const saved = saveGame(state) as { shots: unknown[] }
  assert.ok(saved.shots.length <= 32)
  const back = loadGame(JSON.parse(JSON.stringify(saved)))
  assert.ok(back)
  assert.equal(back.shots.length, saved.shots.length)
})

test('读档后接着打:和没存过档的对局结果一致(引擎与存档对同一个状态达成一致)', () => {
  const state = midGame(2)
  const back = loadGame(JSON.parse(JSON.stringify(saveGame(state))))
  assert.ok(back)
  for (let i = 0; i < 10; i++) {
    const ea = advance(state, 0.2)
    const eb = advance(back, 0.2)
    assert.equal(ea.length, eb.length)
    assert.equal(state.gold, back.gold)
    assert.equal(state.hp, back.hp)
    assert.equal(state.enemies.length, back.enemies.length)
  }
})

test('坏档在读取时被修正的地方:路程裁剪到本关路线长度、span 按路线重算', () => {
  const state = midGame(4)
  const raw = JSON.parse(JSON.stringify(saveGame(state))) as GameState
  const first = raw.enemies[0]
  assert.ok(first)
  first.span = 12345 // 旧数据/坏数据
  first.dist = 10
  const back = loadGame(raw)
  assert.ok(back)
  const level = levelById(4)
  assert.ok(Math.abs(back.enemies[0].span - level.world.lens[0]) < 1e-9, 'span 应该按当前关卡路线重算')
})
