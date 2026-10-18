// 成就单测:12 个定义合法、进度按战绩算、新解锁只报一次、写入档案后不再重复。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ACHIEVEMENTS, achievementCount, newlyUnlocked, unlockedAchievements } from '../src/achievements'
import { newProfile, recordResult, withAchievements, type Profile } from '../src/profile'
import type { Outcome } from '../src/profile'

const outcome = (over: Partial<Outcome> = {}): Outcome => ({
  won: true, draw: false, hero: 'forge', level: 'normal', reason: 'hp', myHp: 30, dealt: 12, played: 6,
  ...over,
})

const ids = (p: Profile): string[] => unlockedAchievements(p).map((a) => a.id)
/** 模拟真实流程:每局结束先把新解锁的成就写进档案,再继续记下一局 */
const settle = (p: Profile): Profile => withAchievements(p, newlyUnlocked(p).map((a) => a.id))

test('成就定义:12 个,id/名字/徽章唯一,进度目标都是正数', () => {
  assert.equal(ACHIEVEMENTS.length, 12)
  assert.equal(new Set(ACHIEVEMENTS.map((a) => a.id)).size, 12)
  assert.equal(new Set(ACHIEVEMENTS.map((a) => a.name)).size, 12)
  for (const a of ACHIEVEMENTS) {
    assert.ok(a.name.length > 0 && a.desc.length > 0 && a.badge.length === 1, `${a.id} 定义不完整`)
    const [now, goal] = a.progress(newProfile())
    assert.equal(now, 0, `${a.id} 新档进度应该从 0 开始`)
    assert.ok(goal > 0, `${a.id} 目标应该大于 0`)
  }
})

test('进度随战绩解锁:首胜/连胜/每套牌/斩杀/疲劳/伤害/出牌/满血/困难', () => {
  let p = newProfile()
  assert.deepEqual(newlyUnlocked(p), [])
  assert.deepEqual(ids(p), [])
  // 首胜(满血、hp 收尾)
  p = settle(recordResult(p, outcome()))
  assert.deepEqual(ids(p), ['first_win', 'win_forge', 'flawless'])
  // 连胜 3 / 5
  p = settle(recordResult(p, outcome()))
  p = settle(recordResult(p, outcome()))
  assert.deepEqual(ids(p), ['first_win', 'streak3', 'win_forge', 'flawless'])
  p = settle(recordResult(p, outcome()))
  p = settle(recordResult(p, outcome()))
  assert.deepEqual(ids(p), ['first_win', 'streak3', 'streak5', 'win_forge', 'flawless'])
  // 每套牌各赢一局 + 单局纪录 + 困难胜
  p = settle(recordResult(p, outcome({ hero: 'frost', level: 'hard', myHp: 24, dealt: 30, played: 15 })))
  assert.deepEqual(ids(p), [
    'first_win', 'streak3', 'streak5', 'win_forge', 'win_frost', 'damage30', 'cards15', 'flawless', 'hard_win',
  ])
  p = settle(recordResult(p, outcome({ hero: 'dusk', myHp: 20, dealt: 5, played: 3 })))
  assert.deepEqual(ids(p), [
    'first_win', 'streak3', 'streak5', 'win_forge', 'win_frost', 'win_dusk', 'damage30', 'cards15', 'flawless', 'hard_win',
  ])
  // 疲劳胜
  p = settle(recordResult(p, outcome({ hero: 'dusk', reason: 'fatigue', myHp: 16, dealt: 18 })))
  assert.ok(ids(p).includes('fatigue_win'))
  // 累计 10 次把对面英雄打到 0(斩杀)
  while (p.lethals < 10) p = settle(recordResult(p, outcome({ hero: 'forge', myHp: 21, dealt: 20, played: 8 })))
  assert.ok(ids(p).includes('lethal10'))
  assert.equal(ids(p).length, 12)
  assert.equal(achievementCount(p), 12)
})

test('新解锁只报一次:写进档案后 newlyUnlocked 为空;进度有上限', () => {
  let p = newProfile()
  p = recordResult(p, outcome())
  const first = newlyUnlocked(p).map((a) => a.id)
  assert.ok(first.includes('first_win'))
  p = withAchievements(p, first)
  assert.deepEqual(newlyUnlocked(p), [])
  assert.equal(achievementCount(p), first.length)
  // 单局超过目标值时进度封顶(不会显示出 45/30 这种)
  const big = recordResult(p, outcome({ dealt: 45, played: 20 }))
  const dmg = ACHIEVEMENTS.find((a) => a.id === 'damage30') as (typeof ACHIEVEMENTS)[number]
  assert.deepEqual(dmg.progress(big), [30, 30])
  const cards = ACHIEVEMENTS.find((a) => a.id === 'cards15') as (typeof ACHIEVEMENTS)[number]
  assert.deepEqual(cards.progress(big), [15, 15])
})

test('档案里只有真正达成的成就才算解锁(写坏的历史成就 id 不算数)', () => {
  const p = { ...newProfile(), achievements: ['first_win', 'not_a_real_achievement'] }
  assert.deepEqual(unlockedAchievements(p).map((a) => a.id), [])
  const q = { ...newProfile(), wins: 1, achievements: ['first_win'] }
  assert.deepEqual(unlockedAchievements(q).map((a) => a.id), ['first_win'])
})
