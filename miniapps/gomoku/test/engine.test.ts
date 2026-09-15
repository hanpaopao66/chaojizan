import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  CENTER, Color, EMPTY_BEST, Level, N, P, State, Stone, THREAT, WIN, aiMove, canUndo, candidates, chooseMove,
  classifyText, combine, fiveLine, load, loadBest, mergeBest, newGame, patternsAt, play, replay, revertBest, save, turn,
  undo, updateBest, vcf,
} from '../src/engine'

const at = (r: number, c: number) => r * N + c

/** 摆一个局面(不管先后顺序,只看棋盘) */
function board(black: Array<[number, number]>, white: Array<[number, number]>): Stone[] {
  const b: Stone[] = new Array(N * N).fill(0)
  for (const [r, c] of black) b[at(r, c)] = 1
  for (const [r, c] of white) b[at(r, c)] = 2
  return b
}

/** 对方(color)这时有没有「下一手就赢」的点 */
function hasThreat(b: Stone[], color: Color): boolean {
  return candidates(b).some((i) => combine(patternsAt(b, i, color)) >= THREAT)
}

/**
 * 沿着 vcf 给的变化一路走:每一步必须是冲四(对方只有一个点能堵,就替它堵上),
 * 最后成五或者成了两个成五点(活四、双四)才算真的赢
 */
function vcfWins(start: Stone[], color: Color): boolean {
  const b = start.slice()
  const other = (3 - color) as Color
  for (let step = 0; step < 12; step++) {
    const e = vcf(b, color, 10 - step)
    if (e < 0) return false
    b[e] = color
    if (fiveLine(b, e)) return true
    const pts = candidates(b).filter((x) => {
      b[x] = color
      const five = !!fiveLine(b, x)
      b[x] = 0
      return five
    })
    if (pts.length >= 2) return true
    if (pts.length !== 1) return false // 不是冲四
    b[pts[0]] = other
  }
  return false
}

test('棋型:连五、活四、冲四(含跳四)、活三(含跳活三)、眠三、活二、被堵死', () => {
  assert.equal(classifyText('__xxxxx__'), P.FIVE)
  assert.equal(classifyText('__xxxx___'), P.OPEN_FOUR)
  assert.equal(classifyText('oxxxx____'), P.FOUR, '一头被堵')
  assert.equal(classifyText('___xx_xx_'), P.FOUR, '跳四:中间空一格')
  assert.equal(classifyText('__xxx____'), P.OPEN_THREE)
  assert.equal(classifyText('__x_xx___'), P.OPEN_THREE, '跳活三')
  assert.equal(classifyText('o_xxx_o__'), P.THREE, '两头都只剩一格:成不了活四,是眠三')
  assert.equal(classifyText('ooxxx____'), P.THREE, '一头贴着对方')
  assert.equal(classifyText('___xx____'), P.OPEN_TWO)
  assert.equal(classifyText('ooo_x_ooo'), P.NONE, '窗口里只有 3 格空间,怎么下都成不了五')
  assert.equal(classifyText('x_xxx_x__'), P.OPEN_FOUR, '一条线上两个成五点,等于活四')
})

test('四个方向合起来:活四、双冲四、冲四活三都是「下一手就赢」', () => {
  assert.ok(combine([P.OPEN_FOUR, 0, 0, 0]) >= THREAT)
  assert.ok(combine([P.FOUR, P.FOUR, 0, 0]) >= THREAT)
  assert.ok(combine([P.FOUR, P.OPEN_THREE, 0, 0]) >= THREAT)
  assert.ok(combine([P.FOUR, P.THREE, 0, 0]) < THREAT, '冲四加眠三不是')
  assert.ok(combine([P.OPEN_THREE, P.OPEN_THREE, 0, 0]) > combine([P.FOUR, P.THREE, 0, 0]), '双活三次之')
  assert.equal(combine([P.FIVE, 0, 0, 0]), WIN)
})

