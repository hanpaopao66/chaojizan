// 棋盘配色,亮暗两套。暗色下棋盘用中间调的木色,黑子白子都看得清。
// 每种棋子「填色或描边」至少有一样和棋盘对比度 ≥ 3:1;线、连五的圈、键盘光标和棋盘 ≥ 3:1;
// 最后一手的红点和两种棋子 ≥ 3:1(test/palette.test.ts 逐项算)。
export interface Palette {
  board: string
  line: string
  black: string
  blackEdge: string
  white: string
  whiteEdge: string
  /** 最后一手的小点 */
  mark: string
  /** 连成五子的圈、键盘光标 */
  win: string
}

export const LIGHT: Palette = {
  board: '#E3C386', line: '#6B4F2E', black: '#1B1A17', blackEdge: '#1B1A17', white: '#F7F4EC', whiteEdge: '#6B4F2E',
  mark: '#C15F3C', win: '#A33A1E',
}

export const DARK: Palette = {
  board: '#8A6A40', line: '#2A2012', black: '#141413', blackEdge: '#141413', white: '#F2F0E8', whiteEdge: '#2A2012',
  mark: '#C15F3C', win: '#FFE3D6',
}
