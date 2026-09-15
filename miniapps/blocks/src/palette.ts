// 七种方块的颜色,亮暗两套,取自超级赞的产品色板(黏土、墨、苔绿、赭、石板蓝、梅、青)。
// 每种方块和棋盘底色的对比度 ≥ 3:1(test/palette.test.ts 逐个算)。顺序对应 engine.ts 的 KINDS。
export interface Palette {
  board: string
  grid: string
  pieces: string[]
  flash: string
}

export const LIGHT: Palette = {
  board: '#FBFAF6',
  grid: '#EEEBE3',
  pieces: ['#C15F3C', '#5B5750', '#4E7A52', '#A0701A', '#3E6A94', '#8A4F7D', '#2F7F7A'],
  flash: '#FFFFFF',
}

export const DARK: Palette = {
  board: '#24231F',
  grid: '#2E2D28',
  pieces: ['#E08A6B', '#BDB8AE', '#8DC08F', '#D9B25E', '#86AEDB', '#C99BC0', '#6FC2BA'],
  flash: '#F2F0E8',
}
