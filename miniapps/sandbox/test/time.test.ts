// 世界时间:折返、时钟文字、昼夜亮度、太阳方向、时段名。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { clockText, daylight, phaseIcon, phaseOf, sunDirection, warmth, wrapTime } from '../src/time'

test('时间折返:任意数都回到 [0,1)', () => {
  assert.equal(wrapTime(0), 0)
  assert.equal(wrapTime(1), 0)
  assert.equal(wrapTime(-0.25), 0.75)
  assert.ok(Math.abs(wrapTime(2.5) - 0.5) < 1e-9)
  assert.equal(wrapTime(Number.NaN), 0)
  assert.ok(Math.abs(wrapTime(-3.1) - 0.9) < 1e-9)
})

test('时钟:t=0 是 06:00,0.25 正午,0.5 日落,0.75 午夜', () => {
  assert.equal(clockText(0), '06:00')
  assert.equal(clockText(0.25), '12:00')
  assert.equal(clockText(0.5), '18:00')
  assert.equal(clockText(0.75), '00:00')
  assert.equal(clockText(0.5 + 1 / 48), '18:30')
  assert.equal(clockText(1), '06:00')
})

test('太阳:正午最高、午夜最低;月亮在反方向', () => {
  const noon = sunDirection(0.25)
  const mid = sunDirection(0.75)
  assert.ok(noon.y > 0.9)
  assert.ok(mid.y < -0.9)
  assert.ok(Math.abs(noon.x + mid.x) < 1e-9)
  assert.ok(Math.abs(noon.y + mid.y) < 1e-9)
  const dawn = sunDirection(0)
  assert.ok(Math.abs(dawn.y) < 0.25, '日出时太阳贴近地平线')
  assert.ok(dawn.x > 0.8)
  const dusk = sunDirection(0.5)
  assert.ok(dusk.x < -0.8)
  for (let t = 0; t < 1; t += 0.05) {
    const d = sunDirection(t)
    assert.ok(Math.abs(Math.hypot(d.x, d.y, d.z) - 1) < 1e-9)
  }
})

test('昼夜亮度:白天接近 1、深夜接近 0,变化连续', () => {
  assert.ok(daylight(0.25) > 0.99)
  assert.ok(daylight(0.75) < 0.02)
  let prev = daylight(0)
  for (let t = 0.005; t < 1; t += 0.005) {
    const cur = daylight(t)
    assert.ok(cur >= 0 && cur <= 1)
    assert.ok(Math.abs(cur - prev) < 0.2, `t=${t} 亮度跳变`)
    prev = cur
  }
  // 日出/日落时天边暖色最强
  assert.ok(warmth(0) > 0.8)
  assert.ok(warmth(0.5) > 0.8)
  assert.ok(warmth(0.25) < 0.01)
  // 时段名和图标
  assert.equal(phaseOf(0.25), 'day')
  assert.equal(phaseOf(0.75), 'night')
  assert.equal(phaseOf(0), 'dawn')
  assert.equal(phaseOf(0.5), 'dusk')
  assert.equal(phaseIcon(0.25), '☀')
  assert.equal(phaseIcon(0.75), '☾')
})
