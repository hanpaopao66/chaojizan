// 平衡/可赢性:
// - 混塔参考策略(按关卡 recommended 铺减速/溅射/穿甲/毒,有关卡先补对空):12 关固定种子全部满血 3 星,无尽撑过 20 波;
// - 纯豆荚炮参考策略:第 7 关起必须拿不到 3 星(≤2 星甚至输),因为豆荚炮打不到飞行虫;
//   前 6 关没有飞行虫,纯炮仍然能 3 星 —— 这是「前期教学、后期混塔」的设计曲线。
// 数值改强改弱了,先看这里。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { LEVELS } from '../src/levels'
import { enemyDef, towerDef } from '../src/data'
import { runLevel, summaryOf } from './helpers'

/** 混塔参考策略:满血 3 星通关 */
function assertMixedThreeStars(id: number): void {
  const level = LEVELS[id - 1]
  const r = runLevel(id, 12345, { strategy: 'mixed' })
  const s = summaryOf(r.state)
  assert.ok(r.won, `第 ${id} 关「${level.name}」混塔策略没赢:hp ${s.hp}/${s.maxHp},第 ${s.waves} 波,${Math.round(r.seconds)} 秒,塔 ${r.built.join('/')}`)
  assert.equal(r.stars, 3, `第 ${id} 关「${level.name}」混塔策略只拿到 ${r.stars} 星(hp ${s.hp}/${s.maxHp})`)
  assert.equal(s.hp, s.maxHp, `第 ${id} 关混塔策略通关时不是满血`)
  assert.ok(r.seconds < 600, `第 ${id} 关打了 ${Math.round(r.seconds)} 秒,太久了`)
}

/** 纯豆荚炮参考策略:最多 2 星(飞行的虫子它打不到) */
function assertPeaNoThree(id: number): void {
  const level = LEVELS[id - 1]
  const r = runLevel(id, 12345, { strategy: 'pea' })
  assert.ok(r.built.every((k) => k === 'pea'), `纯炮策略不该造别的塔:${r.built.join('/')}`)
  assert.ok(r.stars <= 2, `第 ${id} 关「${level.name}」纯豆荚炮拿到了 ${r.stars} 星,后期关卡不应该能只靠豆荚炮 3 星`)
  const level7 = LEVELS[6]
  void level7
}

/** 前 6 关没有飞行虫,纯炮能 3 星(说明前中期基础打法是成立的) */
function assertPeaThreeStars(id: number): void {
  const level = LEVELS[id - 1]
  const r = runLevel(id, 12345, { strategy: 'pea' })
  assert.ok(r.won, `第 ${id} 关「${level.name}」纯炮策略没赢`)
  assert.equal(r.stars, 3, `第 ${id} 关「${level.name}」纯炮只拿到 ${r.stars} 星`)
}

test('第 1 关「菜畦小径」:混塔策略满血 3 星', () => assertMixedThreeStars(1))
test('第 2 关「豆架迷宫」:混塔策略满血 3 星', () => assertMixedThreeStars(2))
test('第 3 关「南瓜回廊」:混塔策略满血 3 星', () => assertMixedThreeStars(3))
test('第 4 关「巨型青虫」:混塔策略满血 3 星(第一个 Boss)', () => assertMixedThreeStars(4))
test('第 5 关「落日果梯」:混塔策略满血 3 星', () => assertMixedThreeStars(5))
test('第 6 关「蜂糖栈道」:混塔策略满血 3 星', () => assertMixedThreeStars(6))
test('第 7 关「蛹灯夜径」:混塔策略满血 3 星(飞行虫登场)', () => assertMixedThreeStars(7))
test('第 8 关「果园守卫战」:混塔策略满血 3 星(果园 Boss)', () => assertMixedThreeStars(8))
test('第 9 关「月光虫道」:混塔策略满血 3 星', () => assertMixedThreeStars(9))
test('第 10 关「双孔巢门」:混塔策略满血 3 星(双入口)', () => assertMixedThreeStars(10))
test('第 11 关「毒雾深井」:混塔策略满血 3 星(双入口)', () => assertMixedThreeStars(11))
test('第 12 关「虫巢母体」:混塔策略满血 3 星(最终 Boss)', () => assertMixedThreeStars(12))

