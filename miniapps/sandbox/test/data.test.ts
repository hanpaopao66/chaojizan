// 数值表自检(GAME-STANDARD §2:所有数值集中在 data.ts):
// 范围合理、阈值递增、成就表完整、方块材质齐全。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  ACHIEVEMENTS, AUDIO, BLOCKS, BEDROCK, DAY, FEEL, HOTBAR, LIMITS, PLAYER, STARTER_COUNTS, TERRAIN, TREE, VIEW,
  WORLD,
} from '../src/data'

test('世界尺寸和方块表:尺寸合理、九格快捷栏、方块材质齐全', () => {
  assert.equal(WORLD.W, 128)
  assert.equal(WORLD.D, 128)
  assert.ok(WORLD.H >= 40 && WORLD.H <= 64)
  assert.ok(WORLD.SEA_LEVEL > 2 && WORLD.SEA_LEVEL < WORLD.H - 10)
  assert.equal(HOTBAR.length, 9)
  assert.equal(new Set(HOTBAR).size, 9)
  assert.equal(STARTER_COUNTS.length, 9)
  // 初始物资只送挖不到的三种(木板/玻璃/砖),其余要自己挖
  assert.deepEqual(STARTER_COUNTS, [0, 0, 0, 0, 0, 0, 8, 6, 6])
  for (const [id, def] of BLOCKS.entries()) {
    assert.equal(def.id, id)
    assert.ok(def.name.length > 0)
    assert.ok(def.hardness > 0)
    const untouchable = id === 0 || id === 5 || id === BEDROCK // 空气/水/基岩不可挖
    if (!untouchable) assert.ok(Number.isFinite(def.hardness), `${def.name} 应该挖得动`)
    else assert.equal(def.hardness, Infinity)
  }
  // 越硬越慢:草比石头好挖
  assert.ok(BLOCKS[1].hardness < BLOCKS[3].hardness)
  assert.ok(BLOCKS[7].hardness < BLOCKS[10].hardness)
})

test('手感参数在可玩范围内;跳跃高度够一格、不够两格', () => {
  assert.ok(FEEL.WALK_SPEED >= 3 && FEEL.WALK_SPEED <= 8)
  assert.ok(FEEL.GRAVITY >= 15 && FEEL.GRAVITY <= 40)
  assert.ok(FEEL.JUMP_SPEED > 6 && FEEL.JUMP_SPEED < 12)
  assert.ok(PLAYER.HEIGHT > 1 && PLAYER.HEIGHT < 2.5)
  assert.ok(PLAYER.EYE_HEIGHT < PLAYER.HEIGHT)
  // 跳起高度 = v²/2g,要 > 1 格(能跳上台阶)、< 2 格(不能一步跳两层)
  const jumpHeight = (FEEL.JUMP_SPEED * FEEL.JUMP_SPEED) / (2 * FEEL.GRAVITY)
  assert.ok(jumpHeight > 1 && jumpHeight < 2, `跳跃高度 ${jumpHeight.toFixed(2)}`)
  assert.ok(FEEL.COYOTE_TIME > 0 && FEEL.COYOTE_TIME < 0.3)
  assert.ok(FEEL.JUMP_BUFFER > 0 && FEEL.JUMP_BUFFER < 0.3)
  assert.ok(FEEL.PLACE_COOLDOWN > 0 && FEEL.PLACE_COOLDOWN < 0.5)
})

test('画面/时间/上限参数:自适应画质、昼夜长度、成就检查都合理', () => {
  assert.ok(VIEW.RENDER_DIST >= 24 && VIEW.RENDER_DIST <= 96)
  assert.ok(VIEW.HFOV >= 60 && VIEW.HFOV <= 100)
  assert.ok(VIEW.TARGET_PIXELS >= 40000 && VIEW.TARGET_PIXELS <= 250000)
  assert.ok(VIEW.QUALITY_MIN > 0 && VIEW.QUALITY_MIN < 1)
  assert.ok(VIEW.FOG_START_RATIO < VIEW.FOG_END_RATIO)
  assert.equal(DAY.SECONDS, 480)
  assert.ok(DAY.START >= 0 && DAY.START < 1)
  assert.equal(LIMITS.MAX_EDITS, 4000)
  assert.ok(LIMITS.MAX_EDITS_TEXT >= 40000 && LIMITS.MAX_EDITS_TEXT <= 64000)
  assert.ok(LIMITS.REACH >= 3 && LIMITS.REACH <= 8)
  assert.ok(LIMITS.FULL_WARN_RATIO > 0.5 && LIMITS.FULL_WARN_RATIO < 1)
  assert.ok(AUDIO.MAX_VOICES >= 6 && AUDIO.MAX_VOICES <= 32)
  assert.ok(AUDIO.UNDERWATER_CUTOFF < AUDIO.NORMAL_CUTOFF)
})

test('成就:10–15 个、id 唯一、统计型阈值递增、条件都有对应判定', () => {
  assert.ok(ACHIEVEMENTS.length >= 10 && ACHIEVEMENTS.length <= 15, `成就 ${ACHIEVEMENTS.length} 个`)
  assert.equal(new Set(ACHIEVEMENTS.map((a) => a.id)).size, ACHIEVEMENTS.length)
  for (const a of ACHIEVEMENTS) {
    assert.ok(a.name.length > 0 && a.desc.length > 0 && a.icon.length > 0)
    assert.ok(a.goal >= 1)
    assert.equal(!!a.stat !== !!a.condition, true, `${a.id} 只能有一种判定方式`)
  }
  const mined = ACHIEVEMENTS.filter((a) => a.stat === 'mined').map((a) => a.goal)
  assert.deepEqual(mined, [1, 100, 1000])
  const placed = ACHIEVEMENTS.filter((a) => a.stat === 'placed').map((a) => a.goal)
  assert.deepEqual(placed, [1, 500])
  // 地形/树木参数在合理范围
  assert.ok(TERRAIN.ISLAND_RX > WORLD.W * 0.3 && TERRAIN.ISLAND_RX < WORLD.W)
  assert.ok(TREE.DENSITY > 0 && TREE.DENSITY < 0.3)
  assert.ok(TREE.TRUNK_MIN >= 3 && TREE.TRUNK_MAX > TREE.TRUNK_MIN)
})
