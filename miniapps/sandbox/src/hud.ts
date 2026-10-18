// HUD:准星旁边的方块名、挖掘进度、快捷栏、物品名、时钟、坐标、改动容量、成就提示、播报。
// 把这一块从主循环拆出来,主循环只负责「状态变了,刷一下」。
import { HOTBAR, blockName } from './blocks'
import { LIMITS, type AchievementDef } from './data'
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
  /** 这个世界改了多少格 */
  edits: number
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
  private readonly editsEl = $('hud-edits')
  private readonly editsNEl = $('hud-edits-n')
  private readonly itemNameEl = $('item-name')
  private readonly achToastEl = $('ach-toast')
  private readonly achIconEl = $('ach-icon')
  private readonly achTextEl = $('ach-text')
  private slotButtons: HTMLButtonElement[] = []
  private slotCounts: HTMLElement[] = []
  private lastAnnounce = 0
  private toastTimer = 0
  private achTimer = 0
  private itemTimer = 0

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

  /** 每 0.1–0.2 秒刷一次:时钟、坐标、准星指向、快捷栏数量、改动容量 */
  refresh(s: HudState): void {
    this.clockEl.textContent = clockText(s.time)
    this.sunEl.textContent = phaseIcon(s.time)
    this.posEl.textContent = `${Math.floor(s.x)}, ${Math.floor(s.y)}, ${Math.floor(s.z)}`
    this.targetEl.textContent = s.target ? blockName(s.target.block) : ''
    this.targetEl.classList.toggle('hidden', !s.target)
    this.counts(s.inv)
    this.selection(s.hot)
    this.edits(s.edits)
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

  /** 改动容量:超过提醒比例才显示,满了变红 */
  edits(count: number): void {
    const ratio = count / LIMITS.MAX_EDITS
    const show = ratio >= LIMITS.FULL_WARN_RATIO
    this.editsEl.hidden = !show
    if (!show) return
    this.editsNEl.textContent = String(count)
    this.editsEl.classList.toggle('full', ratio >= 1)
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

  /** 切方块时在热栏上方弹一下名字 */
  itemName(name: string): void {
    this.itemNameEl.textContent = name
    this.itemNameEl.hidden = false
    this.itemNameEl.classList.remove('show')
    void this.itemNameEl.offsetWidth
    this.itemNameEl.classList.add('show')
    window.clearTimeout(this.itemTimer)
    this.itemTimer = window.setTimeout(() => { this.itemNameEl.hidden = true }, 1400)
  }

  /** 成就解锁:中间偏上弹一个小卡片 */
  achievement(def: AchievementDef): void {
    this.achIconEl.textContent = def.icon
    this.achTextEl.textContent = `成就 · ${def.name}`
    this.achToastEl.hidden = false
    this.achToastEl.classList.remove('show')
    void this.achToastEl.offsetWidth
    this.achToastEl.classList.add('show')
    window.clearTimeout(this.achTimer)
    this.achTimer = window.setTimeout(() => { this.achToastEl.hidden = true }, 2800)
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
