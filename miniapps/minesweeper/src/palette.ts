// 棋盘配色,亮暗两套。数字和翻开的格子底色对比度 ≥ 4.5:1,旗、雷和底色 ≥ 3:1(test/palette.test.ts 逐项算)。
// 没翻开和翻开的格子靠「凸起」区分(底边一道深色),不只靠颜色。main.ts 把它们写成 CSS 变量。
export interface Palette {
  grid: string
  hidden: string
  edge: string
  open: string
  /** 1–8 的颜色 */
  numbers: string[]
  flag: string
  mine: string
  boom: string
}

export const LIGHT: Palette = {
  grid: '#CFC8B8',
  hidden: '#E2DCCF',
  edge: '#B9B1A0',
  open: '#F7F5EF',
  numbers: ['#2C5F87', '#3F6B41', '#B3261E', '#3A3F8F', '#8C3A1E', '#1F6F6A', '#141413', '#5B5750'],
  flag: '#A33A1E',
  mine: '#141413',
  boom: '#F2B8B5',
}

export const DARK: Palette = {
  grid: '#1A1916',
  hidden: '#3D3B34',
  edge: '#2A2823',
  open: '#262520',
  numbers: ['#86AEDB', '#8DC08F', '#F2A3A0', '#B3B8F0', '#E8A07F', '#6FC2BA', '#F2F0E8', '#BDB8AE'],
  flag: '#F2A98E',
  mine: '#F2F0E8',
  boom: '#8C2F24',
}
