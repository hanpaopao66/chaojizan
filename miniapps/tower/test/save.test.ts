// 存档单测:整局往返、小数 HP(毒/灼烧/治疗蛹)不判坏、坏档容错、64KB 上限、子弹裁剪、
// 读档后继续打一致。存档是紧凑格式,数值保留两位小数,所以比较用容差。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { advance, applyBurn, applyPoison, command, newGame, spawnEnemy } from '../src/engine'
import { loadGame, saveGame, type SavedGame } from '../src/save'
import { levelById } from '../src/levels'
import type { GameState } from '../src/types'

const TOL = 0.011
const close = (a: number, b: number, msg = ''): void => {
  assert.ok(Math.abs(a - b) <= TOL, `${msg} ${a} 与 ${b} 差得太多`)
}

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

/** 保存 → 解析 JSON → 读回来(模拟真的写进 localStorage 再读) */
function roundtrip(state: GameState): GameState | null {
  return loadGame(JSON.parse(JSON.stringify(saveGame(state))))
}

function assertSameState(back: GameState, state: GameState): void {
  assert.equal(back.levelId, state.levelId)
  assert.equal(back.gold, state.gold)
  assert.equal(back.maxHp, state.maxHp)
  close(back.hp, state.hp, '西瓜血量')
  assert.equal(back.wave, state.wave)
  assert.equal(back.phase, state.phase)
  assert.equal(back.over, state.over)
  assert.equal(back.stars, state.stars)
  assert.equal(back.speed, state.speed)
  assert.equal(back.endless, state.endless)
  assert.equal(back.bossWave, state.bossWave)
  assert.equal(back.summoned, state.summoned)
  assert.equal(back.paused, state.paused)
  assert.equal(back.seed, state.seed)
  assert.equal(back.rng, state.rng)
  close(back.time, state.time, '用时')
  close(back.prep, state.prep, '准备倒计时')
  close(back.clock, state.clock, '本波时钟')
  assert.equal(back.nextId, state.nextId)
  back.stats.towers = [...back.stats.towers].sort()
  state.stats.towers = [...state.stats.towers].sort()
  assert.deepEqual(back.stats, state.stats)
  // 塔
  assert.equal(back.towers.length, state.towers.length)
  back.towers.forEach((t, i) => {
    const o = state.towers[i]
    assert.equal(t.id, o.id)
    assert.equal(t.kind, o.kind)
    assert.equal(t.level, o.level)
    assert.equal(t.slot, o.slot)
    assert.equal(t.invested, o.invested)
    close(t.cd, o.cd, '塔冷却')
    close(t.aim, o.aim, '塔朝向')
  })
  // 虫
  assert.equal(back.enemies.length, state.enemies.length)
  back.enemies.forEach((e, i) => {
    const o = state.enemies[i]
    assert.equal(e.id, o.id)
    assert.equal(e.kind, o.kind)
    assert.equal(e.maxHp, o.maxHp)
    assert.equal(e.path, o.path)
    close(e.hp, o.hp, '虫 hp')
    close(e.dist, o.dist, '虫路程')
    close(e.slowUntil, o.slowUntil, '减速剩余')
    close(e.slowFactor, o.slowFactor, '减速比例')
    close(e.freezeUntil, o.freezeUntil, '冻结剩余')
    close(e.poisonUntil, o.poisonUntil, '毒剩余')
    close(e.poisonDps, o.poisonDps, '毒伤害')
    close(e.burnUntil, o.burnUntil, '灼烧剩余')
    close(e.burnDps, o.burnDps, '灼烧伤害')
  })
  // 待出怪
  assert.equal(back.spawns.length, state.spawns.length)
  back.spawns.forEach((sp, i) => {
    assert.equal(sp.kind, state.spawns[i].kind)
    assert.equal(sp.path, state.spawns[i].path)
    close(sp.at, state.spawns[i].at, '出怪时间')
  })
}

test('整局存档往返:写进去、读回来,结构和数值都对得上', () => {
  const state = midGame()
  const back = roundtrip(state)
  assert.ok(back)
  assertSameState(back, state)
})