test('连五判定:横、竖、两条斜线;六子也算赢', () => {
  const lines: Array<Array<[number, number]>> = [
    [[3, 3], [3, 4], [3, 5], [3, 6], [3, 7]],
    [[1, 9], [2, 9], [3, 9], [4, 9], [5, 9]],
    [[6, 6], [7, 7], [8, 8], [9, 9], [10, 10]],
    [[4, 14], [5, 13], [6, 12], [7, 11], [8, 10]],
  ]
  for (const l of lines) {
    const b = board(l, [])
    assert.deepEqual(fiveLine(b, at(...l[2])), l.map(([r, c]) => at(r, c)).sort((x, y) => x - y))
  }
  const four = board([[0, 0], [0, 1], [0, 2], [0, 3]], [])
  assert.equal(fiveLine(four, 0), null)
  const six = board([[9, 1], [9, 2], [9, 3], [9, 4], [9, 5], [9, 6]], [])
  assert.equal(fiveLine(six, at(9, 3))!.length, 6)
})

test('黑先、轮流落子;有子的地方落不了;连成五就结束,之后不能再落', () => {
  let s = newGame(1, 'medium', 1)
  assert.equal(turn(s), 1)
  s = play(s, CENTER)
  assert.equal(s.board[CENTER], 1)
  assert.equal(turn(s), 2)
  assert.equal(play(s, CENTER), s, '有子')
  const moves = [at(7, 7), at(8, 7), at(7, 8), at(8, 8), at(7, 9), at(8, 9), at(7, 10), at(8, 10), at(7, 11)]
  const done = replay(moves, 1, 'medium', 1)!
  assert.equal(done.winner, 1)
  assert.equal(done.line.length, 5)
  assert.equal(play(done, at(0, 0)), done)
})

test('下满没人连成五是和棋', () => {
  // 每行按 (行 + 列/2) 的奇偶交替两个一组:横、竖、斜最多连两子;黑 113、白 112,最后一手是黑
  const color = (r: number, c: number): Color => ((r + Math.floor(c / 2)) % 2 === 0 ? 1 : 2)
  const blacks: number[] = []
  const whites: number[] = []
  for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) (color(r, c) === 1 ? blacks : whites).push(at(r, c))
  assert.equal(blacks.length, 113)
  assert.equal(whites.length, 112)
  const moves: number[] = []
  for (let k = 0; k < whites.length; k++) moves.push(blacks[k + 1], whites[k])
  moves.push(blacks[0])
  const s = replay(moves, 1, 'easy', 1)!
  assert.equal(s.moves.length, N * N)
  assert.equal(s.winner, 3)
})

test('悔棋一步:连同电脑那一手退回去;悔过要再下一子才能再悔;赢了不能悔', () => {
  let s = newGame(1, 'easy', 7)
  assert.equal(canUndo(s), false, '还没下')
  s = play(s, CENTER)
  s = aiMove(s)
  assert.equal(s.moves.length, 2)
  assert.equal(canUndo(s), true)
  const u = undo(s)
  assert.equal(u.moves.length, 0, '退回到你落子之前')
  assert.equal(u.undone, true)
  assert.equal(canUndo(u), false)
  const again = aiMove(play(u, at(6, 6)))
  assert.equal(canUndo(again), true, '又下了一子,可以再悔')
  // 电脑还没应(比如刚落完就悔):只退你那一手
  const mine = play(again, at(3, 3))
  assert.equal(undo(mine).moves.length, again.moves.length)
  // 执白:电脑先手的第一子不能悔
  const white = aiMove(newGame(2, 'medium', 3))
  assert.equal(white.moves.length, 1)
  assert.equal(canUndo(white), false)
  const w2 = aiMove(play(white, at(6, 8)))
  assert.deepEqual(undo(w2).moves, white.moves)
  // 赢了不能悔;输了可以
  const won = replay([at(7, 7), at(0, 0), at(7, 8), at(0, 1), at(7, 9), at(0, 2), at(7, 10), at(0, 3), at(7, 11)], 1, 'easy', 1)!
  assert.equal(won.winner, 1)
  assert.equal(canUndo(won), false)
  const lost = replay([at(0, 0), at(7, 7), at(0, 2), at(7, 8), at(0, 4), at(7, 9), at(0, 6), at(7, 10), at(0, 8), at(7, 11)], 1, 'easy', 1)!
  assert.equal(lost.winner, 2)
  assert.equal(canUndo(lost), true)
  assert.equal(undo(lost).winner, 0)
  assert.equal(undo(lost).moves.length, 8)
})

