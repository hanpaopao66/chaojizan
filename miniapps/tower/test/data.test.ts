// 数据自检:地图 / 塔 / 虫 / 关卡路线 / 建造位 / 波次 / 解锁 / 经济 / 成就。
// 这些用例保证 data.ts 里的内容没有写歪(关卡数据是纯手写的,最容易出岔子)。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  ACHIEVEMENTS, ACHIEVEMENT_BY_ID, COLS, ENEMIES, ROWS, STAR_RULE, TARGET, TARGET_CENTER, THEMES,
  TOWERS, TILE, WORLD_H, WORLD_W, bossHealthScale, cellCenter, computeSlots, enemyDef,
  endlessHealthScale, healthScale, pathTiles, sellValue, themeOf, towerStats, upgradeCost,
} from '../src/data'
import {
  ENDLESS, LEVELS, levelById, levelByIdOrNull, levelsOfTheme, unlockLevelOf, waveCount,
} from '../src/levels'

test('地图尺寸固定 9×14,大西瓜在 (4,12) 的中心', () => {
  assert.equal(COLS, 9)
  assert.equal(ROWS, 14)
  assert.equal(TILE, 40)
  assert.equal(WORLD_W, 360)
  assert.equal(WORLD_H, 560)
  assert.deepEqual(TARGET, { c: 4, r: 12 })
  assert.deepEqual(TARGET_CENTER, { x: 180, y: 500 })
  assert.deepEqual(cellCenter({ c: 4, r: 12 }), TARGET_CENTER)
})

