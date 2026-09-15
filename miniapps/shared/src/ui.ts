// 小游戏共用的界面零件:弹层、按钮、亮暗主题、宿主能力、存档的两头(云存储和本机缓存)。
// 用户看得到的字一律用 textContent 放进页面,不拼 HTML。
import WebApp from '../../../packages/miniapp-sdk/src/index'
import type { CloudLike, LocalLike } from './save'

export { WebApp }

export const $ = <T extends HTMLElement = HTMLElement>(id: string): T => document.getElementById(id) as T

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = ''): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag)
  if (text) e.textContent = text
  if (cls) e.className = cls
  return e
}

export function button(text: string, onClick: () => void, cls = ''): HTMLButtonElement {
  const b = el('button', text, cls)
  b.type = 'button'
  b.addEventListener('click', onClick)
  return b
}

export const reduced = (): boolean => matchMedia('(prefers-reduced-motion: reduce)').matches

/** 盖在整页上的弹层(结束、暂停、关于、选项)。一次只有一个 */
export class Overlay {
  private onDismiss: (() => void) | null = null

  constructor(private readonly root: HTMLElement, private readonly refocus: () => void) {
    root.addEventListener('click', (e) => { if (e.target === root && this.onDismiss) this.dismiss() })
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.open && this.onDismiss) {
        e.preventDefault()
        this.dismiss()
      }
    })
  }

  get open(): boolean {
    return !this.root.hidden
  }

  /** onDismiss 给了才能点空白处或按 Esc 关掉 */
  show(fill: (panel: HTMLElement) => void, opts: { cls?: string; onDismiss?: () => void } = {}): void {
    this.root.textContent = ''
    const p = el('div', '', `panel ${opts.cls || ''}`.trim())
    p.setAttribute('role', 'dialog')
    p.setAttribute('aria-modal', 'true')
    fill(p)
    const h = p.querySelector('h2')
    if (h) {
      h.id = 'panel-title'
      p.setAttribute('aria-labelledby', 'panel-title')
    }
    this.root.append(p)
    this.root.hidden = false
    this.onDismiss = opts.onDismiss || null
    const first = (p.querySelector('button.primary') || p.querySelector('button')) as HTMLElement | null
    first?.focus()
  }

  hide(): void {
    if (!this.open) return
    this.root.hidden = true
    this.root.textContent = ''
    this.onDismiss = null
    this.refocus()
  }

  private dismiss(): void {
    const fn = this.onDismiss
    this.hide()
    fn?.()
  }
}

/** 一排按钮 */
export function row(...buttons: HTMLElement[]): HTMLElement {
  const r = el('div', '', 'row')
  r.append(...buttons)
  return r
}

/** 「关于」里的一串要点 */
export function bullets(items: string[]): HTMLElement {
  const ul = el('ul')
  for (const t of items) ul.append(el('li', t))
  return ul
}

/** 确认框:宿主原生弹窗,不在宿主里退回浏览器自带的 */
export async function confirmBox(message: string): Promise<boolean> {
  try {
    return await WebApp.showConfirm(message)
  } catch (_) {
    return window.confirm(message)
  }
}

/**
 * 亮暗:宿主下发了主题就跟宿主(colorScheme),不在宿主里就跟系统。
 * 在 <html> 上切 .dark;画布游戏的颜色从 CSS 变量里读,变了回调一次让它重画。
 */
export function followTheme(onChange?: () => void): void {
  const mq = matchMedia('(prefers-color-scheme: dark)')
  const apply = () => {
    const host = Object.keys(WebApp.themeParams).length > 0
    const dark = host ? WebApp.colorScheme === 'dark' : mq.matches
    const root = document.documentElement
    root.classList.toggle('dark', dark)
    root.style.colorScheme = dark ? 'dark' : 'light'
    onChange?.()
  }
  apply()
  WebApp.onEvent('themeChanged', apply)
  if (mq.addEventListener) mq.addEventListener('change', apply)
  else mq.addListener(apply)
}

/** 读一个 CSS 变量的最终值(画布用) */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/**
 * 小游戏的宿主能力:全屏、锁方向(superz.json 里 orientation 写了 portrait,宿主打开时就锁;这两句给网页版用)。
 * 切到后台、页面要被收起时回调一次(暂停、马上存档)。
 */
export function hostGame(onHide: () => void): void {
  WebApp.requestFullscreen().catch(() => undefined)
  WebApp.lockOrientation().catch(() => undefined)
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') onHide() })
  window.addEventListener('pagehide', onHide)
  WebApp.onEvent('deactivated', onHide)
}

/** 本机缓存的键按 open_id 分开:同一台设备换了账号,接不上上一个人的 */
export function cacheKey(app: string): string {
  return `${app}:v1:${WebApp.initDataUnsafe.user?.open_id || 'anon'}`
}

/** 云存储(按应用和用户隔离) */
export const cloud: CloudLike = {
  getItems: (keys) => WebApp.CloudStorage.getItems(keys),
  setItem: (key, value) => WebApp.CloudStorage.setItem(key, value),
}

/** 本机缓存。有的 WebView 一碰 localStorage 就抛错,包一层 */
export const local: LocalLike = {
  getItem(key) {
    try { return window.localStorage.getItem(key) } catch (_) { return null }
  },
  setItem(key, value) {
    try { window.localStorage.setItem(key, value) } catch (_) { /* 满了或者不让用 */ }
  },
}
