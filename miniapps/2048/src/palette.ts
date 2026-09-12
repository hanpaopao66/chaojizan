// 方块色阶:骨白 → 黏土 → 墨(品牌色板)。每一档的数字和底色对比度 ≥ 4.5:1(test/palette.test.ts 逐档算)。
export const TILE_COLORS: Record<number, { bg: string; fg: string }> = {
  2: { bg: '#EFE9DD', fg: '#141413' },
  4: { bg: '#E8DCC6', fg: '#141413' },
  8: { bg: '#EBC7AE', fg: '#141413' },
  16: { bg: '#E2A887', fg: '#141413' },
  32: { bg: '#D98A67', fg: '#141413' },
  64: { bg: '#A84E30', fg: '#FFFFFF' },
  128: { bg: '#8C5B41', fg: '#FFFFFF' },
  256: { bg: '#6B4A36', fg: '#FFFFFF' },
  512: { bg: '#4E6B4F', fg: '#FFFFFF' },
  1024: { bg: '#2C5F87', fg: '#FFFFFF' },
  2048: { bg: '#141413', fg: '#F0EEE6' },
}
export const TILE_BEYOND = { bg: '#141413', fg: '#E08A6B' }

export function tileColor(v: number): { bg: string; fg: string } {
  return TILE_COLORS[v] || TILE_BEYOND
}

function lum(hex: string): number {
  const n = parseInt(hex.slice(1), 16)
  const ch = [n >> 16, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  })
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
}

/** WCAG 对比度 */
export function contrast(a: string, b: string): number {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}
