// 成就系统:12 个跨局目标。定义(名称 / 说明 / 阈值)是数据,判定是纯函数,
// 进度全部从战绩档案里算 —— 不额外存「进度」,换设备合并档案后进度自然还是对的。
import type { Profile } from './profile'

export interface Achievement {
  id: string
  name: string
  desc: string
  /** 首页/结算页上的单字徽章(不依赖外部图片) */
  badge: string
  /** 当前进度:[已有, 目标];目标 1 的成就达到 1 就解锁 */
  progress(p: Profile): [number, number]
}

const heroWins = (id: string) => (p: Profile): [number, number] => [p.winsByHero[id] || 0, 1]

export const ACHIEVEMENTS: readonly Achievement[] = [
  {
    id: 'first_win', name: '初战告捷', badge: '胜',
    desc: '赢下第一局对战。', progress: (p) => [Math.min(p.wins, 1), 1],
  },
  {
    id: 'streak3', name: '三连星火', badge: '连',
    desc: '拿到 3 连胜。', progress: (p) => [Math.min(p.bestStreak, 3), 3],
  },
  {
    id: 'streak5', name: '五连燎原', badge: '燎',
    desc: '拿到 5 连胜。', progress: (p) => [Math.min(p.bestStreak, 5), 5],
  },
  {
    id: 'win_forge', name: '炉火纯青', badge: '熔',
    desc: '用熔火工坊赢一局。', progress: heroWins('forge'),
  },
  {
    id: 'win_frost', name: '霜刃初试', badge: '霜',
    desc: '用霜林哨站赢一局。', progress: heroWins('frost'),
  },
  {
    id: 'win_dusk', name: '暮影破晓', badge: '影',
    desc: '用暮影集市赢一局。', progress: heroWins('dusk'),
  },
  {
    id: 'lethal10', name: '十步斩将', badge: '斩',
    desc: '累计 10 次把对面英雄打到 0。', progress: (p) => [Math.min(p.lethals, 10), 10],
  },
  {
    id: 'fatigue_win', name: '灯枯油尽', badge: '疲',
    desc: '让对面的牌库先抽空,靠疲劳伤害赢一局。', progress: (p) => [Math.min(p.fatigueWins, 1), 1],
  },
  {
    id: 'damage30', name: '一局三十伤', badge: '伤',
    desc: '单局对敌方造成 30 点伤害。', progress: (p) => [Math.min(p.maxDealt, 30), 30],
  },
  {
    id: 'cards15', name: '手快有', badge: '牌',
    desc: '单局打出 15 张牌。', progress: (p) => [Math.min(p.maxPlayed, 15), 15],
  },
  {
    id: 'flawless', name: '全身而退', badge: '全',
    desc: '满血(30 点)赢下一局。', progress: (p) => [Math.min(p.flawlessWins, 1), 1],
  },
  {
    id: 'hard_win', name: '硬碰硬', badge: '难',
    desc: '在困难难度赢一局。', progress: (p) => [Math.min(p.hardWins, 1), 1],
  },
]

const byId = new Map(ACHIEVEMENTS.map((a) => [a.id, a]))

export function achievement(id: string): Achievement | null {
  return byId.get(id) || null
}

/** 进度到没到 */
function done(a: Achievement, p: Profile): boolean {
  const [now, goal] = a.progress(p)
  return now >= goal
}

/** 档案里已经解锁的成就(按定义顺序) */
export function unlockedAchievements(p: Profile): Achievement[] {
  const have = new Set(p.achievements)
  return ACHIEVEMENTS.filter((a) => have.has(a.id) && done(a, p))
}

/** 这次结算新解锁的成就(档案里还没有、且已经达成的) */
export function newlyUnlocked(p: Profile): Achievement[] {
  const have = new Set(p.achievements)
  return ACHIEVEMENTS.filter((a) => !have.has(a.id) && done(a, p))
}

/** 已解锁数量(首页显示「成就 3/12」) */
export function achievementCount(p: Profile): number {
  return unlockedAchievements(p).length
}
