import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  COLS, LOCK_MS, MAX_RESETS, Piece, ROWS, SHAPES, State, cellsOf, dropY, fits, gravity, hardDrop, levelOf, load,
  loadBest, mergeBest, move, newGame, rotate, save, softDrop, spawn, tick, updateBest,
} from '../src/engine'

/** 造一个局面:rows 是棋盘最底下几行('#' 有格子,'.' 空),其余是空的 */
function board(rows: string[], piece: Piece, rest: Partial<State> = {}): State {
  const cells = new Array(COLS * ROWS).fill(0)
  rows.forEach((line, i) => {
    const y = ROWS - rows.length + i
    for (let x = 0; x < COLS; x++) if (line[x] === '#') cells[y * COLS + x] = 3
  })
  return { ...newGame(1), cells, piece, lowest: piece.y, ...rest }
}
const I = 0
const O = 1
const T = 2
const key = (p: Piece) => cellsOf(p).map(([x, y]) => `${x},${y}`).sort().join(' ')

test('七种方块,每种四个朝向、四个格子;转四次回到原样;正方形转了也一样', () => {
  assert.equal(SHAPES.length, 7)
  for (const shapes of SHAPES) {
    assert.equal(shapes.length, 4)
    for (const cells of shapes) assert.equal(new Set(cells.map((c) => c.join())).size, 4)
  }
  // 长条:横 → 竖(第 2 列)→ 横(第 2 行)→ 竖(第 1 列)
  assert.deepEqual(SHAPES[I][1].map(([x]) => x), [2, 2, 2, 2])
  assert.deepEqual(SHAPES[I][2].map(([, y]) => y), [2, 2, 2, 2])
  const o = SHAPES[O].map((c) => c.map((p) => p.join()).sort().join(' '))
  assert.equal(new Set(o).size, 1)
  let s = newGame(5)
  s = { ...s, piece: { k: T, r: 0, x: 3, y: 5 } }
  const start = key(s.piece!)
  for (let i = 0; i < 4; i++) s = rotate(s, 1)
  assert.equal(key(s.piece!), start)
  assert.equal(key(rotate(rotate(s, 1), -1).piece!), start, '顺时针再逆时针回原样')
})

test('七个一袋:每 7 块里七种各一个', () => {
  let s = newGame(123)
  const seen: number[] = [s.piece!.k]
  for (let i = 0; i < 13; i++) {
    s = hardDrop({ ...s, cells: new Array(COLS * ROWS).fill(0) }).state
    seen.push(s.piece!.k)
  }
  assert.deepEqual(seen.slice(0, 7).sort(), [0, 1, 2, 3, 4, 5, 6])
  assert.deepEqual(seen.slice(7, 14).sort(), [0, 1, 2, 3, 4, 5, 6])
})

test('新方块横着居中、贴着顶出来', () => {
  assert.deepEqual(cellsOf(spawn(I)).map(([, y]) => y), [0, 0, 0, 0])
  assert.deepEqual(cellsOf(spawn(I)).map(([x]) => x), [3, 4, 5, 6])
  assert.deepEqual(cellsOf(spawn(O)).map(([x]) => x).sort(), [4, 4, 5, 5])
  assert.equal(Math.min(...cellsOf(spawn(T)).map(([, y]) => y)), 0)
})

test('左右挪:到墙挪不动;挡着的格子也挪不过去', () => {
  let s = board([], { k: O, r: 0, x: 4, y: 5 })
  for (let i = 0; i < 10; i++) s = move(s, -1)
  assert.equal(s.piece!.x, 0)
  for (let i = 0; i < 10; i++) s = move(s, 1)
  assert.equal(s.piece!.x, COLS - 2)
  const wall = board(['...#......', '...#......'], { k: O, r: 0, x: 4, y: ROWS - 2 })
  assert.equal(move(wall, -1).piece!.x, 4, '左边有格子挡着')
})

test('贴着墙转不开时踢墙:竖着的长条贴左墙,转成横的往右挪', () => {
  const s = board([], { k: I, r: 3, x: -1, y: 5 }) // 竖在第 0 列
  assert.ok(fits(s.cells, s.piece!))
  const r = rotate(s, 1)
  assert.equal(r.piece!.r, 0)
  assert.ok(cellsOf(r.piece!).every(([x]) => x >= 0 && x < COLS))
  // 四面都堵死就转不了,原样返回
  const stuck = board(['##.#######', '##.#######', '##.#######', '##.#######'], { k: I, r: 1, x: 0, y: ROWS - 4 })
  assert.ok(fits(stuck.cells, stuck.piece!))
  assert.equal(rotate(stuck, 1), stuck)
})

