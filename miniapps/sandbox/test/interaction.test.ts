// 挖 / 放的手感状态机:进度、换目标取消、放置冷却、连击计数。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { canPlace, newMineState, newPlaceCooldown, nextStreak, tickMining, tickPlaceCooldown } from '../src/interaction'
import { BEDROCK, GRASS, STONE, breakTime } from '../src/blocks'
import { FEEL } from '../src/data'

test('挖掘进度按硬度走:草比石头快,进度到 1 才破', () => {
  const grass = newMineState()
  const hard = newMineState()
  let brokeGrass = -1
  let brokeStone = -1
  let t = 0
  for (let i = 0; i < 600; i++) {
    t += 1 / 60
    const a = tickMining(grass, '1,2,3', true, GRASS, false, 1 / 60)
    const b = tickMining(hard, '1,2,3', true, STONE, false, 1 / 60)
    if (a.broke && brokeGrass < 0) brokeGrass = t
    if (b.broke && brokeStone < 0) brokeStone = t
    if (brokeGrass > 0 && brokeStone > 0) break
  }
  assert.ok(brokeGrass > 0 && brokeStone > 0)
  assert.ok(brokeGrass < brokeStone, `草 ${brokeGrass.toFixed(2)}s 应该比石头 ${brokeStone.toFixed(2)}s 快`)
  assert.ok(Math.abs(brokeGrass - breakTime(GRASS, false)) < 0.05)
  assert.ok(Math.abs(brokeStone - breakTime(STONE, false)) < 0.1)
  // 水里慢一点(同样时间进度更少)
  const wet = newMineState()
  const dry = newMineState()
  for (let i = 0; i < 30; i++) {
    tickMining(wet, 'k', true, STONE, true, 1 / 60)
    tickMining(dry, 'k', true, STONE, false, 1 / 60)
  }
  assert.ok(wet.progress < dry.progress)
})

test('松开、换目标都会取消进度;挖穿后进度清零', () => {
  const s = newMineState()
  tickMining(s, 'a', true, STONE, false, 0.3)
  assert.ok(s.progress > 0)
  tickMining(s, 'a', false, STONE, false, 1 / 60)
  assert.equal(s.progress, 0)
  assert.equal(s.targetKey, '')
  tickMining(s, 'b', true, STONE, false, 0.3)
  const before = s.progress
  tickMining(s, 'c', true, STONE, false, 1 / 60)
  assert.ok(s.progress < before, '换目标进度清零')
  assert.equal(s.targetKey, 'c')
  // 挖穿:长时间按住只破一次(破完 targetKey 归零,再按同一目标是一轮新的)
  const fast = newMineState()
  let breaks = 0
  for (let i = 0; i < 60; i++) {
    if (tickMining(fast, 'k', true, GRASS, false, 0.05).broke) {
      breaks++
      break
    }
  }
  assert.equal(breaks, 1)
  assert.equal(fast.progress, 0)
})

test('基岩:再按也不会推进、不会破', () => {
  const s = newMineState()
  for (let i = 0; i < 100; i++) {
    const r = tickMining(s, 'bed', true, BEDROCK, false, 0.05)
    assert.equal(r.broke, false)
  }
  assert.equal(s.progress, 0)
})

test('挖掘音效节流:每 0.2 秒最多响一次「沙沙」', () => {
  const s = newMineState()
  let sounds = 0
  for (let i = 0; i < 60; i++) if (tickMining(s, 'k', true, STONE, false, 0.05).tickSound) sounds++
  const expect = Math.ceil(3 / FEEL.MINE_SOUND_INTERVAL)
  assert.ok(sounds >= expect - 2 && sounds <= expect + 1, `响 ${sounds} 次(预期约 ${expect})`)
})

test('放置冷却:连点不会一口气放一排', () => {
  let cd = newPlaceCooldown()
  assert.equal(cd, FEEL.PLACE_COOLDOWN)
  assert.equal(canPlace(cd), false)
  for (let i = 0; i < 12; i++) cd = tickPlaceCooldown(cd, 1 / 60)
  assert.equal(canPlace(cd), true)
  assert.equal(tickPlaceCooldown(1, 5), 0, '冷却不会变成负数')
})

test('连击计数:按住挖才累计;松开/放置归零', () => {
  let s = 0
  s = nextStreak(s, true, true, false)
  s = nextStreak(s, true, true, false)
  assert.equal(s, 2)
  s = nextStreak(s, true, false, false)
  assert.equal(s, 2, '没挖穿的那帧不变')
  s = nextStreak(s, true, false, true)
  assert.equal(s, 0, '放了方块就归零')
  s = nextStreak(5, false, true, false)
  assert.equal(s, 0, '松开挖键归零')
})
