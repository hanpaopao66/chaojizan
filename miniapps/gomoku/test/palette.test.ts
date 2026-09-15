import assert from 'node:assert/strict'
import { test } from 'node:test'
import { contrast } from '../../shared/src/color'
import { DARK, LIGHT } from '../src/palette'

test('棋子、线、连五的圈和棋盘分得清,最后一手的红点在两种棋子上都看得见(亮暗两套)', () => {
  for (const [name, p] of Object.entries({ 亮: LIGHT, 暗: DARK })) {
    const visible = (fill: string, edge: string) => Math.max(contrast(fill, p.board), contrast(edge, p.board))
    assert.ok(visible(p.black, p.blackEdge) >= 3, `${name}色 黑子`)
    assert.ok(visible(p.white, p.whiteEdge) >= 3, `${name}色 白子`)
    assert.ok(contrast(p.black, p.white) >= 3, `${name}色 黑白两子互相`)
    assert.ok(contrast(p.line, p.board) >= 3, `${name}色 棋盘线:${contrast(p.line, p.board).toFixed(2)}`)
    assert.ok(contrast(p.win, p.board) >= 3, `${name}色 连五的圈:${contrast(p.win, p.board).toFixed(2)}`)
    assert.ok(contrast(p.mark, p.black) >= 3, `${name}色 红点在黑子上`)
    assert.ok(contrast(p.mark, p.white) >= 3, `${name}色 红点在白子上`)
  }
})