test('电脑:空棋盘下天元;执白第一手贴着黑子', () => {
  assert.equal(chooseMove(new Array(N * N).fill(0), 1, 'hard', 1).i, CENTER)
  for (const level of ['easy', 'medium', 'hard'] as Level[]) {
    const i = chooseMove(board([[7, 7]], []), 2, level, 5).i
    const [r, c] = [Math.floor(i / N), i % N]
    assert.ok(Math.max(Math.abs(r - 7), Math.abs(c - 7)) <= 2, `${level}:${r},${c}`)
  }
})

test('电脑:自己能连五先连五(不去堵对方)', () => {
  const b = board([[10, 3], [10, 4], [10, 5], [10, 6]], [[3, 3], [3, 4], [3, 5], [3, 6]])
  for (const level of ['easy', 'medium', 'hard'] as Level[]) {
    const i = chooseMove(b, 2, level, 9).i
    assert.ok([at(3, 2), at(3, 7)].includes(i), `${level} 下在了 ${i}`)
  }
})

test('电脑:对方冲四一定堵(三档都是)', () => {
  const b = board([[7, 5], [7, 6], [7, 7], [7, 8]], [[7, 4], [9, 9]])
  for (const level of ['easy', 'medium', 'hard'] as Level[]) {
    for (let seed = 1; seed <= 5; seed++) assert.equal(chooseMove(b, 2, level, seed).i, at(7, 9), level)
  }
})

test('电脑(中等、困难):对方活三要堵,堵完对方没有「下一手就赢」的点', () => {
  const b = board([[7, 6], [7, 7], [7, 8]], [[8, 7], [6, 9]])
  assert.equal(hasThreat(b, 1), true, '不堵的话黑下一手能成活四')
  for (const level of ['medium', 'hard'] as Level[]) {
    for (let seed = 1; seed <= 5; seed++) {
      const i = chooseMove(b, 2, level, seed).i
      const after = b.slice()
      after[i] = 2
      assert.equal(hasThreat(after, 1), false, `${level} 种子 ${seed} 下在 ${i},没堵住`)
    }
  }
})

test('困难:算得出连续冲四;中等以下不算', () => {
  // 白:第 7 行三子(左边被黑堵)、第 10 列两子(上下都被黑堵)、第 6 行三子(右边被黑堵);
  // (5,13) 的黑子堵住 (8,10)-(6,12) 那条斜线,免得 (7,11) 一步就成冲四活三
  const b = board([[7, 6], [5, 10], [11, 10], [6, 14], [5, 13]],
    [[7, 7], [7, 8], [7, 9], [8, 10], [9, 10], [6, 11], [6, 12], [6, 13]])
  assert.equal(hasThreat(b, 2), false, '一步之内没有必胜点,得靠连续冲四')
  const first = vcf(b, 2)
  assert.ok(first >= 0)
  assert.equal(vcfWins(b, 2), true, '顺着算出来的变化走,每一步都是冲四,最后真的赢')
  assert.equal(chooseMove(b, 2, 'hard', 1).i, first)
  assert.equal(vcf(board([[7, 7]], [[7, 8]]), 1), -1, '开局没有连续冲四')
  assert.equal(vcfWins(board([[7, 7], [7, 8], [7, 9]], [[8, 8]]), 1), true, '轮到自己时有活三:下成活四就赢')
  assert.equal(vcfWins(board([[7, 7], [7, 8], [7, 9]], [[7, 6], [8, 8]]), 1), false, '一头被堵的眠三:冲一次四就没了')
})