test('自然下落:第 1 级每 1000ms 一格;攒不够不动', () => {
  const s = board([], { k: T, r: 0, x: 3, y: 0 })
  assert.equal(tick(s, 999).state.piece!.y, 0)
  assert.equal(tick(tick(s, 999).state, 1).state.piece!.y, 1)
  assert.equal(tick(s, 3000).state.piece!.y, 3, '卡了一下补上')
})

test('落地后 0.5 秒固定;挪动会重新计时,但最多 15 次', () => {
  let s = board([], { k: O, r: 0, x: 4, y: ROWS - 2 })
  let r = tick(s, LOCK_MS - 1)
  assert.equal(r.locked, false)
  r = tick(r.state, 1)
  assert.equal(r.locked, true)
  assert.equal(r.state.cells[(ROWS - 1) * COLS + 4], O + 1)
  // 一直挪:前 15 次每次都重新计时
  s = board([], { k: O, r: 0, x: 4, y: ROWS - 2 })
  for (let i = 0; i < MAX_RESETS; i++) {
    s = tick(s, LOCK_MS - 10).state
    s = move(s, i % 2 ? 1 : -1)
    assert.equal(s.lock, 0, `第 ${i + 1} 次挪动重新计时`)
  }
  s = tick(s, LOCK_MS - 10).state
  s = move(s, 1)
  assert.ok(s.lock > 0, '次数用完,不再重新计时')
  assert.equal(tick(s, 10).locked, true)
})

test('软降一格得 1 分;硬降每格 2 分、马上固定、换下一块', () => {
  const s = board([], { k: T, r: 0, x: 3, y: 0 })
  const d = softDrop(s)
  assert.equal(d.piece!.y, 1)
  assert.equal(d.score, 1)
  const h = hardDrop(s)
  const fell = dropY(s.cells, s.piece!) - s.piece!.y
  assert.equal(fell, ROWS - 2)
  assert.equal(h.locked, true)
  assert.equal(h.state.score, 2 * fell)
  assert.equal(h.gained, 2 * fell)
  assert.equal(h.state.piece!.k, s.next, '下一块上场')
})

test('满行消除:消 1 行 100 分,一次 4 行 800 分(再乘等级);上面的格子掉下来', () => {
  const one = board(['#.........', '#########.'], { k: I, r: 1, x: 7, y: ROWS - 4 })
  // 竖着的长条插进最右边那一列:只有最底行满
  const r1 = hardDrop(one)
  assert.deepEqual(r1.cleared, [ROWS - 1])
  assert.equal(r1.gained, 100)
  assert.equal(r1.state.lines, 1)
  assert.equal(r1.state.cells[(ROWS - 1) * COLS], 3, '上面那格掉到了最底行')
  assert.ok(r1.board, '给界面留了消行之前的棋盘')
  const tetra = board(['#########.', '#########.', '#########.', '#########.'],
    { k: I, r: 1, x: 7, y: 0 }, { level: 3, lines: 20 })
  const r4 = hardDrop(tetra)
  assert.equal(r4.cleared.length, 4)
  assert.equal(r4.gained - 2 * (ROWS - 4), 800 * 3)
  assert.ok(r4.state.cells.every((v) => v === 0), '全消干净了')
})

test('每消 10 行升一级,越往后落得越快,最快 50ms', () => {
  assert.equal(levelOf(0), 1)
  assert.equal(levelOf(9), 1)
  assert.equal(levelOf(10), 2)
  assert.equal(gravity(1), 1000)
  let last = gravity(1)
  for (let l = 2; l <= 40; l++) {
    assert.ok(gravity(l) <= last && gravity(l) >= 50)
    last = gravity(l)
  }
  const s = board(['#########.'], { k: I, r: 1, x: 7, y: 0 }, { lines: 9 })
  assert.equal(hardDrop(s).state.level, 2)
})

