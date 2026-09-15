import assert from 'node:assert/strict'
import { test } from 'node:test'
import { contrast } from '../../shared/src/color'
import { DARK, LIGHT } from '../src/palette'

test('数字 1–8 和翻开的格子底色对比度 ≥ 4.5:1;旗、雷 ≥ 3:1,亮暗两套都算', () => {
  for (const [name, p] of Object.entries({ 亮: LIGHT, 暗: DARK })) {
    assert.equal(p.numbers.length, 8)
    p.numbers.forEach((c, i) => {
      assert.ok(contrast(c, p.open) >= 4.5, `${name}色 数字 ${i + 1}:${contrast(c, p.open).toFixed(2)}`)
    })
    assert.ok(contrast(p.flag, p.hidden) >= 3, `${name}色 旗对没翻开的格子`)
    assert.ok(contrast(p.mine, p.open) >= 3, `${name}色 雷对翻开的格子`)
    assert.ok(contrast(p.mine, p.boom) >= 3, `${name}色 雷对踩到的那格`)
    assert.ok(contrast(p.mine, p.hidden) >= 3, `${name}色 插错的旗上的叉`)
  }
})