test('虫 hp 是小数(毒/灼烧/治疗蛹)时存档不能判坏 —— P0 回归', () => {
  // 用真的毒蘑菇 + 火焰椒打一轮,让场上虫子的 hp 变成小数
  const state = newGame(levelById(5), 11)
  state.gold = 5000
  command(state, { kind: 'summon' })
  command(state, { kind: 'build', slot: 0, tower: 'mushroom' })
  command(state, { kind: 'build', slot: 1, tower: 'pepper' })
  advance(state, 2.5)
  if (state.enemies.length) {
    applyPoison(state.enemies[0], 6, state.time + 4)
    applyBurn(state.enemies[0], 4, state.time + 3)
  }
  advance(state, 0.5)
  const fractional = state.enemies.filter((e) => !Number.isInteger(e.hp))
  assert.ok(fractional.length > 0, '毒/灼烧应该让敌人 hp 出现小数')
  const back = roundtrip(state)
  assert.ok(back, '有小数 hp 的存档被误判成坏档')
  assert.equal(back.enemies.length, state.enemies.length)
  back.enemies.forEach((e, i) => close(e.hp, state.enemies[i].hp, '小数 hp 存回来'))
})

test('治疗蛹把同伴 hp 奶成小数时,存档也不能判坏', () => {
  const state = newGame(levelById(5), 13)
  state.phase = 'wave'
  state.wave = 1
  state.spawns = []
  state.enemies = []
  state.gold = 5000
  spawnEnemy(state, 'pupa', 0, 400)
  const worm = spawnEnemy(state, 'worm', 0, 402)
  worm.hp = 10
  advance(state, 1.7)
  assert.ok(!Number.isInteger(worm.hp), `治疗蛹治疗后的 hp 应该是小数,现在是 ${worm.hp}`)
  const back = roundtrip(state)
  assert.ok(back)
  const healed = back.enemies.find((e) => e.kind === 'worm')
  assert.ok(healed)
  close(healed.hp, worm.hp, '治疗后的 hp')
})

test('坏档容错:版本不对、结构不对、数值越界的存档一律当作没有', () => {
  const good = saveGame(midGame())
  const clone = (): SavedGame => JSON.parse(JSON.stringify(good))
  const bads: unknown[] = [
    null, undefined, 0, 42, 'x', [], {}, { ...good, v: 2 }, { ...good, l: 99 },
    { ...good, l: 'endless', en: 0 },
    { ...good, hp: -1 }, { ...good, hp: 999 }, { ...good, mh: 30, hp: 31 },
    { ...good, g: -5 }, { ...good, g: 1.5 }, { ...good, w: -1 }, { ...good, w: 99 },
    { ...good, ph: 3 }, { ...good, ov: 2 }, { ...good, ov: 1, ph: 1 },
    { ...good, ov: null, ph: 2 }, { ...good, st: 4 }, { ...good, ov: 0, st: 2 },
    { ...good, sp: 3 }, { ...good, pa: 5 }, { ...good, pr: -1 }, { ...good, c: NaN },
    { ...good, es: 'oops' }, { ...good, ts: {} }, { ...good, ss: null },
    { ...good, sk: [1, 2] }, { ...good, sk: [1, 2, 3, 4, 5, 6, -7] },
    { ...good, ni: 0 }, { ...good, ut: 999 },
  ]
  const badEnemy = clone()
  badEnemy.es[0][1] = 99 // 不认识的虫种类
  bads.push(badEnemy)
  const badEnemyHp = clone()
  badEnemyHp.es[0][2] = badEnemyHp.es[0][3] + 1 // hp 超过 maxHp
  bads.push(badEnemyHp)
  const zeroHp = clone()
  zeroHp.es[0][2] = 0
  bads.push(zeroHp)
  const badPath = clone()
  badPath.es[0][5] = 9
  bads.push(badPath)
  const badDist = clone()
  badDist.es[0][4] = 999999
  bads.push(badDist)
  const dupEnemy = clone()
  dupEnemy.es.push([...dupEnemy.es[0]])
  bads.push(dupEnemy)
  const badTower = clone()
  badTower.ts[0][1] = 99
  bads.push(badTower)
  const dupSlot = clone()
  if (dupSlot.ts.length >= 2) dupSlot.ts[1][3] = dupSlot.ts[0][3]
  bads.push(dupSlot)
  const badSlot = clone()
  badSlot.ts[0][3] = 999
  bads.push(badSlot)
  const badSpawn = clone()
  badSpawn.ss = [[0, 1, 0]]
  badSpawn.ss[0][1] = -1
  bads.push(badSpawn)
  const badShot = clone()
  badShot.sh.push([0, 0, 0, 0, 0, 1, 0])
  bads.push(badShot)
  for (const raw of bads) {
    assert.equal(loadGame(raw), null, `这个存档应该被拒绝:${JSON.stringify(raw)?.slice(0, 80)}`)
  }
  // 旧格式(字段全名的对象)现在不认,当作没有存档
  const oldFormat = { ...midGame(), v: 1 }
  assert.equal(loadGame(oldFormat), null)
  assert.ok(loadGame(JSON.parse(JSON.stringify(good))), '正常存档仍然读得出来')
})

