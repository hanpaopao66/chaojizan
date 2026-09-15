import assert from 'node:assert/strict'
import { test } from 'node:test'
import { contrast } from '../../shared/src/color'
import {
  COLS, ROWS, START_LEN, State, interval, load, loadBest, mergeBest, newGame, placeFood, rowCol, save, step,
  turn, updateBest,
} from '../src/engine'
import { DARK, LIGHT } from '../src/palette'

/** 造一个局面:snake 用 [行, 列] 写,头在前 */
function at(cells: Array<[number, number]>, food: [number, number], rest: Partial<State> = {}): State {
  const s = newGame(1)
  return { ...s, snake: cells.map(([r, c]) => r * COLS + c), food: food[0] * COLS + food[1], ...rest }
}
const head = (s: State) => rowCol(s, s.snake[0])

test('开局:3 节、头朝上、食物不压在蛇身上', () => {
  const s = newGame(42)
  assert.equal(s.snake.length, START_LEN)
  assert.equal(s.dir, 'up')
  assert.ok(s.food >= 0 && s.snake.indexOf(s.food) < 0)
  assert.deepEqual(head(s), [ROWS / 2, COLS / 2])
})

test('往前走一格,尾巴跟上;吃到了长一节、得 1 分、换个地方出食物', () => {
  let s = at([[5, 5], [6, 5], [7, 5]], [4, 5])
  const r = step(s)
  assert.equal(r.ate, true)
  assert.equal(r.state.score, 1)
  assert.equal(r.state.snake.length, 4)
  assert.deepEqual(head(r.state), [4, 5])
  assert.ok(r.state.food >= 0 && r.state.snake.indexOf(r.state.food) < 0)
  s = at([[5, 5], [6, 5], [7, 5]], [0, 0])
  const r2 = step(s)
  assert.equal(r2.ate, false)
  assert.deepEqual(r2.state.snake.map((i) => rowCol(s, i)), [[4, 5], [5, 5], [6, 5]])
})

test('撞墙结束', () => {
  const s = at([[0, 3], [1, 3], [2, 3]], [9, 9])
  const r = step(s)
  assert.equal(r.died, true)
  assert.equal(r.state.over, true)
  assert.equal(r.state.cause, 'wall')
  assert.deepEqual(r.state.snake, s.snake, '撞墙那一步蛇不动')
  const left = step(turn(at([[3, 0], [3, 1], [3, 2]], [9, 9], { dir: 'left' }), 'left'))
  assert.equal(left.state.cause, 'wall')
})

test('咬到自己结束;但头可以跟进尾巴刚离开的格子', () => {
  // 5 节盘成一圈:头 (5,5) 往左走会咬到 (5,4)
  const ring = at([[5, 5], [6, 5], [6, 4], [5, 4], [4, 4]], [0, 0], { dir: 'up' })
  const bite = step(turn(ring, 'left'))
  assert.equal(bite.died, true)
  assert.equal(bite.state.cause, 'self')
  // 4 节成一个方块:头往尾巴那格走,尾巴同时挪走,不算咬到
  const square = at([[5, 5], [6, 5], [6, 4], [5, 4]], [0, 0], { dir: 'up' })
  const chase = step(turn(square, 'left'))
  assert.equal(chase.died, false)
  assert.deepEqual(head(chase.state), [5, 4])
})

test('吃到食物那一步尾巴不动,所以跟进尾巴的格子会咬到', () => {
  const square = at([[5, 5], [6, 5], [6, 4], [5, 4]], [5, 4], { dir: 'up' })
  // 食物放在尾巴上(实际不会发生,但规则要自洽):这一步长一节,尾巴不走,就咬到了
  const r = step(turn(square, 'left'))
  assert.equal(r.state.cause, 'self')
})

test('掉头不算;同方向不算;一格之内最多排两个转向', () => {
  const s = at([[5, 5], [6, 5], [7, 5]], [0, 0], { dir: 'up' })
  assert.equal(turn(s, 'down'), s, '反方向')
  assert.equal(turn(s, 'up'), s, '同方向')
  let t = turn(s, 'left')
  t = turn(t, 'down') // 先左再下:排两个,两格之内掉过头来
  assert.deepEqual(t.queue, ['left', 'down'])
  assert.equal(turn(t, 'right'), t, '排满了')
  const a = step(t).state
  assert.deepEqual(head(a), [5, 4])
  const b = step(a).state
  assert.deepEqual(head(b), [6, 4])
  assert.equal(b.dir, 'down')
  // 排着的最后一个是左,再按右是它的反方向,不算
  assert.equal(turn(turn(s, 'left'), 'right').queue.length, 1)
})