test('困难:不走会被对方连续冲四冲死的点', () => {
  // 黑有一路连续冲四(和上一个测试同样的形状,颜色对调);白要走的点得先把它破掉
  const b = board([[7, 7], [7, 8], [7, 9], [8, 10], [9, 10], [6, 11], [6, 12], [6, 13]],
    [[7, 6], [5, 10], [11, 10], [6, 14], [5, 13], [12, 2]])
  assert.equal(hasThreat(b, 1), false)
  assert.ok(vcf(b, 1) >= 0)
  const i = chooseMove(b, 2, 'hard', 1).i
  const after = b.slice()
  after[i] = 2
  assert.equal(vcf(after, 1), -1, `白下在 ${i} 之后,黑还能连续冲四`)
})

test('电脑的应手可复现:同一个种子同一局,下法一样;困难档一手在 1 秒内算完', () => {
  const run = (seed: number, level: Level) => {
    let s = newGame(1, level, seed)
    for (const m of [at(7, 7), at(6, 6), at(8, 8), at(5, 9), at(9, 5)]) {
      s = play(s, s.board[m] ? candidates(s.board)[0] : m)
      s = aiMove(s)
      if (s.winner) break
    }
    return s.moves.join(',')
  }
  assert.equal(run(4, 'medium'), run(4, 'medium'))
  const t0 = Date.now()
  assert.equal(run(4, 'hard'), run(4, 'hard'))
  assert.ok(Date.now() - t0 < 5000, `困难档 10 手用了 ${Date.now() - t0}ms`)
})

test('存档往返;坏存档读不出来而不是崩', () => {
  let s = newGame(2, 'hard', 12)
  s = aiMove(s)
  s = aiMove(play(s, at(6, 6)))
  s = undo(s)
  const back = load(JSON.parse(JSON.stringify(save(s))))!
  assert.deepEqual(back.moves, s.moves)
  assert.deepEqual(back.board, s.board)
  assert.equal(back.human, 2)
  assert.equal(back.level, 'hard')
  assert.equal(back.undone, true)
  assert.equal(back.seed, s.seed)
  const bad = (patch: Record<string, unknown>) => load({ ...save(s), ...patch })
  assert.equal(bad({ moves: [0, 0] }), null, '同一格下两次')
  assert.equal(bad({ moves: [999] }), null)
  assert.equal(bad({ human: 3 }), null)
  assert.equal(bad({ level: 'god' }), null)
  const five = [at(7, 7), at(0, 0), at(7, 8), at(0, 1), at(7, 9), at(0, 2), at(7, 10), at(0, 3), at(7, 11)]
  assert.equal(bad({ moves: [...five, at(14, 14)] }), null, '分出胜负之后还有子')
  assert.equal(load({ ...save(s), moves: five })!.winner, 1)
  assert.equal(load('garbage'), null)
})

test('战绩:每档分开记赢、输、和;两台设备合并取大', () => {
  const won = { ...newGame(1, 'hard', 1), winner: 1 as const }
  const lost = { ...newGame(1, 'hard', 1), winner: 2 as const }
  const draw = { ...newGame(2, 'easy', 1), winner: 3 as const }
  let b = updateBest(EMPTY_BEST, won)
  b = updateBest(b, lost)
  b = updateBest(b, draw)
  b = updateBest(b, newGame(1, 'easy', 1) as State)
  assert.deepEqual(b.hard, { win: 1, lose: 1, draw: 0 })
  assert.deepEqual(b.easy, { win: 0, lose: 0, draw: 1 })
  assert.deepEqual(mergeBest(b, { ...EMPTY_BEST, hard: { win: 5, lose: 0, draw: 2 } }).hard, { win: 5, lose: 1, draw: 2 })
  assert.deepEqual(revertBest(b, lost).hard, { win: 1, lose: 0, draw: 0 }, '输了又悔棋:撤回那一笔')
  assert.deepEqual(revertBest(EMPTY_BEST, lost).hard, { win: 0, lose: 0, draw: 0 }, '不会减成负数')
  assert.equal(loadBest({ v: 9 }), null)
  assert.deepEqual(loadBest({ v: 1 }), EMPTY_BEST)
})
