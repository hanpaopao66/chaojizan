import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  LEVELS, LEVEL_KEYS, Level, State, canChord, chord, count, flagsAround, load, loadBest, mergeBest, neighbors,
  newGame, placeMines, remaining, reveal, save, tickTime, toggleFlag, updateBest, wrongFlags, EMPTY_BEST,
} from '../src/engine'

/** 按图造一个进行中的局面:'*' 是雷,'.' 不是。格子数必须和档位一致,所以用自定义尺寸的 State */
function layout(rows: string[], level: Level = 'easy'): State {
  const s = newGame(level, 1)
  const cols = rows[0].length
  const mine = rows.join('').split('').map((c) => c === '*')
  return { ...s, cols, rows: rows.length, mines: mine.filter(Boolean).length, mine,
    open: mine.map(() => false), flag: mine.map(() => false), status: 'playing' }
}
const idx = (s: State, r: number, c: number) => r * s.cols + c

test('三档的尺寸和雷数', () => {
  assert.deepEqual(LEVELS.easy, { name: '初级', cols: 9, rows: 9, mines: 10 })
  assert.equal(LEVELS.medium.cols * LEVELS.medium.rows, 256)
  assert.equal(LEVELS.medium.mines, 40)
  assert.deepEqual([LEVELS.hard.cols, LEVELS.hard.rows, LEVELS.hard.mines], [16, 30, 99])
})

test('第一下永远不是雷,而且总能翻开一片(点的那格和周围一圈都没有雷)', () => {
  for (const level of LEVEL_KEYS) {
    for (let seed = 1; seed <= 60; seed++) {
      const s = newGame(level, seed)
      const first = (seed * 37) % (s.cols * s.rows)
      const r = reveal(s, first)
      assert.equal(r.state.status === 'lost', false, `${level} 种子 ${seed} 第一下踩雷了`)
      assert.equal(r.state.mine.filter(Boolean).length, LEVELS[level].mines)
      assert.equal(count(r.state, first), 0)
      assert.ok(r.opened.length > 1, '翻开了一片')
    }
  }
})

test('格子太挤、避不开一整圈时,至少避开点的那一格', () => {
  const s = { ...newGame('easy', 3), mines: 78 } // 81 格里埋 78 颗:一圈 9 格避不开
  const p = placeMines(s, 40)
  assert.equal(p.mine[40], false)
  assert.equal(p.mine.filter(Boolean).length, 78)
})

test('翻到 0 往外扩,插了旗的不翻;翻到数字就停', () => {
  const s = layout([
    '....*',
    '.....',
    '.....',
    '*....',
  ])
  const flagged = toggleFlag(s, idx(s, 2, 2))
  const r = reveal(flagged, idx(s, 0, 0))
  assert.equal(r.state.open[idx(s, 2, 2)], false, '插旗的格子不翻')
  assert.equal(r.state.open[idx(s, 0, 3)], true, '数字格翻开了')
  assert.equal(r.state.open[idx(s, 0, 4)], false, '雷没翻')
  assert.equal(r.state.open[idx(s, 3, 0)], false)
  assert.equal(count(r.state, idx(s, 0, 3)), 1)
  assert.equal(r.state.status, 'playing')
})

test('翻到雷就输,记下踩的是哪颗;插错的旗能找出来', () => {
  let s = layout(['*..', '...', '..*'])
  s = toggleFlag(s, idx(s, 1, 1)) // 插错了
  const r = reveal(s, idx(s, 0, 0))
  assert.equal(r.state.status, 'lost')
  assert.equal(r.state.boom, 0)
  assert.deepEqual(wrongFlags(r.state), [idx(s, 1, 1)])
  assert.equal(reveal(r.state, idx(s, 0, 1)).state, r.state, '输了什么都动不了')
  assert.equal(toggleFlag(r.state, idx(s, 0, 1)), r.state)
})

test('不是雷的格子全翻开就赢,剩下的雷自动插上旗', () => {
  const s = layout(['*..', '...', '...'])
  const r = reveal(s, idx(s, 2, 2))
  assert.equal(r.state.status, 'won')
  assert.equal(r.state.flag[0], true)
  assert.equal(remaining(r.state), 0)
})

test('插旗:只能插在没翻开的格子上,再点一下拔掉;剩余雷数跟着变', () => {
  const s = layout(['*...', '....', '....', '...*'])
  const a = toggleFlag(s, 0)
  assert.equal(a.flag[0], true)
  assert.equal(remaining(a), 1)
  assert.equal(toggleFlag(a, 0).flag[0], false)
  const opened = reveal(s, idx(s, 1, 1)).state
  assert.equal(toggleFlag(opened, idx(s, 1, 1)), opened, '翻开的格子插不了旗')
})