test('速度随长度慢慢加快,有下限', () => {
  assert.equal(interval(0), 180)
  let last = interval(0)
  for (let k = 1; k <= 300; k++) {
    const ms = interval(k)
    assert.ok(ms <= last, `第 ${k} 个比前一个慢了`)
    assert.ok(ms >= 70)
    last = ms
  }
  assert.ok(interval(10) > 140 && interval(10) < 160, '吃 10 个还不算快')
})

test('占满格子算赢', () => {
  // 3×2 的小格子:蛇 5 节,吃掉最后一格就满了
  const cols = 3
  const s: State = { cols, rows: 2, snake: [1, 2, 5, 4, 3], dir: 'left', queue: [], food: 0, score: 2, seed: 1,
    steps: 10, over: false, won: false, cause: '' }
  const r = step(s)
  assert.equal(r.ate, true)
  assert.equal(r.state.won, true)
  assert.equal(r.state.over, true)
  assert.equal(r.state.food, -1)
  assert.equal(r.state.cause, 'full')
  assert.deepEqual(placeFood([0, 1, 2], 3, 1, 5), [-1, 5])
})

test('种子可复现:同一个种子、同一串操作,结果一样', () => {
  const play = (seed: number) => {
    let s = newGame(seed)
    const moves = ['left', '', '', 'up', '', 'right', '', '', 'up', '', 'left'] as const
    for (const m of moves) {
      if (m) s = turn(s, m)
      s = step(s).state
    }
    return JSON.stringify(save(s))
  }
  assert.equal(play(7), play(7))
  const foods = new Set([1, 2, 3, 4, 5, 6, 7, 8].map((seed) => newGame(seed).food))
  assert.ok(foods.size > 1, '不同的种子,食物放的地方不一样')
})

test('存档往返;坏存档读不出来而不是崩', () => {
  let s = newGame(3)
  s = step(turn(s, 'left')).state
  const back = load(JSON.parse(JSON.stringify(save(s))))!
  assert.deepEqual(back.snake, s.snake)
  assert.equal(back.food, s.food)
  assert.equal(back.seed, s.seed)
  assert.equal(back.dir, s.dir)
  assert.deepEqual(back.queue, [])
  const bad = (patch: Record<string, unknown>) => load({ ...save(s), ...patch })
  assert.equal(bad({ snake: [0, 2, 3] }), null, '蛇身不连着')
  assert.equal(bad({ snake: [17, 17, 18] }), null, '重叠')
  assert.equal(bad({ food: s.snake[1] }), null, '食物压在蛇身上')
  assert.equal(bad({ cols: 10 }), null, '格子数不对')
  assert.equal(bad({ dir: 'north' }), null)
  assert.equal(bad({ v: 2 }), null)
  assert.equal(load('garbage'), null)
  assert.equal(load(null), null)
})

test('最好成绩:分数取大,局数累加,两台设备合并取大', () => {
  const s = { ...newGame(1), score: 12 }
  assert.deepEqual(updateBest({ v: 1, score: 20, games: 3 }, s, true), { v: 1, score: 20, games: 4 })
  assert.deepEqual(updateBest({ v: 1, score: 5, games: 3 }, s, false), { v: 1, score: 12, games: 3 })
  assert.deepEqual(mergeBest({ v: 1, score: 5, games: 9 }, { v: 1, score: 8, games: 2 }), { v: 1, score: 8, games: 9 })
  assert.equal(loadBest({ v: 2 }), null)
  assert.deepEqual(loadBest({ v: 1, score: -3, games: 'x' }), { v: 1, score: 0, games: 0 })
})

test('配色:蛇、蛇头、食物、撞到的标记和两种底色的对比度 ≥ 3:1,亮暗两套都算', () => {
  for (const [name, p] of Object.entries({ 亮: LIGHT, 暗: DARK })) {
    for (const fg of ['snake', 'head', 'food', 'crash'] as const) {
      for (const bg of ['boardA', 'boardB'] as const) {
        const c = contrast(p[fg], p[bg])
        assert.ok(c >= 3, `${name}色 ${fg} 对 ${bg}:${c.toFixed(2)}`)
      }
    }
    assert.ok(contrast(p.eye, p.head) >= 3, `${name}色 眼睛对蛇头`)
  }
})
