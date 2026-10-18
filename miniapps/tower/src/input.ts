// 战场输入:canvas 点击/触摸 → 建造位或塔;另外在每个建造位上面放一个透明的真按钮,
// 键盘和读屏用户可以直接按到它们(位置跟着 canvas 缩放走)。
import { TILE } from './data'
import { clientToWorld, worldToCss } from './render'
import type { Renderer } from './render'
import type { GameState, LevelDef, Tower } from './types'

export interface FieldCallbacks {
  /** 点了空的建造位 */
  onSlot: (slot: number) => void
  /** 点了已经有塔的建造位 */
  onTower: (tower: Tower) => void
  /** 点了空白处 */
  onEmpty: () => void
}

export class FieldInput {
  private buttons: HTMLButtonElement[] = []
  private level: LevelDef | null = null
  private state: GameState | null = null
  private hoverSlot = -1
  private readonly onPointer = (e: PointerEvent): void => {
    if (e.pointerType === 'mouse' && e.button !== 0) return
    e.preventDefault()
    this.pick(clientToWorld(this.renderer, this.canvas, e.clientX, e.clientY).x,
      clientToWorld(this.renderer, this.canvas, e.clientX, e.clientY).y)
  }
  private readonly activate = (slot: number, tower: Tower | null): void => {
    if (tower) this.cb.onTower(tower)
    else this.cb.onSlot(slot)
  }

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly sites: HTMLElement,
    private readonly renderer: Renderer,
    private readonly cb: FieldCallbacks,
  ) {
    canvas.addEventListener('pointerdown', this.onPointer)
    canvas.addEventListener('contextmenu', (e) => e.preventDefault())
    sites.addEventListener('pointerleave', () => { this.hoverSlot = -1 })
  }

  get hover(): number {
    return this.hoverSlot
  }

  /** 换关:重建覆盖在建造位上的按钮 */
  setLevel(level: LevelDef): void {
    this.level = level
    this.sites.textContent = ''
    this.buttons = []
    for (let i = 0; i < level.slots.length; i++) {
      const b = document.createElement('button')
      b.type = 'button'
      b.className = 'site'
      b.dataset.slot = String(i)
      b.addEventListener('click', () => this.press(i))
      b.addEventListener('pointerenter', () => { this.hoverSlot = i })
      b.addEventListener('pointerleave', () => { if (this.hoverSlot === i) this.hoverSlot = -1 })
      this.sites.append(b)
      this.buttons.push(b)
    }
    this.layout()
  }

  /** canvas 尺寸变了:把按钮摆到新的位置 */
  layout(): void {
    if (!this.level) return
    const canvasRect = this.canvas.getBoundingClientRect()
    const wrapRect = this.sites.getBoundingClientRect()
    const k = this.renderer.scaleOf()
    const size = Math.max(44, TILE * k * 1.6)
    for (let i = 0; i < this.buttons.length; i++) {
      const slot = this.level.slots[i]
      const p = worldToCss(this.renderer, { x: (slot.c + 0.5) * TILE, y: (slot.r + 0.5) * TILE })
      const b = this.buttons[i]
      b.style.left = `${canvasRect.left - wrapRect.left + p.x - size / 2}px`
      b.style.top = `${canvasRect.top - wrapRect.top + p.y - size / 2}px`
      b.style.width = `${size}px`
      b.style.height = `${size}px`
    }
  }

  /** 每帧(或状态变化时)更新按钮的无障碍标签 */
  sync(state: GameState, selectedTower: number): void {
    this.state = state
    if (!this.level) return
    for (let i = 0; i < this.buttons.length; i++) {
      const tower = state.towers.find((t) => t.slot === i)
      const b = this.buttons[i]
      if (tower) {
        b.setAttribute('aria-label', `建造位 ${i + 1}:${towerName(tower)} ${tower.level} 级,点开看升级和卖出`)
        b.dataset.tower = tower.kind
        b.dataset.level = String(tower.level)
        b.classList.add('built')
      } else {
        b.setAttribute('aria-label', `空建造位 ${i + 1},点一下放塔`)
        delete b.dataset.tower
        delete b.dataset.level
        b.classList.remove('built')
      }
      b.classList.toggle('selected', tower !== undefined && tower.id === selectedTower)
    }
  }

  private pick(worldX: number, worldY: number): void {
    if (!this.level || !this.state) return
    let best = -1
    let bestD = TILE * 0.95
    this.level.slots.forEach((slot, i) => {
      const dx = (slot.c + 0.5) * TILE - worldX
      const dy = (slot.r + 0.5) * TILE - worldY
      const d = Math.hypot(dx, dy)
      if (d < bestD) {
        bestD = d
        best = i
      }
    })
    if (best < 0) {
      this.cb.onEmpty()
      return
    }
    this.press(best)
  }

  private press(slot: number): void {
    const tower = this.state?.towers.find((t) => t.slot === slot) || null
    this.activate(slot, tower)
  }
}

function towerName(tower: Tower): string {
  const names: Record<string, string> = {
    pea: '豆荚炮', frost: '冰霜铃', pepper: '火焰椒', vine: '闪电藤',
    mushroom: '毒蘑菇', bow: '瓜藤弓', marigold: '金盏花',
  }
  return names[tower.kind] || tower.kind
}
