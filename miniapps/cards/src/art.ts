// 程序化美术:卡面、图标、英雄头像全部是内联 SVG 的 path 数据,CSS 负责配色和光晕。
// 不加载任何图片、字体文件或网络资源;同一个图案在不同阵营下用 CSS 变量换颜色。
import { el } from '../../shared/src/ui'
import type { ArtKey } from './types'

const NS = 'http://www.w3.org/2000/svg'

/** 图案表:一个 key 一行 path 数据(多个子路径拼在一条 d 里,用 evenodd 挖洞) */
const GLYPHS: Record<ArtKey, string> = {
  flame: 'M12 2c1.2 4-3.5 5.4-3.5 10a3.5 3.5 0 0 0 7 0c0-1.7-.8-2.9-1.4-4.4 2.2 1.2 4.4 3.6 4.4 7.4a6.5 6.5 0 1 1-13 0C5.5 8.2 10.4 6.3 12 2z',
  ember: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 4a6 6 0 1 1 0 12 6 6 0 0 1 0-12z',
  hammer: 'M14.8 2.6l6.6 6.6-3 3-1.9-1.9-6.2 6.2 2.2 2.2-2.8 2.8-7.8-7.8 2.8-2.8 2.2 2.2 6.2-6.2-1.9-1.9z',
  giant: 'M4 21V9.5L12 3l8 6.5V21h-5v-6H9v6z',
  orb: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 3a7 7 0 1 1 0 14 7 7 0 0 1 0-14z',
  snow: 'M11 2h2v6.2l4.4-4.4 1.4 1.4-4.4 4.4H21v2h-6.6l4.4 4.4-1.4 1.4L13 13.4V21h-2v-7.6l-4.4 4.4-1.4-1.4L9.6 12H3v-2h6.6L5.2 5.6 6.6 4.2 11 8.6z',
  feather: 'M20 4C11 4 5 8 4 17c0 2 1 3 2 3 9-1 13-7 14-16zM8 15l6-6 1.4 1.4-6 6z',
  shield: 'M12 2l8 3v6c0 5-3.4 9-8 11-4.6-2-8-6-8-11V5z',
  ring: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 3.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13z',
  winter: 'M11 2h2v5.2l3.7-3.7 1.4 1.4L13.4 10H21v2h-7.6l4.7 4.7-1.4 1.4L13 13.4V21h-2v-7.6l-4.7 4.7-1.4-1.4L8.6 12H1v-2h7.6L3.9 5.1 5.3 3.7 11 9.4z',
  leaf: 'M20 4C11 4 5 8 4 17c0 2 1 3 2 3 9-1 13-7 14-16zM7 19c1-5 4-8 9-11-4 3-6 6-7 11z',
  dagger: 'M20 2l2 2-3 3 2 2-2 2-2-2-8 8-2 2-3-3 2-2 8-8-2-2 2-2 2 2z',
  lantern: 'M9 2h6v2H9zm-1 4h8l2 4v8l-2 4H8l-2-4v-8zm3 5v6h2v-6z',
  coin: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 3a7 7 0 1 1 0 14 7 7 0 0 1 0-14zm0 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
  crown: 'M3 7l4.5 4L12 4l4.5 7L21 7v11H3z',
  swirl: 'M12 2a10 10 0 1 1-9.9 11h3a7 7 0 1 0 6.9-8z',
  moon: 'M20 14.5A9 9 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z',
  spark: 'M12 2l2.2 7.8L22 12l-7.8 2.2L12 22l-2.2-7.8L2 12l7.8-2.2z',
  rock: 'M4 19l2-8 6-6 8 5-1 9z',
  wind: 'M3 6h13a3 3 0 1 0-3-3h2a1 1 0 1 1 1 1H3zm0 6h16a3 3 0 1 1-3 3h2a1 1 0 1 0 1-1H3zm0 6h8v2H3z',
  bird: 'M2 15c5 0 7-4 10-4s5 3 8 3c-2 4-6 6-11 6-4 0-7-2-7-5z',
  vial: 'M9 2h6v2h-1v3l2 3v10a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2V10l2-3V4H9zm2 11v6h2v-6z',
  wall: 'M3 5h18v4H3zm0 6h5v4H3zm7 0h5v4h-5zm7 0h4v4h-4zM3 17h18v4H3z',
  horn: 'M3 11c5-4 13-4 18 0-5 4-13 4-18 0zm2 2l-1 7 5-2 1-4z',
  twins: 'M8 4a5 5 0 1 0 0 10A5 5 0 0 0 8 4zm8 6a5 5 0 1 0 0 10 5 5 0 0 0 0-10z',
  cart: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 3a6 6 0 1 1 0 12 6 6 0 0 1 0-12zm-1 1v4H7v2h4v4h2v-4h4v-2h-4V7z',
  owl: 'M6 5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zm0 2a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zm12-2a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zm0 2a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z',
  star: 'M12 2l2.9 6.9 7.1.6-5.4 4.7 1.6 7-6.2-3.8-6.2 3.8 1.6-7L2 9.5l7.1-.6z',
  swap: 'M7 3l4 4H8v6H6V7H2zm10 18l-4-4h3V7h2v10h4z',
}

/** 一张卡 / 一个英雄的图案元素;颜色由外层的阵营 class 决定 */
export function artEl(key: ArtKey, cls = ''): HTMLElement {
  const span = el('span', '', `art ${cls}`.trim())
  span.setAttribute('aria-hidden', 'true')
  const svg = document.createElementNS(NS, 'svg')
  svg.setAttribute('viewBox', '0 0 24 24')
  svg.setAttribute('focusable', 'false')
  const path = document.createElementNS(NS, 'path')
  path.setAttribute('d', GLYPHS[key])
  path.setAttribute('fill', 'currentColor')
  path.setAttribute('fill-rule', 'evenodd')
  svg.append(path)
  span.append(svg)
  return span
}

/** 背景里飘的星火(纯 CSS 动画,装饰用) */
export function sparkField(count: number): HTMLElement {
  const box = el('div', '', 'sparks')
  box.setAttribute('aria-hidden', 'true')
  for (let i = 0; i < count; i++) {
    const s = el('i', '', 'sparkdot')
    s.style.setProperty('--x', `${(i * 37) % 100}%`)
    s.style.setProperty('--y', `${(i * 61) % 100}%`)
    s.style.setProperty('--d', `${2.4 + ((i * 7) % 10) / 4}s`)
    s.style.setProperty('--s', `${2 + ((i * 13) % 5)}px`)
    s.style.setProperty('--delay', `${-((i * 17) % 40) / 10}s`)
    box.append(s)
  }
  return box
}
