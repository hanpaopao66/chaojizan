// 棋盘配色,亮暗两套。蛇、食物和两种底色的对比度都 ≥ 3:1(test/engine.test.ts 逐项算)。
export interface Palette {
  boardA: string
  boardB: string
  snake: string
  head: string
  eye: string
  food: string
  crash: string
}

export const LIGHT: Palette = {
  boardA: '#FBFAF6', boardB: '#F1EEE6', snake: '#C15F3C', head: '#9A4428', eye: '#FFFFFF',
  food: '#3F6B41', crash: '#B3261E',
}

export const DARK: Palette = {
  boardA: '#24231F', boardB: '#2B2A25', snake: '#E08A6B', head: '#F2A98E', eye: '#1B1A17',
  food: '#8DC08F', crash: '#F2B8B5',
}
