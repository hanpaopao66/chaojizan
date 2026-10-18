// 平衡/可赢性:固定种子的基准策略(先铺 14 座豆荚炮再升级)要能满血 3 星通关每一关,
// 无尽模式要能撑过 20 波。数据改弱/改强了,先看这里。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { LEVELS } from '../src/levels'
import { runLevel, summaryOf } from './helpers'

/** 跑一关并断言「满血 3 星通关」 */
function assertThreeStars(id: number): void {
  const level = LEVELS[id - 1]
  const r = runLevel(id, 12345)
  const s = summaryOf(r.state)
  assert.ok(r.won, `第 ${id} 关「${level.name}」基准策略没赢:hp ${s.hp}/${s.maxHp},第 ${s.waves} 波,${Math.round(r.seconds)} 秒`)
  assert.equal(r.stars, 3, `第 ${id} 关「${level.name}」只拿到 ${r.stars} 星(hp ${s.hp}/${s.maxHp})`)
  assert.equal(s.hp, s.maxHp, `第 ${id} 关「${level.name}」通关时不是满血`)
  assert.equal(s.waves, level.waves.length, `第 ${id} 关应该打完全部 ${level.waves.length} 波`)
  assert.ok(r.seconds < 600, `第 ${id} 关打了 ${Math.round(r.seconds)} 秒,太久了`)
}

test('第 1 关「菜畦小径」:基准策略满血 3 星', () => assertThreeStars(1))
test('第 2 关「豆架迷宫」:基准策略满血 3 星', () => assertThreeStars(2))
test('第 3 关「南瓜回廊」:基准策略满血 3 星', () => assertThreeStars(3))
test('第 4 关「巨型青虫」:基准策略满血 3 星(第一个 Boss)', () => assertThreeStars(4))
test('第 5 关「落日果梯」:基准策略满血 3 星', () => assertThreeStars(5))
test('第 6 关「蜂糖栈道」:基准策略满血 3 星', () => assertThreeStars(6))
test('第 7 关「蛹灯夜径」:基准策略满血 3 星', () => assertThreeStars(7))
test('第 8 关「果园守卫战」:基准策略满血 3 星(果园 Boss)', () => assertThreeStars(8))
test('第 9 关「月光虫道」:基准策略满血 3 星', () => assertThreeStars(9))
test('第 10 关「双孔巢门」:基准策略满血 3 星(双入口)', () => assertThreeStars(10))
test('第 11 关「毒雾深井」:基准策略满血 3 星(双入口)', () => assertThreeStars(11))
test('第 12 关「虫巢母体」:基准策略满血 3 星(最终 Boss)', () => assertThreeStars(12))

test('无尽模式:基准策略撑过 20 波(固定种子)', () => {
  const r = runLevel('endless', 12345, { stopWave: 20, maxSeconds: 1200 })
  assert.ok(r.survived, `无尽模式没撑到 20 波:第 ${r.state.wave} 波,hp ${r.state.hp}/${r.state.maxHp}`)
  assert.equal(r.state.over, null, '撑到 20 波时还没输')
  assert.ok(r.state.hp > 0)
  assert.ok(r.state.wave >= 20)
  assert.ok(r.seconds < 900, `无尽 20 波用了 ${Math.round(r.seconds)} 秒,偏久`)
})

test('无尽模式:固定种子下同一份策略结果可复现', () => {
  const a = runLevel('endless', 777, { stopWave: 12, maxSeconds: 800 })
  const b = runLevel('endless', 777, { stopWave: 12, maxSeconds: 800 })
  assert.equal(a.state.hp, b.state.hp)
  assert.equal(a.state.wave, b.state.wave)
  assert.equal(a.state.gold, b.state.gold)
  assert.deepEqual(a.state.towers.map((t) => [t.slot, t.level]), b.state.towers.map((t) => [t.slot, t.level]))
})

test('每关的首波都有 3 秒以上准备时间(新手能放塔)', () => {
  for (const level of LEVELS) {
    assert.ok(level.firstPrep >= 8, `第 ${level.id} 关开局准备时间太短`)
  }
})
