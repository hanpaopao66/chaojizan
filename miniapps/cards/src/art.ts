// 程序化美术:40 个内联 SVG 徽记(36 张卡 + 1 个召唤物 + 3 位英雄),每张卡一个独立图案,
// 加上 CSS 的阵营配色 / 稀有度边框 / 光晕。不加载任何图片、字体文件或网络资源。
//
// 图案约定:24×24 视框,一条 path 里可以有多个子路径(用 evenodd 挖洞);颜色一律 currentColor,
// 由外层 .cls-forge / .cls-frost / .cls-dusk / .cls-neutral 决定。
import { el } from '../../shared/src/ui'
import type { ArtKey } from './types'

const NS = 'http://www.w3.org/2000/svg'

const GLYPHS: Record<ArtKey, string> = {
  // ===== 中立 15 张 =====
  firefly: 'M12 2l1.7 6.1L20 9.8l-5 3.9 1.4 6.3-4.4-3.5-4.4 3.5L9 13.7 4 9.8l6.3-1.7zM11 11h2v2h-2z',
  peddler: 'M3 8h12l-2.6-2.6L14 3.8 20 9l-6 5.2-1.6-1.6L15 10H3zM21 15H9l2.6 2.6L10 19.2 4 14l6-5.2 1.6 1.6L9 13h12z',
  pebble: 'M3 20l2.4-8.2L11 6l6.4 1.2L21 14l-3 6zM8 12l3 2-1 4',
  scout: 'M2 7h13a3 3 0 1 0-3-3h2a1 1 0 1 1 1 1H2zM2 12h17l-3 3h3l3-4-3-4h-3l3 3H2zM2 17h9v2H2z',
  starling: 'M2 16c5 0 7-4 10-4s5 3 8 3c-2 4-6 6-11 6-4 0-7-2-7-5zM17 2l1 2.4 2.4 1L18 6.8 17 9.4l-1-2.6-2.4-1.4L16 4.4z',
  apothecary: 'M9 2h6v2h-1v3l2 3v10a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2V10l2-3V4H9zM11 13h2v2h2v2h-2v2h-2v-2H9v-2h2z',
  nightwatch: 'M3 5h18v4H3zM3 11h5v4H3zM10 11h5v4h-5zM17 11h4v4h-4zM3 17h18v4H3zM10 2h4v2h-4z',
  herald: 'M2 11c5-4 13-4 18 0-5 4-13 4-18 0zM4 13l-1 7 5-2 1-4zM18 2l1.2 2.6L22 5.8l-2.8 1.2L18 10l-1.2-3L14 5.8l2.8-1.2z',
  twinlamp: 'M4 5h5v2H4zM3 8h7l1.5 3v7L10 20H3l-1.5-2v-7zM15 2h5v2h-5zM14 5h7l1.5 3v7L21 17h-7l-1.5-2V8z',
  shellguard: 'M12 2l8 3v6c0 5-3.4 9-8 11-4.6-2-8-6-8-11V5zM12 7l-1.6 3.6L7 12l3.4 1.4L12 17l1.6-3.6L17 12l-3.4-1.4z',
  hammer: 'M14.8 2.6l6.6 6.6-3 3-1.9-1.9-6.2 6.2 2.2 2.2-2.8 2.8-7.8-7.8 2.8-2.8 2.2 2.2 6.2-6.2-1.9-1.9z',
  owl: 'M6 4a5 5 0 1 0 0 10A5 5 0 0 0 6 4zm0 2.2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6zM18 4a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 2.2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6zM11 17h2l-1 3z',
  wagon: 'M2 6h12v7H2zM14 13h4l2.5 4H2v-2h12zM8 17a2.2 2.2 0 1 0 0 4.4A2.2 2.2 0 0 0 8 17zm10 0a2.2 2.2 0 1 0 0 4.4 2.2 2.2 0 0 0 0-4.4z',
  lamplighter: 'M8 2h7v4h-1l1.5 2.5V19L13 21H10L7.5 19V8.5L9 6H8zM15 3h2v6l3 1-1 2.5-3-1z',
  colossus: 'M4 22V10l8-8 8 8v12h-4v-6H8v6zM9 9h2v2H9zm4 0h2v2h-2z',
  // ===== 熔火工坊 7 张 =====
  emberInitiate: 'M11 2c1.4 4-3.4 5.6-3.4 10a4.4 4.4 0 0 0 8.8 0c0-1.8-.8-3.2-1.6-4.8 2.4 1.4 4.6 4 4.6 7.6a6.4 6.4 0 1 1-12.8 0C6.6 8.4 9 6.4 11 2zM9 15a2.6 2.6 0 0 0 4.4 1.9A3.6 3.6 0 0 1 9 15z',
  ashPuppet: 'M8 2h8v3H8zM6 7h12v7l-3 3H9l-3-3zM9 19h2v3H9zM13 19h2v3h-2zM10 10h4v2h-4z',
  flameThrower: 'M10 2c1.2 3.4-3 4.8-3 8.6A3.7 3.7 0 0 0 14.4 10c0-1.5-.6-2.7-1.3-4 2 1.2 4 3.4 4 6.4A6.1 6.1 0 1 1 5.2 12C5.2 7.6 8.4 5.4 10 2zM17 16h5v3h-5z',
  heartGuard: 'M12 2l8 3v6c0 5-3.4 9-8 11-4.6-2-8-6-8-11V5zM12 8l-2.2 2.3c-1.2 1.3-.4 3.7 2.2 4.7 2.6-1 3.4-3.4 2.2-4.7z',
  flint: 'M4 19l3-9 5-2 3 4-2 3 4 1-2 5H7zM16 3l1 2.2 2.2 1L17 7.2 16 9.5l-1-2.3-2.2-1L15 5.2z',
  emberRain: 'M5 7h11a2.5 2.5 0 1 0-2.5-4H16a1 1 0 1 1 1 1H3v2h14a2 2 0 1 1-2 2H5zM7 12c.8 2-1.8 2.8-1.8 5A2.2 2.2 0 0 0 9.6 19c0-.9-.5-1.7-.9-2.5 1.3.7 2.5 2 2.5 4M15 12c.8 2-1.8 2.8-1.8 5a2.2 2.2 0 0 0 4.4 2c0-.9-.5-1.7-.9-2.5 1.3.7 2.5 2 2.5 4',
  magmaGiant: 'M5 22V12l7-7 7 7v10h-4v-5H9v5zM11 8h2v1.5h-2zM8 6l1.5-1.5 1 1L9 7zM14 5l1.5-1.5 1 1L15 6z',
  // ===== 霜林哨站 7 张 =====
  frostSentry: 'M11 2h2v6l4.2-4.2 1.4 1.4L14.4 9H21v2h-6.6l4.2 4.2-1.4 1.4L13 12.4V21h-2v-8.6l-4.2 4.2-1.4-1.4L9.6 11H3V9h6.6L5.4 4.8 6.8 3.4 11 7.6z',
  snowHealer: 'M20 3C11 3 5 7.4 4 17c0 2 1 3 2 3 9-1 13-7 14-17zM7 19c1-5 4-8 9-11-4 3-6.4 6.2-7.4 11zM3 3h2v5H3zM1.5 5.5h5v2h-5z',
  iceShell: 'M12 2l8 3v6c0 5-3.4 9-8 11-4.6-2-8-6-8-11V5zM11 7h2v3l2.6-2.6 1.4 1.4L14.4 11H17v2h-2.6l2.6 2.6-1.4 1.4L13 14.4V18h-2v-3.6l-2.6 2.6-1.4-1.4L9.6 13H7v-2h2.6L7.2 8.4 8.6 7 11 9.6z',
  frostRing: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 3.6a6.4 6.4 0 1 1 0 12.8 6.4 6.4 0 0 1 0-12.8zM11 7h2v3h2v2h-2v3h-2v-3H9v-2h2z',
  winterBless: 'M11 2h2v5l3-3 1.4 1.4L13 10v1h5v2h-5v2l4.4 4.4L16 20.8 13 17.8V22h-2v-4.2l-3 3-1.4-1.4L11 15v-2H6v-2h5v-1L6.6 5.4 8 4l3 3z',
  snowSpring: 'M9 2h6v2h-1v3l2 3v10a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2V10l2-3V4H9zM11 12h2v2.5l2-1.2 1 1.7-2 1.2 2 1.2-1 1.7-2-1.2V20h-2v-3.1l-2 1.2-1-1.7 2-1.2-2-1.2 1-1.7 2 1.2z',
  everWatch: 'M5 22V10l7-8 7 8v12h-4v-5H9v5zM9 10h2v2H9zm4 0h2v2h-2z',
  // ===== 暮影集市 7 张 =====
  alleyThief: 'M20 2l2 2-3 3 2 2-2 2-2-2-8 8-2 2-3-3 2-2 8-8-2-2 2-2 2 2zM3 18l1 1-1 2 3-1z',
  lampBearer: 'M9 2h6v2H9zM8 5h8l2 4v9l-2 3H8l-2-3V9zM10 10v5h4v-5zM18 8l3 2v4l-3 2z',
  merchant: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 3a7 7 0 1 1 0 14 7 7 0 0 1 0-14zM8 15h8l-1.5-5-2.5 3-2.5-3z',
  shadowDancer: 'M12 2a10 10 0 1 1-9.9 11h3a7 7 0 1 0 6.9-8zM15 5l2 2-5 5 3 3-2 2-5-5z',
  ambush: 'M3 21l2-6 11-11 4 4-11 11zM16 2l6 6-2 2-6-6zM5 15l2 2-3 1z',
  stardust: 'M2 5l2 2-2 2 3 1 1 3 2-2 3 1-1-3 2-2-3-1-1-3-2 2zM15 2l1 2.4 2.4 1L16 6.8 15 9.4l-1-2.6-2.4-1.4L14 4.4zM15 14l1.5 3 3 1.5-3 1.5L15 23l-1.5-3-3-1.5 3-1.5z',
  shadowLord: 'M3 7l4.5 4L12 4l4.5 7L21 7v11H3zM8 15h8v3H8zM10 2h4v2h-4z',
  wisp: 'M12 3c.8 2.6-2.2 3.6-2.2 6.4A2.7 2.7 0 0 0 15.2 11c0-1.2-.5-2.1-1-3.2 1.6 1 3 2.6 3 5a5.2 5.2 0 1 1-10.4 0c0-4.4 3.6-5.6 5.2-9.8z',
  // ===== 三位英雄头像 =====
  heroForge: 'M4 22V11l8-8 8 8v11h-4v-6H8v6zM11 9h2v2h-2zM15 9h2v2h-2zM2 2h2v7H2zM3 2h7v2H3z',
  heroFrost: 'M11 2h2v6.2l4.4-4.4 1.4 1.4-4.4 4.4H21v2h-6.6l4.4 4.4-1.4 1.4L13 13.4V21h-2v-7.6l-4.4 4.4-1.4-1.4L9.6 12H3v-2h6.6L5.2 5.6l1.4-1.4L11 8.6zM9 4h6v2H9zM9 18h6v2H9z',
  heroDusk: 'M22 15A10 10 0 0 1 9 2a10 10 0 1 0 13 13zM3 3h2v8H3zM2.5 3.5h3v2h-3zM15 2l1 2.2 2.2 1L17 6.2 16 8.5l-1-2.3-2.2-1L15 4.2z',
}

/** 一张卡 / 一个英雄的图案元素;颜色由外层的阵营 class / 稀有度 class 决定 */
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