test('64KB 上限:300 只虫 + 800 个待出怪 + 满塔 + 小数状态也存得下、读得回', () => {
  const level = levelById(12)
  const state = newGame(level, 21)
  state.gold = 1e9
  command(state, { kind: 'summon' })
  for (let i = 0; i < level.slots.length; i++) command(state, { kind: 'build', slot: i, tower: 'pea' })
  state.spawns = []
  const kinds = ['worm', 'flea', 'beetle', 'moth', 'wasp', 'pupa', 'ant', 'boss'] as const
  for (let i = 0; i < 300; i++) {
    const e = spawnEnemy(state, kinds[i % kinds.length], i % 2, (i * 3.37) % 500)
    e.hp = Math.max(1, e.maxHp * 0.5 + 0.37)
    e.slowUntil = 12.34
    e.slowFactor = 0.45
    e.freezeUntil = 5.55
    e.poisonUntil = 8.88
    e.poisonDps = 9
    e.burnUntil = 7.77
    e.burnDps = 4
    e.flash = 0.06
  }
  for (let i = 0; i < 800; i++) {
    state.spawns.push({ kind: kinds[i % kinds.length], at: 120 + i * 0.37, path: i % 2 })
  }
  for (let i = 0; i < 64; i++) {
    state.shots.push({ kind: 'pea', x: 10 + i, y: 20 + i, tx: 30 + i, ty: 40 + i, life: 0.12, max: 0.16 })
  }
  const json = JSON.stringify(saveGame(state))
  assert.ok(json.length < 64 * 1024, `最坏情况的存档 ${json.length} 字节,超过 64 KB`)
  const back = loadGame(JSON.parse(json))
  assert.ok(back, '最坏情况的存档也要能读回来')
  assert.equal(back.enemies.length, 300)
  assert.equal(back.spawns.length, 800)
  assert.equal(back.towers.length, level.slots.length)
  assert.ok(back.shots.length <= 32, '子弹只留最后一小段')
})

test('子弹只留最后 32 发,存档不会因为弹道越写越大', () => {
  const state = newGame(levelById(1), 3)
  for (let i = 0; i < 100; i++) {
    state.shots.push({ kind: 'pea', x: 0, y: 0, tx: 10, ty: 10, life: 0.1, max: 0.16 })
  }
  const saved = saveGame(state)
  assert.ok(saved.sh.length <= 32)
  const back = loadGame(JSON.parse(JSON.stringify(saved)))
  assert.ok(back)
  assert.equal(back.shots.length, saved.sh.length)
})

test('读档后的两份对局继续打,结果完全一致(存档把状态定死了)', () => {
  const state = midGame(2)
  const a = roundtrip(state)
  const b = roundtrip(state)
  assert.ok(a && b)
  for (let i = 0; i < 10; i++) {
    const ea = advance(a, 0.2)
    const eb = advance(b, 0.2)
    assert.equal(ea.length, eb.length)
    assert.deepEqual(a, b)
  }
})

test('坏数据在读取时被修正:路程超出裁到路线长度,nextId 自动推到最大 id 之后', () => {
  const state = midGame(4)
  const raw = JSON.parse(JSON.stringify(saveGame(state))) as SavedGame
  const first = raw.es[0]
  assert.ok(first)
  const span = levelById(4).world.lens[first[5]]
  first[4] = span
  raw.ni = 2
  let maxId = 0
  for (const e of raw.es) maxId = Math.max(maxId, e[0])
  const back = loadGame(raw)
  assert.ok(back)
  assert.ok(back.nextId > maxId, 'nextId 必须比场上最大 id 大')
  assert.ok(back.enemies[0].dist <= span)
})
