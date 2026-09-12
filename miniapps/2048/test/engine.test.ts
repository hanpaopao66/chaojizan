import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  WIN, canMove, emptyCells, fromBoard, load, maxTile, move, newGame, rand, save, slideLine, spawn,
  toBoard, updateBest,
} from '../src/engine'
import { TILE_BEYOND, TILE_COLORS, contrast } from '../src/palette'

test('一行的滑动合并:文档里的两个例子', () => {
  assert.deepEqual(slideLine([2, 2, 2, 2]).out, [4, 4, 0, 0])
  assert.deepEqual(slideLine([4, 4, 8, 8]).out, [8, 16, 0, 0])
  assert.equal(slideLine([4, 4, 8, 8]).gained, 24)
})

test('每块每步最多合并一次', () => {
  assert.deepEqual(slideLine([2, 2, 4, 0]).out, [4, 4, 0, 0], '合出来的 4 不再和后面的 4 合')
  assert.deepEqual(slideLine([4, 0, 2, 2]).out, [4, 4, 0, 0])
  assert.deepEqual(slideLine([8, 4, 4, 8]).out, [8, 8, 8, 0])
  assert.deepEqual(slideLine([0, 0, 0, 2]).out, [2, 0, 0, 0])
})

test('四个方向', () => {
  const s = fromBoard([[2, 0, 0, 2], [0, 0, 0, 0], [0, 4, 0, 0], [0, 4, 0, 0]])
  assert.deepEqual(toBoard(move(s, 'left').state.tiles)[0].slice(0, 1), [4])
  const right = move(s, 'right')
  assert.equal(toBoard(right.state.tiles)[0][3], 4)
  const down = move(s, 'down')
  assert.equal(toBoard(down.state.tiles)[3][1], 8)
  assert.equal(down.gained, 8)
  const up = move(s, 'up')
  assert.equal(toBoard(up.state.tiles)[0][1], 8)
})

test('动不了的方向不算一步,也不出新块', () => {
  const s = fromBoard([[2, 4, 8, 16], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])
  const r = move(s, 'left')
  assert.equal(r.moved, false)
  assert.equal(r.state, s)
  assert.equal(move(s, 'up').moved, false)
  assert.equal(move(s, 'down').moved, true)
})

test('只在空格出块;出 2 或 4', () => {
  let s = fromBoard([[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 0]])
  const r = spawn(s)
  assert.deepEqual([r.tile!.row, r.tile!.col], [3, 3])
  assert.ok([2, 4].includes(r.tile!.value))
  s = r.state
  assert.equal(spawn(s).tile, null, '满了不出')
  let twos = 0
  let seed = 7
  for (let i = 0; i < 2000; i++) {
    const st = spawn(fromBoard([[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], { seed }))
    if (st.tile!.value === 2) twos++
    seed = st.state.seed
  }
  assert.ok(twos > 1700 && twos < 1900, `约 90% 是 2,实际 ${twos / 20}%`)
})

test('无路可走判定', () => {
  assert.equal(canMove(fromBoard([[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 2]]).tiles), false)
  assert.equal(canMove(fromBoard([[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 4]]).tiles), true)
  const last = fromBoard([[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 8, 8]])
  const r = move(last, 'left')
  assert.equal(r.moved, true)
})

test('种子可复现:同一个种子、同一串操作,结果一样', () => {
  const play = (seed: number) => {
    let s = newGame(seed)
    for (const d of ['left', 'up', 'right', 'down', 'left', 'left', 'up'] as const) s = move(s, d).state
    return JSON.stringify(save(s))
  }
  assert.equal(play(42), play(42))
  assert.notEqual(play(42), play(43))
  assert.equal(newGame(1).tiles.length, 2, '开局两块')
  const [a, next] = rand(1)
  assert.ok(a >= 0 && a < 1 && next !== 1)
})

test('拼出 2048 只报一次;可以继续', () => {
  const s = fromBoard([[1024, 1024, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])
  const r = move(s, 'left')
  assert.equal(r.justWon, true)
  assert.equal(r.state.won, true)
  assert.equal(maxTile(r.state.tiles), WIN)
  const again = move(fromBoard(toBoard(r.state.tiles), { won: true }), 'right')
  assert.equal(again.justWon, false)
})

test('存档往返;坏存档读不出来而不是崩', () => {
  const s = move(newGame(9), 'left').state
  const back = load(JSON.stringify(save(s)))!
  assert.deepEqual(toBoard(back.tiles), toBoard(s.tiles))
  assert.equal(back.score, s.score)
  assert.equal(back.seed, s.seed)
  assert.equal(load('{"v":1,"board":[[3,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]]}'), null, '3 不是 2 的幂')
  assert.equal(load('garbage'), null)
})

test('最好成绩:分数、最大块、局数', () => {
  const s = fromBoard([[512, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], { score: 3000 })
  const b = updateBest({ v: 1, score: 5000, max_tile: 256, games: 3 }, s, true)
  assert.deepEqual(b, { v: 1, score: 5000, max_tile: 512, games: 4 })
})

test('方块数字和底色的对比度 ≥ 4.5:1', () => {
  for (const [v, c] of Object.entries(TILE_COLORS)) {
    assert.ok(contrast(c.bg, c.fg) >= 4.5, `${v}:${contrast(c.bg, c.fg).toFixed(2)}`)
  }
  assert.ok(contrast(TILE_BEYOND.bg, TILE_BEYOND.fg) >= 4.5)
})

test('合并时被吃掉的块记录它滑到的位置(界面先滑过去再消失)', () => {
  const s = fromBoard([[0, 2, 0, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])
  const r = move(s, 'left')
  assert.equal(r.consumed.length, 2)
  assert.ok(r.consumed.every((c) => c.row === 0 && c.col === 0))
  assert.equal(r.merged[0].value, 4)
  assert.equal(emptyCells(r.state.tiles).length, 14)
})
