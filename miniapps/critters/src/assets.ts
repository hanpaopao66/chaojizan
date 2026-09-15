// 图集的加载和取帧。units(动物和卡面)一打开就要;world(战场)和 fx(粒子)进对局前再加载。
// 受击闪白要的白色剪影、粒子的几种颜色,都是加载后在内存里一次性做好的,不另外下载。
import { FX, Sheet, UNITS, WORLD } from './art'

export type Canvasish = HTMLImageElement | HTMLCanvasElement

export interface Loaded {
  sheet: Sheet
  img: Canvasish
}

const cache = new Map<string, Promise<HTMLImageElement>>()

export function loadImage(src: string): Promise<HTMLImageElement> {
  let p = cache.get(src)
  if (!p) {
    p = new Promise((resolve, reject) => {
      const img = new Image()
      img.decoding = 'async'
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error(`图片没加载出来:${src}`))
      img.src = src
    })
    cache.set(src, p)
    p.catch(() => cache.delete(src))
  }
  return p
}

export const art = {
  units: null as Loaded | null,
  /** 动物的白色剪影(受击闪一下) */
  unitsWhite: null as HTMLCanvasElement | null,
  world: null as Loaded | null,
  fx: null as Loaded | null,
  /** 粒子的几种颜色:颜色 → 整张染好色的图集 */
  fxTint: new Map<string, HTMLCanvasElement>(),
}

function canvas(w: number, h: number): HTMLCanvasElement {
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  return c
}

/** 把整张图集染成一种颜色(保留透明度) */
function tinted(img: Canvasish, w: number, h: number, color: string): HTMLCanvasElement {
  const c = canvas(w, h)
  const g = c.getContext('2d') as CanvasRenderingContext2D
  g.drawImage(img, 0, 0)
  g.globalCompositeOperation = 'source-in'
  g.fillStyle = color
  g.fillRect(0, 0, w, h)
  return c
}

export async function loadUnits(): Promise<void> {
  if (art.units) return
  const img = await loadImage(UNITS.src)
  art.units = { sheet: UNITS, img }
  art.unitsWhite = tinted(img, UNITS.w, UNITS.h, '#ffffff')
}

/** 对局要用的:战场、粒子(染好几种常用色) */
export async function loadBattleArt(): Promise<void> {
  await loadUnits()
  if (!art.world) art.world = { sheet: WORLD, img: await loadImage(WORLD.src) }
  if (!art.fx) {
    const img = await loadImage(FX.src)
    art.fx = { sheet: FX, img }
    for (const c of Object.values(FX_COLORS)) art.fxTint.set(c, tinted(img, FX.w, FX.h, c))
  }
}

export const FX_COLORS = {
  white: '#ffffff', dust: '#e8dcc4', smoke: '#c9c4bc', dark: '#6b6258', orange: '#ffb04a', fire: '#ff7a2e',
  ice: '#bfeaff', cyan: '#5fd2ff', green: '#7fe08a', heal: '#b8ffb0', red: '#ff5a4a', gold: '#ffd54a',
  teal: '#3fd6c6', blue: '#6fb4ff', purple: '#c49bff', pink: '#ff9ec2',
} as const
export type FxColor = keyof typeof FX_COLORS

export function frame(l: Loaded | null, key: string): number[] | null {
  return l ? l.sheet.frames[key] || null : null
}

/**
 * 画一帧:(x, y) 是锚点在画布上的位置,w 是画出来的宽(高按比例)。
 * 返回画出来的高(没画成返回 0)
 */
export function draw(g: CanvasRenderingContext2D, l: Loaded | null, key: string, x: number, y: number, w: number,
  img?: Canvasish): number {
  const f = frame(l, key)
  if (!f || !l) return 0
  const h = (w * f[3]) / f[2]
  g.drawImage(img || l.img, f[0], f[1], f[2], f[3], x - w * f[4], y - h * f[5], w, h)
  return h
}

export function drawFx(g: CanvasRenderingContext2D, key: string, color: FxColor, x: number, y: number, size: number): void {
  const l = art.fx
  const f = frame(l, key)
  if (!f || !l) return
  const img = color === 'white' ? art.fxTint.get(FX_COLORS.white) || l.img : art.fxTint.get(FX_COLORS[color]) || l.img
  const k = size / Math.max(f[2], f[3])
  const w = f[2] * k
  const h = f[3] * k
  g.drawImage(img, f[0], f[1], f[2], f[3], x - w / 2, y - h / 2, w, h)
}

/** 原色粒子(爆炸那几张本来就是彩色的) */
export function drawFxRaw(g: CanvasRenderingContext2D, key: string, x: number, y: number, size: number): void {
  const l = art.fx
  const f = frame(l, key)
  if (!f || !l) return
  const k = size / Math.max(f[2], f[3])
  g.drawImage(l.img, f[0], f[1], f[2], f[3], x - (f[2] * k) / 2, y - (f[3] * k) / 2, f[2] * k, f[3] * k)
}

/**
 * DOM 里放一张卡面(动物头像、法术圆球……):一个 span,背景是 units 图集里的那一帧,
 * 等比缩到放得进 box×box。图集还没加载完也行,背景图会自己出来。
 */
export function artSpan(key: string, box: number, cls = 'art'): HTMLSpanElement {
  const s = document.createElement('span')
  s.className = cls
  setArt(s, key, box)
  return s
}

export function setArt(s: HTMLElement, key: string, box: number): void {
  const f = UNITS.frames[key]
  if (!f) return
  const k = Math.min(box / f[2], box / f[3])
  s.style.width = `${f[2] * k}px`
  s.style.height = `${f[3] * k}px`
  s.style.backgroundImage = `url(${UNITS.src})`
  s.style.backgroundSize = `${UNITS.w * k}px ${UNITS.h * k}px`
  s.style.backgroundPosition = `${-f[0] * k}px ${-f[1] * k}px`
}

/** 图标(白色剪影)当遮罩用,颜色跟着文字色走 */
export function icon(name: string, cls = ''): HTMLSpanElement {
  const s = document.createElement('span')
  s.className = `ic ${cls}`.trim()
  s.setAttribute('aria-hidden', 'true')
  // 金币画成一枚圆片(见 style.css 的 .coinic),不用图
  if (name === 'coin') {
    s.classList.add('coinic')
    return s
  }
  const url = `url(art/icon/${name}.webp)`
  s.style.webkitMaskImage = url
  s.style.maskImage = url
  return s
}
