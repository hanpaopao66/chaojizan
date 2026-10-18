// 平衡模拟单测:固定种子跑完整对局,不再依赖人工试玩。
// 验收口径(玩家视角):休闲档胜率 > 60%,困难档 < 40%;三套牌都能玩(每套 38%–62%)。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { HEROES } from '../src/data'
import { balanceReport, simulateGame } from '../src/sim'
import type { Level } from '../src/types'

test('平衡:休闲档玩家胜率 > 60%、困难档 < 40%(固定种子,先后手各半)', () => {
  const report = balanceReport({ gamesPerCell: 150, seed: 20261018, playerLevel: 'normal' })
  assert.ok(report.total.games >= 2000, `样本太少:${report.total.games}`)
  assert.equal(report.byLevel.easy.winRate > 0.6, true,
    `休闲档胜率 ${(report.byLevel.easy.winRate * 100).toFixed(1)}% 应该 > 60%`)
  assert.equal(report.byLevel.hard.winRate < 0.4, true,
    `困难档胜率 ${(report.byLevel.hard.winRate * 100).toFixed(1)}% 应该 < 40%`)
  // 玩家实际对局永远是先手:先手视角也要站得住(困难档 < 45%)
  const first = (level: Level) => {
    const cells = report.cells.filter((c) => c.level === level && c.first === 0)
    const games = cells.reduce((a, c) => a + c.games, 0)
    const wins = cells.reduce((a, c) => a + c.wins, 0)
    return wins / games
  }
  assert.equal(first('easy') > 0.6, true, `先手休闲胜率 ${(first('easy') * 100).toFixed(1)}% 应该 > 60%`)
  assert.equal(first('hard') < 0.45, true, `先手困难胜率 ${(first('hard') * 100).toFixed(1)}% 应该 < 45%`)
})

test('平衡:三套牌都能玩(每套总胜率 38%–62%),模拟不软锁、可复现', () => {
  const report = balanceReport({ gamesPerCell: 150, seed: 20261018, playerLevel: 'normal' })
  for (const h of HEROES) {
    const t = report.byHero[h.id]
    assert.ok(t.winRate > 0.38 && t.winRate < 0.62,
      `${h.title} 胜率 ${(t.winRate * 100).toFixed(1)}%,超出 38%–62% 的「能玩」区间`)
  }
  // 所有模拟对局都必须正常结束(没有卡死)
  for (const c of report.cells) assert.equal(c.stuck, 0, `${c.playerHero}/${c.level}/first=${c.first} 出现卡死`)
  // 固定种子:同样参数跑两遍结果完全一样
  const small = { gamesPerCell: 20, seed: 99 }
  assert.deepEqual(balanceReport(small), balanceReport(small))
  // 单局模拟也确定
  const one = { seed: 12345, playerHero: 'forge', aiHero: 'dusk', playerLevel: 'normal' as Level, aiLevel: 'hard' as Level, first: 0 as const }
  assert.deepEqual(simulateGame(one), simulateGame(one))
})
