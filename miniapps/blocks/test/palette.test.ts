import assert from 'node:assert/strict'
import { test } from 'node:test'
import { contrast } from '../../shared/src/color'
import { KINDS } from '../src/engine'
import { DARK, LIGHT } from '../src/palette'

test('七种方块各有颜色,和棋盘底色、格线的对比度 ≥ 3:1,亮暗两套都算', () => {
  for (const [name, p] of Object.entries({ 亮: LIGHT, 暗: DARK })) {
    assert.equal(p.pieces.length, KINDS.length)
    assert.equal(new Set(p.pieces).size, KINDS.length, `${name}色有两种方块同色`)
    p.pieces.forEach((c, i) => {
      assert.ok(contrast(c, p.board) >= 3, `${name}色 ${KINDS[i]}:${contrast(c, p.board).toFixed(2)}`)
      assert.ok(contrast(c, p.grid) >= 3, `${name}色 ${KINDS[i]} 对格线`)
    })
  }
})
