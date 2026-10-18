// Game 类(玩法总装):走/挖/放驱动统计、成就、背包、世界编辑和改动上限的清理出口。
// 副作用全部用假实现收集,不碰 DOM/音频/存档。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Game, emptyInput, type GameEffects, type GameInput } from '../src/gameplay'
import { GRASS } from '../src/blocks'
import { emptyProfile } from '../src/profile'
import { World } from '../src/world'
import { MAX_EDITS } from '../src/world'

interface Harness {
  game: Game
  world: World
  effects: {
    sounds: string[]
    toasts: string[]
    announces: string[]
    achievements: string[]
    cleanup: number
  }
}

function harness(seed = 4242): Harness {
  const effects = { sounds: [] as string[], toasts: [] as string[], announces: [] as string[], achievements: [] as string[], cleanup: 0 }
  const impl: GameEffects = {
    sound: (name) => { effects.sounds.push(name) },
    toast: (text) => { effects.toasts.push(text) },
    announce: (text) => { effects.announces.push(text) },
    achievement: (def) => { effects.achievements.push(def.id) },
    cleanupNeeded: () => { effects.cleanup++ },
    markDirty: () => undefined,
  }
  const game = new Game(impl)
  const world = new World(seed)
  game.loadNew(seed, world)
  return { game, world, effects }
}

/** 按住某键跑 n 帧;第一帧带 jumpPressed/placePressed 的用 extra 传 */
function run(game: Game, frames: number, over: Partial<GameInput> = {}): void {
  const input: GameInput = { ...emptyInput(), ...over }
  for (let i = 0; i < frames; i++) {
    game.update(1 / 60, { ...input, jumpPressed: i === 0 ? (over.jumpPressed ?? false) : false, placePressed: i === 0 ? (over.placePressed ?? false) : false })
  }
}

test('走动会累计距离和时长;踩在地上不掉出世界', () => {
  const h = harness()
  const start = { x: h.game.player.x, z: h.game.player.z }
  run(h.game, 90, { forward: 1 })
  assert.ok(h.game.profile.walked > 1, `走了 ${h.game.profile.walked} 米`)
  assert.ok(Math.abs(h.game.profile.seconds - 1.5) < 0.05)
  assert.ok(Math.hypot(h.game.player.x - start.x, h.game.player.z - start.z) > 1)
  assert.ok(h.game.player.y > 0)
  // 没挖没放
  assert.equal(h.game.profile.mined, 0)
  assert.equal(h.game.profile.placed, 0)
})

test('低头按住挖:真的挖掉方块、进背包、算统计、触发第一个成就', () => {
  const h = harness()
  h.game.player.pitch = -1.45
  run(h.game, 90, { mine: true })
  assert.ok(h.game.profile.mined >= 1, `挖了 ${h.game.profile.mined} 块`)
  assert.ok(h.world.editCount >= 1, '世界里有编辑')
  assert.ok(h.game.inv.some((n) => n > 0), '挖到的东西进了背包')
  assert.ok(h.effects.achievements.includes('first_mine'))
  assert.ok(h.world.blockAt(
    Math.floor(h.game.player.x), Math.floor(h.game.player.y - 1), Math.floor(h.game.player.z),
  ) !== GRASS || h.world.editCount > 0)
})

test('挖掉面前的方块再放回去:放会消耗背包、算 placed、触发成就', () => {
  const h = harness()
  // 面前斜下方挖两下(别挖脚底下,人不会掉进洞里)
  h.game.player.pitch = -0.9
  run(h.game, 50, { mine: true })
  assert.ok(h.game.profile.mined >= 1)
  // 选中背包里数量 >0 的格子,再按住放
  const slot = h.game.inv.findIndex((n) => n > 0)
  assert.ok(slot >= 0)
  h.game.selectSlot(slot)
  const before = h.game.inv[slot]
  for (let i = 0; i < 40 && h.game.profile.placed === 0; i++) {
    h.game.update(1 / 60, { ...emptyInput(), placePressed: true })
  }
  assert.ok(h.game.profile.placed >= 1, '放了至少一块')
  assert.ok(h.game.inv[slot] < before, '放方块消耗背包')
  assert.ok(h.effects.achievements.includes('first_place'))
})