test('第 1 关:纯豆荚炮也能 3 星(基础教学关)', () => assertPeaThreeStars(1))
test('第 2 关:纯豆荚炮也能 3 星', () => assertPeaThreeStars(2))
test('第 3 关:纯豆荚炮也能 3 星', () => assertPeaThreeStars(3))
test('第 4 关:纯豆荚炮也能 3 星(地面 Boss)', () => assertPeaThreeStars(4))
test('第 5 关:纯豆荚炮也能 3 星', () => assertPeaThreeStars(5))
test('第 6 关:纯豆荚炮也能 3 星', () => assertPeaThreeStars(6))

test('第 7 关起纯豆荚炮拿不到 3 星(飞蛾/毒蜂只打得到地面塔)', () => assertPeaNoThree(7))
test('第 8 关纯豆荚炮拿不到 3 星', () => assertPeaNoThree(8))
test('第 9 关纯豆荚炮拿不到 3 星', () => assertPeaNoThree(9))
test('第 10 关纯豆荚炮拿不到 3 星', () => assertPeaNoThree(10))
test('第 11 关纯豆荚炮拿不到 3 星', () => assertPeaNoThree(11))
test('第 12 关纯豆荚炮拿不到 3 星', () => assertPeaNoThree(12))

test('混塔策略确实混了:解锁多种塔的关卡至少 3 种,有飞行虫的关卡一定造了对空塔', () => {
  for (const level of LEVELS) {
    const r = runLevel(level.id as number, 12345, { strategy: 'mixed' })
    const kinds = new Set(r.built)
    if (level.towers.length >= 3) {
      assert.ok(kinds.size >= 3, `第 ${level.id} 关混塔策略只造了 ${[...kinds].join('/')}`)
    }
    const hasAir = level.waves.some((w) => w.groups.some((g) => enemyDef(g.kind).flying))
    if (hasAir) assert.ok([...kinds].some((k) => towerDef(k).air), `第 ${level.id} 关混塔策略没造对空塔`)
  }
})

test('每关推荐序列都能用:过滤后非空,有飞行虫的关卡里要包含对空塔', () => {
  for (const level of LEVELS) {
    const usable = level.recommend.filter((k) => level.towers.includes(k))
    assert.ok(usable.length >= 3, `第 ${level.id} 关推荐序列过滤后太短`)
    const hasAir = level.waves.some((w) => w.groups.some((g) => enemyDef(g.kind).flying))
    if (hasAir) assert.ok(usable.some((k) => towerDef(k).air), `第 ${level.id} 关推荐序列没有对空塔`)
  }
})

test('无尽模式:混塔策略撑过 20 波(固定种子)', () => {
  const r = runLevel('endless', 12345, { stopWave: 20, maxSeconds: 1200, strategy: 'mixed' })
  assert.ok(r.survived, `无尽模式没撑到 20 波:第 ${r.state.wave} 波,hp ${r.state.hp}/${r.state.maxHp}`)
  assert.equal(r.state.over, null, '撑到 20 波时还没输')
  assert.ok(r.state.hp > 0)
  assert.ok(r.seconds < 900, `无尽 20 波用了 ${Math.round(r.seconds)} 秒,偏久`)
})

test('固定种子下同一份策略结果可复现', () => {
  const a = runLevel('endless', 777, { stopWave: 12, maxSeconds: 800, strategy: 'mixed' })
  const b = runLevel('endless', 777, { stopWave: 12, maxSeconds: 800, strategy: 'mixed' })
  assert.equal(a.state.hp, b.state.hp)
  assert.equal(a.state.wave, b.state.wave)
  assert.equal(a.state.gold, b.state.gold)
  assert.deepEqual(a.state.towers.map((t) => [t.slot, t.level]), b.state.towers.map((t) => [t.slot, t.level]))
})

test('每关都有 8 秒以上的开局准备时间(新手能放塔)', () => {
  for (const level of LEVELS) {
    assert.ok(level.firstPrep >= 8, `第 ${level.id} 关开局准备时间太短`)
  }
})