test('新方块出不来就结束', () => {
  // 顶上正中间(出生的位置)有一格占着;这一块落到左下角,下一块 T 出不来
  const s = { ...board([], { k: O, r: 0, x: 0, y: 5 }), next: T }
  s.cells = s.cells.slice()
  s.cells[4] = 5
  const r = hardDrop(s)
  assert.equal(r.state.over, true)
  assert.equal(r.state.piece, null)
  assert.equal(move(r.state, 1), r.state, '结束了什么都动不了')
})

test('停在顶上外面算到顶;但同时消了行、掉得回棋盘里就接着玩', () => {
  // 第 0–2 行只差最右一格,下面每行都缺第 1 格、最右一格是满的:竖长条插进最右一列,最上面一格探在顶上外面
  const rows = ['#########.', '#########.', '#########.']
  for (let i = 3; i < ROWS; i++) rows.push('#.########')
  const tall = board(rows, { k: I, r: 1, x: 7, y: -1 })
  assert.equal(dropY(tall.cells, tall.piece!), -1)
  const r = hardDrop(tall)
  assert.deepEqual(r.cleared, [0, 1, 2])
  assert.equal(r.state.over, false, '消了 3 行,探出去的那格掉回了棋盘')
  assert.equal(r.state.cells[2 * COLS + 9], I + 1)
  // 没消行、方块停在顶上外面:结束
  const stack = ['..#######.']
  for (let i = 1; i < ROWS; i++) stack.push('#.########')
  const s = board(stack, { k: O, r: 0, x: 0, y: -2 })
  assert.ok(fits(s.cells, s.piece!))
  const top = hardDrop(s)
  assert.deepEqual(top.cleared, [])
  assert.equal(top.state.over, true)
})

test('种子可复现:同一个种子、同一串操作,结果一样', () => {
  const play = (seed: number) => {
    let s = newGame(seed)
    const ops = ['L', 'R', 'U', 'D', 'H', 'L', 'L', 'H', 'U', 'H', 'R', 'R', 'H', 'H']
    for (const op of ops) {
      if (op === 'L') s = move(s, -1)
      else if (op === 'R') s = move(s, 1)
      else if (op === 'U') s = rotate(s, 1)
      else if (op === 'D') s = softDrop(s)
      else s = hardDrop(s).state
      s = tick(s, 16).state
    }
    return JSON.stringify(save(s))
  }
  assert.equal(play(99), play(99))
  assert.notEqual(play(99), play(100))
})

test('存档往返;坏存档读不出来而不是崩', () => {
  let s = newGame(8)
  s = hardDrop(move(s, -1)).state
  s = move(rotate(s, 1), 1)
  const back = load(JSON.parse(JSON.stringify(save(s))))!
  assert.deepEqual(back.cells, s.cells)
  assert.deepEqual(back.piece, s.piece)
  assert.equal(back.next, s.next)
  assert.deepEqual(back.bag, s.bag)
  assert.equal(back.seed, s.seed)
  assert.equal(back.score, s.score)
  const bad = (patch: Record<string, unknown>) => load({ ...save(s), ...patch })
  assert.equal(bad({ cells: '0'.repeat(10) }), null, '格子数不对')
  assert.equal(bad({ cells: '9'.repeat(COLS * ROWS) }), null, '不认识的格子')
  assert.equal(bad({ piece: { k: 9, r: 0, x: 3, y: 0 } }), null)
  assert.equal(bad({ piece: { k: 1, r: 0, x: -5, y: 0 } }), null, '方块在棋盘外面')
  assert.equal(bad({ piece: null }), null, '没结束却没有方块')
  assert.equal(bad({ bag: [1, 1] }), null, '袋子里有重复')
  assert.equal(bad({ next: 7 }), null)
  assert.equal(load('garbage'), null)
  assert.equal(load({ ...save(s), over: true, piece: null })!.over, true)
})

test('最好成绩:分数、行数、等级取大,局数累加,两台设备合并', () => {
  const s = { ...newGame(1), score: 900, lines: 12, level: 2 }
  assert.deepEqual(updateBest({ v: 1, score: 1000, lines: 5, level: 1, games: 2 }, s, true),
    { v: 1, score: 1000, lines: 12, level: 2, games: 3 })
  assert.deepEqual(mergeBest({ v: 1, score: 1, lines: 50, level: 6, games: 9 }, { v: 1, score: 7, lines: 3, level: 1, games: 2 }),
    { v: 1, score: 7, lines: 50, level: 6, games: 9 })
  assert.equal(loadBest({ v: 3 }), null)
})