test('正好 12 关 + 无尽,三页主题各 4 关', () => {
  assert.equal(LEVELS.length, 12)
  assert.deepEqual(LEVELS.map((l) => l.id), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
  assert.equal(new Set(LEVELS.map((l) => l.name)).size, 12, '关卡名不能重复')
  for (const theme of THEMES) assert.equal(levelsOfTheme(theme.id).length, 4, `${theme.name} 应该有 4 关`)
  assert.equal(THEMES.length, 3)
  assert.equal(themeOf('garden').name, '菜园')
  assert.equal(ENDLESS.id, 'endless')
  assert.equal(levelByIdOrNull('endless')?.name, '无尽瓜田')
})

test('七种塔,每种三级;造价/升级费/数值都在数据里', () => {
  assert.equal(TOWERS.length, 7)
  const kinds = new Set(TOWERS.map((t) => t.kind))
  assert.equal(kinds.size, 7, '塔的种类不能重复')
  for (const tower of TOWERS) {
    assert.ok(tower.name.length > 0 && tower.role.length > 0 && tower.desc.length > 0, `${tower.kind} 缺文案`)
    assert.match(tower.color, /^#[0-9A-Fa-f]{6}$/, `${tower.kind} 的颜色要是 #RRGGBB`)
    assert.equal(tower.upgrade.length, 2)
    assert.ok(tower.cost > 0)
    for (const up of tower.upgrade) assert.ok(up > 0)
    assert.equal(tower.levels.length, 3)
    for (let i = 0; i < 3; i++) {
      const lv = tower.levels[i]
      assert.equal(towerStats(tower.kind, i + 1), lv)
      if (tower.kind === 'marigold') {
        assert.ok((lv.goldPerWave || 0) > 0, '金盏花要有每波产出')
        continue
      }
      assert.ok(lv.damage > 0, `${tower.kind} ${i + 1} 级要有伤害`)
      assert.ok(lv.rate > 0, `${tower.kind} ${i + 1} 级要有攻速`)
      assert.ok(lv.range >= 2, `${tower.kind} ${i + 1} 级射程太小`)
    }
    // 升级只会变强,不能变弱
    assert.ok(tower.levels[1].damage >= tower.levels[0].damage)
    assert.ok(tower.levels[2].damage >= tower.levels[1].damage)
    assert.equal(upgradeCost(tower.kind, 3), 0, '满级没有升级费')
    assert.equal(upgradeCost(tower.kind, 1), tower.upgrade[0])
    assert.equal(upgradeCost(tower.kind, 2), tower.upgrade[1])
  }
  // 卖出返还总投入的 70%(向下取整)
  assert.equal(sellValue(60), 42)
  assert.equal(sellValue(130), 91)
  assert.equal(sellValue(239), 167)
})

test('虫子数据:七种普通虫 + 分裂小蚁 + 巨虫 Boss', () => {
  assert.equal(ENEMIES.length, 9)
  assert.equal(new Set(ENEMIES.map((e) => e.kind)).size, 9)
  for (const e of ENEMIES) {
    assert.ok(e.hp > 0 && e.speed > 0 && e.bounty > 0 && e.size > 0, `${e.kind} 数值不对`)
    assert.match(e.color, /^#[0-9A-Fa-f]{6}$/)
  }
  assert.equal(enemyDef('worm').hp, 30)
  assert.equal(enemyDef('flea').speed, 2.0)
  assert.equal(enemyDef('beetle').armor, 4)
  assert.equal(enemyDef('moth').flying, true)
  assert.equal(enemyDef('wasp').flying, true)
  assert.ok((enemyDef('pupa').heal?.rate || 0) > 0)
  assert.equal(enemyDef('ant').split, 2)
  assert.equal(enemyDef('antling').split, undefined, '小蚁不能再分裂')
  assert.equal(enemyDef('boss').armor, 6)
  assert.equal(enemyDef('boss').hp, 900)
  assert.equal(enemyDef('boss').leak, 5)
  assert.equal(enemyDef('boss').boss, true)
})

test('每一关的路线:轴对齐、在图上、从地图边缘进来、最后停在西瓜上方', () => {
  for (const level of LEVELS) {
    const tiles = pathTiles(level.paths)
    assert.ok(level.paths.length >= 1, `第 ${level.id} 关没有路线`)
    for (const path of level.paths) {
      assert.ok(path.length >= 2)
      path.forEach((p, i) => {
        assert.ok(p.c >= 0 && p.c < COLS && p.r >= 0 && p.r < ROWS, `第 ${level.id} 关路线越界`)
        if (i === 0) return
        const prev = path[i - 1]
        assert.ok(prev.c === p.c || prev.r === p.r, `第 ${level.id} 关路线有斜线`)
      })
      const first = path[0]
      const onEdge = first.r === 0 || first.c === 0 || first.c === COLS - 1
      assert.ok(onEdge, `第 ${level.id} 关的入口要在地图边缘`)
      const last = path[path.length - 1]
      assert.equal(last.c, 4, `第 ${level.id} 关的路线要收在西瓜正上方`)
      assert.equal(last.r, 11)
      for (const p of path) assert.ok(!(p.c === TARGET.c && p.r === TARGET.r), '路线不能穿过西瓜')
    }
    assert.ok(tiles.size > 10, `第 ${level.id} 关的路太短`)
    assert.equal(level.world.polys.length, level.paths.length)
    assert.equal(level.world.target.x, TARGET_CENTER.x)
    assert.ok(level.world.lens.every((l) => l > TILE * 6), `第 ${level.id} 关有路线太短`)
  }
  // 第 10 关起双入口
  for (const id of [1, 2, 3, 4, 5, 6, 7, 8, 9]) assert.equal(levelById(id).paths.length, 1)
  for (const id of [10, 11, 12]) assert.equal(levelById(id).paths.length, 2)
})

test('建造位:不压路、不压西瓜、在图上、互相隔开、数量够', () => {
  for (const level of LEVELS) {
    const tiles = pathTiles(level.paths)
    assert.ok(level.slots.length >= 8, `第 ${level.id} 关建造位太少`)
    assert.ok(level.slots.length <= level.slotCap, `第 ${level.id} 关建造位超过上限`)
    assert.ok(level.hintSlot >= 0 && level.hintSlot < level.slots.length)
    const seen = new Set<number>()
    level.slots.forEach((slot) => {
      assert.ok(slot.c >= 0 && slot.c < COLS && slot.r >= 0 && slot.r < ROWS)
      const key = slot.r * COLS + slot.c
      assert.ok(!seen.has(key), `第 ${level.id} 关建造位重复`)
      seen.add(key)
      assert.ok(!tiles.has(key), `第 ${level.id} 关建造位压在路上 (${slot.c},${slot.r})`)
      assert.ok(!(slot.c === TARGET.c && slot.r === TARGET.r))
    })
    for (let i = 0; i < level.slots.length; i++) {
      for (let j = i + 1; j < level.slots.length; j++) {
        const a = level.slots[i]
        const b = level.slots[j]
        const d2 = (a.c - b.c) ** 2 + (a.r - b.r) ** 2
        assert.ok(d2 >= 4, `第 ${level.id} 关两个建造位挨得太近`)
      }
    }
    // 推导函数本身可复现
    assert.deepEqual(computeSlots(level.paths).slice(0, level.slots.length), level.slots.slice())
  }
})

test('波次数据:每组虫都在图里、间隔合理、走对应的路;Boss 关最后一波有 Boss', () => {
  for (const level of LEVELS) {
    assert.ok(level.waves.length >= 5, `第 ${level.id} 关波数太少`)
    assert.equal(waveCount(level), level.waves.length)
    level.waves.forEach((wave, wi) => {
      assert.ok(wave.groups.length > 0, `第 ${level.id} 关第 ${wi + 1} 波没有怪`)
      for (const g of wave.groups) {
        assert.ok(['worm', 'flea', 'beetle', 'moth', 'wasp', 'pupa', 'ant', 'boss'].includes(g.kind))
        assert.ok(g.count > 0 && g.count < 100)
        assert.ok(g.gap > 0 && g.gap < 5)
        const path = g.path || 0
        assert.ok(path < level.paths.length, `第 ${level.id} 关第 ${wi + 1} 波走错路`)
        assert.ok((g.delay || 0) >= 0)
      }
    })
  }
  for (const id of [4, 8, 12]) {
    const last = levelById(id).waves[levelById(id).waves.length - 1]
    assert.ok(last.groups.some((g) => g.kind === 'boss'), `第 ${id} 关最后一波应该有 Boss`)
  }
  assert.equal(ENDLESS.waves.length, 0, '无尽波次是现场生成的')
})

test('塔的解锁进度:第 1 关只有豆荚炮,到第 9 关七种都能造,无尽全开', () => {
  assert.deepEqual([...levelById(1).towers], ['pea'])
  assert.equal(unlockLevelOf('pea'), 1)
  for (const tower of TOWERS) {
    assert.ok(unlockLevelOf(tower.kind) <= 9, `${tower.name} 到第 9 关还没解锁`)
  }
  assert.equal(unlockLevelOf('marigold'), 3)
  assert.equal(ENDLESS.towers.length, 7)
  for (const level of LEVELS) {
    for (const kind of level.towers) assert.ok(TOWERS.some((t) => t.kind === kind))
  }
})

test('经济数据:起始金币 150–300、目标 HP 合理、波次奖励和成长公式固定', () => {
  for (const level of LEVELS) {
    assert.ok(level.startGold >= 150 && level.startGold <= 300, `第 ${level.id} 关起始金币 ${level.startGold} 超出 150–300`)
    assert.ok(level.goalHp >= 16 && level.goalHp <= 40, `第 ${level.id} 关目标 HP 不合理`)
  }
  assert.ok(ENDLESS.startGold >= 300, '无尽模式可以多给一点起始金币')
  // 血量成长:1 级第 1 波 = 1;1 级第 11 波 = 1.6
  assert.equal(healthScale(1, 1), 1)
  assert.ok(Math.abs(healthScale(11, 1) - 1.6) < 1e-9)
  assert.ok(healthScale(11, 12) > healthScale(11, 1), '后面的关卡同波更强')
  assert.equal(endlessHealthScale(1), 1)
  assert.ok(endlessHealthScale(20) > healthScale(20, 12), '无尽模式成长更快')
  assert.equal(bossHealthScale(1), 1)
  assert.ok(Math.abs(bossHealthScale(11) - 1.6) < 1e-9)
})

test('主题与关卡名:三套场景、四个主题页、文案不空', () => {
  assert.equal(THEMES.length, 3)
  assert.deepEqual(THEMES.map((t) => t.id), ['garden', 'orchard', 'nest'])
  for (const t of THEMES) {
    assert.ok(t.name.length > 0 && t.tagline.length > 0)
    assert.match(t.accent, /^#[0-9A-Fa-f]{6}$/)
    assert.equal(levelsOfTheme(t.id).length, 4)
    assert.ok(levelsOfTheme(t.id).every((l) => l.theme === t.id))
  }
  for (const level of LEVELS) assert.ok(level.name.length >= 2, `第 ${level.id} 关没有名字`)
})

test('关卡查询:levelById 正常、越界抛错;levelByIdOrNull 对坏输入返回 null', () => {
  assert.equal(levelById(1).id, 1)
  assert.equal(levelById(12).id, 12)
  assert.equal(levelById('endless').id, 'endless')
  assert.throws(() => levelById(0 as never))
  assert.throws(() => levelById(13 as never))
  assert.equal(levelByIdOrNull(0), null)
  assert.equal(levelByIdOrNull(13), null)
  assert.equal(levelByIdOrNull('nope'), null)
  assert.equal(levelByIdOrNull(null), null)
  assert.equal(levelByIdOrNull(6)?.name, levelById(6).name)
})

test('成就:12 个、id 唯一、文案齐全、判定表能查到', () => {
  assert.equal(ACHIEVEMENTS.length, 12)
  assert.equal(new Set(ACHIEVEMENTS.map((a) => a.id)).size, 12)
  for (const a of ACHIEVEMENTS) {
    assert.ok(a.name.length >= 2 && a.desc.length >= 4, `${a.id} 文案不齐`)
    assert.equal(ACHIEVEMENT_BY_ID.get(a.id), a)
  }
  assert.ok(STAR_RULE.includes('3 星'))
})

test('路线采样:折线长度和入口/终点对得上', () => {
  const level = levelById(1)
  const poly = level.world.polys[0]
  const start = level.world.starts[0]
  assert.deepEqual({ x: poly[0].x, y: poly[0].y }, { x: start.x, y: start.y })
  let walked = 0
  for (let i = 1; i < poly.length; i++) walked += Math.hypot(poly[i].x - poly[i - 1].x, poly[i].y - poly[i - 1].y)
  assert.ok(Math.abs(walked - level.world.lens[0]) < 1e-6)
  assert.deepEqual(level.world.target, TARGET_CENTER)
})