test('放置冷却:一帧连按多次也只放一块', () => {
  const h = harness()
  h.game.player.pitch = -0.9
  run(h.game, 50, { mine: true })
  const slot = h.game.inv.findIndex((n) => n > 0)
  h.game.selectSlot(slot)
  h.game.update(1 / 60, { ...emptyInput(), placePressed: true })
  const placedOnce = h.game.profile.placed
  h.game.update(1 / 60, { ...emptyInput(), placePressed: true })
  assert.equal(h.game.profile.placed, placedOnce, '冷却中不会再放')
})

test('改动到上限:挖新的方块被拒绝,并通知界面弹清理面板', () => {
  const h = harness(777)
  // 在很高的空中填满编辑表(不影响地面)
  let made = 0
  outer:
  for (let y = 47; y >= 40; y--) {
    for (let z = 10; z < 40; z++) {
      for (let x = 10; x < 40; x++) {
        if (h.world.blockAt(x, y, z) !== 0) continue
        if (h.world.setBlock(x, y, z, 3) !== 'ok') break outer
        if (++made >= MAX_EDITS) break outer
      }
    }
  }
  assert.equal(made, MAX_EDITS)
  h.game.player.pitch = -1.45
  h.game.update(1 / 60, { ...emptyInput(), mine: true })
  for (let i = 0; i < 300; i++) h.game.update(1 / 60, { ...emptyInput(), mine: true })
  assert.ok(h.effects.cleanup >= 1, '到上限时调用了 cleanupNeeded')
  assert.equal(h.game.profile.mined, 0, '上限时不再增加统计,因为没挖掉')
})

test('清理出口:撤销最近一批 / 全部恢复;统计不受影响', () => {
  const h = harness(888)
  // 直接在世界里造 150 处改动
  let made = 0
  outer:
  for (let y = 47; y >= 44; y--) {
    for (let z = 20; z < 30; z++) {
      for (let x = 20; x < 30; x++) {
        if (h.world.blockAt(x, y, z) !== 0) continue
        if (h.world.setBlock(x, y, z, 3) === 'ok') made++
        if (made >= 150) break outer
      }
    }
  }
  assert.equal(h.world.editCount, 150)
  const minedBefore = h.game.profile.mined
  const reverted = h.game.cleanupRecent()
  assert.equal(reverted, 100)
  assert.equal(h.world.editCount, 50)
  assert.equal(h.game.profile.mined, minedBefore, '清理不扣统计')
  assert.ok(h.effects.sounds.includes('cleanup'))
  const all = h.game.cleanupAll()
  assert.equal(all, 50)
  assert.equal(h.world.editCount, 0)
})

test('存档快照:带世界/位置/背包/时间,能原样再开', () => {
  const h = harness(999)
  run(h.game, 30, { forward: 1 })
  const save = h.game.snapshot()
  assert.equal(save.v, 2)
  assert.equal(save.seed, 999)
  assert.equal(save.edits, h.world.serializeEdits())
  assert.ok(Math.abs(save.time - h.game.time) < 1e-9)
  assert.equal(save.inv.length, 9)
  // 再开一份
  const h2 = harness(999)
  h2.game.load(save, emptyProfile(), new World(999))
  assert.equal(h2.game.profile.mined, 0)
  assert.ok(Math.abs(h2.game.player.x - h.game.player.x) < 1e-6)
})

test('成就上下文:maxY、地形、连击、夜里挖都从运行状态累计', () => {
  const h = harness(1234)
  h.game.player.pitch = -1.45
  run(h.game, 30, { mine: true })
  const c = h.game.achievementContext()
  assert.ok(c.maxY >= h.game.player.y - 3)
  assert.ok(c.biomeMask > 0, '出生点附近至少踩到一种地形')
  assert.ok(c.streak >= 1, '按住挖的连击在累计')
})
