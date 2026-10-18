// shared 音效模块的纯数据单测:Node 里没有 AudioContext,这里只验证「静默降级 + 音色表合法」。
// 真正的听感在浏览器/真机人工验收(GAME-STANDARD §4)。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  CUES, haptic, installSfxUnlock, playSfx, presetOf, setSfxMuted, sfxDebug, sfxMuted, toggleSfxMuted, unlockSfx,
} from '../src/sfx'

test('音效 cue 表没有重复,且每个 cue 都有合法预设', () => {
  assert.equal(new Set(CUES).size, CUES.length)
  for (const cue of CUES) {
    const preset = presetOf(cue)
    assert.ok(preset.length >= 1 && preset.length <= 4, `${cue} 应该是 1–4 个音`)
    let total = 0
    for (const t of preset) {
      assert.ok(t.f > 0 && t.f < 8000, `${cue} 频率不合法:${t.f}`)
      if (t.to !== undefined) assert.ok(t.to > 0 && t.to < 8000, `${cue} 滑音终点不合法:${t.to}`)
      assert.ok(t.d > 0 && t.d <= 0.4, `${cue} 时长应该在 0–400ms:${t.d}`)
      assert.ok(t.g >= 0 && t.g <= 0.2, `${cue} 单音增益应该在 0–0.2:${t.g}`)
      assert.ok(!t.at || t.at >= 0, `${cue} 延迟不能为负`)
      total = Math.max(total, (t.at || 0) + t.d)
    }
    assert.ok(total <= 0.5, `${cue} 整个 cue 不应超过 500ms(不拖尾)`)
  }
})

test('没有 AudioContext 时所有调用都静默降级、不抛', () => {
  assert.doesNotThrow(() => unlockSfx())
  assert.doesNotThrow(() => installSfxUnlock())
  assert.doesNotThrow(() => playSfx('tap'))
  assert.doesNotThrow(() => haptic('light'))
  assert.doesNotThrow(() => haptic('success'))
  const d = sfxDebug()
  assert.equal(d.unlocked, false)
  assert.equal(d.active, 0)
})

test('静音开关能来回切换(设备级,进程内状态正确)', () => {
  const before = sfxMuted()
  setSfxMuted(false)
  assert.equal(sfxMuted(), false)
  assert.equal(toggleSfxMuted(), true)
  assert.equal(sfxMuted(), true)
  // 静音时 play/unlock 都不应该建 AudioContext
  playSfx('win')
  unlockSfx()
  assert.equal(sfxDebug().unlocked, false)
  setSfxMuted(false)
  assert.equal(sfxMuted(), false)
  setSfxMuted(before)
})
