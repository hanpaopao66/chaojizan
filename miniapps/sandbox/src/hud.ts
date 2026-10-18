// HUD:准星旁边的方块名、挖掘进度、快捷栏、时钟、坐标、提示和播报。
// 把这一块从 main.ts 拆出来,主循环只负责「状态变了,刷一下」。
import { HOTBAR, blockName } from './blocks'
import { blockIconUrl } from './icons'
import type { RayHit } from './raycast'
import { clockText, phaseIcon } from './time'
import { $, el } from '../../shared/src/ui'

export interface HudState {
  /** 世界时间 0..1 */
  time: number
  x: number
  y: number
  z: number
  target: RayHit | null
  inv: number[]
  /** 当前选中的快捷栏下标 */
  hot: number
}

export class Hud {
  private readonly clockEl = $('hud-clock')
  private readonly sunEl = $('hud-sun')
  private readonly posEl = $('hud-pos')
  private readonly targetEl = $('target-name')
  private readonly mineEl = $('mine')
  private readonly mineFillEl = $('mine-fill')
  private readonly hotbarEl = $('hotbar')
  private readonly liveEl = $('live')
  private readonly toastEl = $('toast')
  private readonly soundBtn = $('btn-sound')
  private slotButtons: HTMLButtonElement[] = []
  private slotCounts: HTMLElement[] = []
  private lastAnnounce = 0
  private toastTimer = 0

  constructor(private readonly onSelect: (index: number) => void) {}

  /** 进入世界时建一次:九格快捷栏(图标由程序化纹理生成) */
  buildHotbar(): void {
    this.hotbarEl.textContent = ''
    this.slotButtons = []
    this.slotCounts = []
    for (let i = 0; i < HOTBAR.length; i++) {
      const b = document.createElement('button')
      b.type = 'button'
      b.className = 'slot'
      const img = document.createElement('img')
      img.src = blockIconUrl(HOTBAR[i])
      img.alt = ''
      img.draggable = false
      const key = el('span', String(i + 1), 'slot-key')
      const count = el('span', '', 'slot-count')
      b.append(img, key, count)
      b.addEventListener('click', () => this.onSelect(i))
      this.hotbarEl.append(b)
      this.slotButtons.push(b)
      this.slotCounts.push(count)
    }
  }

  /** 每 0.1–0.2 秒刷一次:时钟、坐标、准星指向、快捷栏数量 */
  refresh(s: HudState): void {
    this.clockEl.textContent = clockText(s.time)
    this.sunEl.textContent = phaseIcon(s.time)
    this.posEl.textContent = `${Math.floor(s.x)}, ${Math.floor(s.y)}, ${Math.floor(s.z)}`
    this.targetEl.textContent = s.target ? blockName(s.target.block) : ''
    this.targetEl.classList.toggle('hidden', !s.target)
    this.counts(s.inv)
    this.selection(s.hot)
  }

  counts(inv: number[]): void {
    for (let i = 0; i < this.slotButtons.length; i++) {
      const n = inv[i] ?? 0
      this.slotCounts[i].textContent = String(n)
      this.slotButtons[i].setAttribute('aria-label', `第 ${i + 1} 格 ${blockName(HOTBAR[i])},还有 ${n} 个`)
      this.slotButtons[i].classList.toggle('empty', n <= 0)
    }
  }

  selection(hot: number): void {
    for (let i = 0; i < this.slotButtons.length; i++) {
      this.slotButtons[i].setAttribute('aria-pressed', String(i === hot))
    }
  }

  /** 挖掘进度条:0 隐藏,>0 按比例填充 */
  mine(progress: number): void {
    if (progress <= 0.004) {
      this.mineEl.hidden = true
      return
    }
    this.mineEl.hidden = false
    this.mineFillEl.style.transform = `scaleX(${Math.min(1, progress).toFixed(3)})`
    this.mineEl.setAttribute('aria-valuenow', String(Math.round(progress * 100)))
  }

  /** 声音按钮:静音时显示「静」 */
  sound(muted: boolean): void {
    this.soundBtn.textContent = muted ? '静' : '声'
    this.soundBtn.setAttribute('aria-label', muted ? '声音已关,点击打开声音' : '声音已开,点击静音')
    const menuBtn = document.getElementById('menu-sound')
    if (menuBtn) menuBtn.textContent = muted ? '声音:关' : '声音:开'
  }

  /** 关键状态播报(aria-live);太频繁的更新跳过,免得读屏一直响 */
  announce(text: string): void {
    const now = performance.now()
    if (now - this.lastAnnounce < 250) return
    this.lastAnnounce = now
    this.liveEl.textContent = text
  }

  toast(text: string): void {
    this.toastEl.textContent = text
    this.toastEl.hidden = false
    this.toastEl.classList.remove('show')
    void this.toastEl.offsetWidth
    this.toastEl.classList.add('show')
    window.clearTimeout(this.toastTimer)
    this.toastTimer = window.setTimeout(() => { this.toastEl.hidden = true }, 2800)
  }
}