test('快速翻开:旗数等于数字才翻周围;旗插错了会踩雷', () => {
  const s = layout([
    '*..',
    '...',
    '...',
    '..*',
  ])
  // (1,1) 周围有 1 颗雷(0,0)
  let st = reveal(s, idx(s, 1, 1)).state
  assert.equal(st.open[idx(s, 1, 1)], true)
  assert.equal(count(st, idx(s, 1, 1)), 1)
  assert.equal(canChord(st, idx(s, 1, 1)), false, '还没插旗')
  assert.equal(chord(st, idx(s, 1, 1)).state, st)
  st = toggleFlag(st, 0)
  assert.equal(flagsAround(st, idx(s, 1, 1)), 1)
  assert.equal(canChord(st, idx(s, 1, 1)), true)
  const ok = chord(st, idx(s, 1, 1))
  assert.ok(ok.opened.length >= 7)
  assert.equal(ok.state.open[0], false, '插旗的不翻')
  assert.notEqual(ok.state.status, 'lost')
  // 旗插错:把旗插在 (0,1) 上,数字 1 的周围「旗够了」,翻开时踩到真正的雷 (0,0)
  let wrong = reveal(s, idx(s, 1, 1)).state
  wrong = toggleFlag(wrong, idx(s, 0, 1))
  const boom = chord(wrong, idx(s, 1, 1))
  assert.equal(boom.state.status, 'lost')
  assert.equal(boom.state.boom, 0)
})

test('计时只在进行中走', () => {
  const s = newGame('easy', 5)
  assert.equal(tickTime(s, 1000).elapsed, 0, '第一下之前不计时')
  const p = reveal(s, 40).state
  assert.equal(tickTime(p, 1500).elapsed, 1500)
  const lost = { ...p, status: 'lost' as const }
  assert.equal(tickTime(lost, 1000), lost)
})

test('种子可复现:同一个种子、同一串操作,结果一样', () => {
  const play = (seed: number) => {
    let s = newGame('medium', seed)
    s = reveal(s, 100).state
    s = toggleFlag(s, 3)
    s = reveal(s, 250).state
    return JSON.stringify(save(s))
  }
  assert.equal(play(11), play(11))
  assert.notEqual(play(11), play(12))
})

test('邻格:角上 3 个、边上 5 个、中间 8 个', () => {
  const s = newGame('easy', 1)
  assert.equal(neighbors(s, 0).length, 3)
  assert.equal(neighbors(s, 4).length, 5)
  assert.equal(neighbors(s, 40).length, 8)
})

test('存档往返;坏存档读不出来而不是崩', () => {
  let s = newGame('medium', 21)
  s = reveal(s, 120).state
  s = toggleFlag(s, 0)
  s = tickTime(s, 4321)
  const back = load(JSON.parse(JSON.stringify(save(s))))!
  assert.deepEqual(back.mine, s.mine)
  assert.deepEqual(back.open, s.open)
  assert.deepEqual(back.flag, s.flag)
  assert.equal(back.elapsed, 4321)
  assert.equal(back.status, 'playing')
  const saved = save(s)
  const bad = (patch: Record<string, unknown>) => load({ ...saved, ...patch })
  assert.equal(bad({ level: 'insane' }), null)
  assert.equal(bad({ cells: '0'.repeat(10) }), null, '格子数不对')
  assert.equal(bad({ mine: '0'.repeat(256) }), null, '进行中却没有雷')
  const minePos = s.mine.findIndex((m, i) => m && !s.flag[i])
  const cells = saved.cells.split('')
  cells[minePos] = '1'
  assert.equal(bad({ cells: cells.join('') }), null, '翻开的格子是雷,却没输')
  assert.equal(load('garbage'), null)
  const fresh = load(save(toggleFlag(newGame('hard', 2), 5)))!
  assert.equal(fresh.status, 'ready')
  assert.equal(fresh.flag[5], true)
  const lost = reveal(s, minePos).state
  assert.equal(load(save(lost))!.boom, minePos)
})

test('最好成绩:每档分开记最快、赢的局数、玩的局数;两台设备合并取最好', () => {
  const won = { ...newGame('easy', 1), status: 'won' as const, elapsed: 42_000 }
  let b = updateBest(EMPTY_BEST, won)
  assert.deepEqual(b.easy, { time: 42_000, wins: 1, games: 1 })
  b = updateBest(b, { ...won, elapsed: 50_000 })
  assert.equal(b.easy.time, 42_000, '慢的不覆盖快的')
  b = updateBest(b, { ...won, status: 'lost' })
  assert.deepEqual(b.easy, { time: 42_000, wins: 2, games: 3 })
  assert.deepEqual(b.medium, { time: 0, wins: 0, games: 0 })
  const other = { ...EMPTY_BEST, easy: { time: 30_000, wins: 1, games: 9 }, hard: { time: 900_000, wins: 1, games: 1 } }
  const m = mergeBest(b, other)
  assert.deepEqual(m.easy, { time: 30_000, wins: 2, games: 9 })
  assert.equal(m.hard.time, 900_000, '一边没有纪录时取有的那边')
  assert.equal(loadBest({ v: 2 }), null)
  assert.deepEqual(loadBest({ v: 1 }), EMPTY_BEST)
})
