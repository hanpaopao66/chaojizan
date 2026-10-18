// 成就:纯函数判定 —— 一场比赛结束后,把「这一场满足哪些成就」算出来。
// 解锁状态存在 Profile.achievements 里(云端同步、两台设备取并集),这里不碰存档。

import { MatchState } from './match'

export interface AchievementDef {
  id: string
  name: string
  /** 一句话说明怎么拿 */
  desc: string
  /** 一个汉字图标(程序化界面里当徽章用) */
  icon: string
}

export const ACHIEVEMENTS: readonly AchievementDef[] = [
  { id: 'first-win', name: '第一滴血', desc: '赢下第一场比赛', icon: '旗' },
  { id: 'flawless', name: '零阵亡', desc: '一场比赛没被击倒就赢下', icon: '盾' },
  { id: 'plant-hold', name: '安放并守住', desc: '安放炸弹并守到它爆炸', icon: '雷' },
  { id: 'pistol-five', name: '手枪专家', desc: '单场用手枪击杀 5 名守卫', icon: '铳' },
  { id: 'sweep', name: '横扫', desc: '2:0 赢下一场比赛', icon: '双' },
  { id: 'hard-win', name: '硬核行动', desc: '在困难难度赢下一场比赛', icon: '难' },
]

export function achievementById(id: string): AchievementDef | undefined {
  return ACHIEVEMENTS.find((a) => a.id === id)
}

/** 这场比赛达成了哪些成就(可能一次达成好几个);训练模式不参与 */
export function evaluateAchievements(match: MatchState): string[] {
  if (match.training || !match.over) return []
  const won = match.over === 'win'
  const out: string[] = []
  if (won) out.push('first-win')
  if (won && match.stats.deaths === 0) out.push('flawless')
  if (match.stats.explodedWins > 0) out.push('plant-hold')
  if (match.stats.pistolKills >= 5) out.push('pistol-five')
  if (won && match.scoreGuard === 0) out.push('sweep')
  if (won && match.difficulty === 'hard') out.push('hard-win')
  return out
}

/** 新解锁的成就 id(已经在 Profile 里的不算) */
export function newlyUnlocked(profileIds: readonly string[], satisfied: readonly string[]): string[] {
  return satisfied.filter((id) => profileIds.indexOf(id) < 0)
}
