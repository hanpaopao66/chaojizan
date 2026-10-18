// 输入:桌面(键盘 + 鼠标锁定/拖拽)和触屏(左摇杆 + 右侧拖拽视角 + 三个按钮)。
// 这里只收「玩家想干什么」,不碰物理和画面:主循环每帧来读。
import { hotbarIndexFromKey } from './blocks'

export interface InputHooks {
  /** 数字键 1–9 / 点热栏:切到第几格(0 开始) */
  onHotbar(index: number): void
  /** 滚轮:切上一格 / 下一格(dir = ±1) */
  onCycle(dir: number): void
  /** Esc / 浏览器把鼠标锁定取消了:暂停 */
  onPause(): void
}

export interface TouchButtons {
  jump: HTMLElement
  mine: HTMLElement
  place: HTMLElement
}

const MOUSE_SENS = 0.0024
const TOUCH_SENS = 0.0055
const MOVE_KEYS = ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'Space', 'ShiftLeft', 'ShiftRight']
const LOOK_KEYS = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']
const STICK_DEAD = 0.16

const clamp1 = (v: number): number => (v < -1 ? -1 : v > 1 ? 1 : v)

export class Input {
  /** 游戏里(没暂停、没弹层)才收输入 */
  enabled = false
  /** 用过触屏:界面显示摇杆和按钮 */
  touched = false
  private keys = new Set<string>()
  private joyX = 0
  private joyY = 0
  private lookDX = 0
  private lookDY = 0
  private mineHeld = false
  private jumpHeld = false
  private jumpPressQueued = false
  private placeQueued = false
  private canvas: HTMLCanvasElement | null = null
  private hooks: InputHooks | null = null
  private stickEl: HTMLElement | null = null
  private knobEl: HTMLElement | null = null
  private stickPointer = -1
  private lookPointer = -1
  private dragging = false
  private lastX = 0
  private lastY = 0
  private wasLocked = false
  private ignoreUnlock = false
  private wheelHandler: ((e: WheelEvent) => void) | null = null

  attach(canvas: HTMLCanvasElement, stick: HTMLElement, knob: HTMLElement, buttons: TouchButtons,
    hooks: InputHooks): void {
    this.canvas = canvas
    this.stickEl = stick
    this.knobEl = knob
    this.hooks = hooks
    canvas.addEventListener('pointerdown', this.onCanvasDown)
    canvas.addEventListener('pointermove', this.onCanvasMove)
    canvas.addEventListener('pointerup', this.onCanvasUp)
    canvas.addEventListener('pointercancel', this.onCanvasUp)
    canvas.addEventListener('contextmenu', (e) => e.preventDefault())
    this.wheelHandler = (e) => {
      if (!this.enabled) return
      e.preventDefault()
      this.hooks?.onCycle(e.deltaY > 0 ? 1 : -1)
    }
    canvas.addEventListener('wheel', this.wheelHandler, { passive: false })
    window.addEventListener('keydown', this.onKeyDown)
    window.addEventListener('keyup', this.onKeyUp)
    window.addEventListener('blur', this.releaseAll)

    stick.addEventListener('pointerdown', this.onStickDown)
    stick.addEventListener('pointermove', this.onStickMove)
    stick.addEventListener('pointerup', this.onStickUp)
    stick.addEventListener('pointercancel', this.onStickUp)
    this.bindHold(buttons.mine, () => { this.mineHeld = true; this.touched = true }, () => { this.mineHeld = false })
    this.bindHold(buttons.jump, () => {
      this.jumpHeld = true
      this.jumpPressQueued = true
      this.touched = true
    }, () => { this.jumpHeld = false })
    buttons.place.addEventListener('pointerdown', (e) => {
      e.preventDefault()
      this.touched = true
      this.placeQueued = true
    })
    document.addEventListener('pointerlockchange', this.onLockChange)
  }

  /** 离开游戏/暂停时把按住的东西都松开,免得回来还在走 */
  releaseAll = (): void => {
    this.keys.clear()
    this.joyX = 0
    this.joyY = 0
    this.lookDX = 0
    this.lookDY = 0
    this.mineHeld = false
    this.jumpHeld = false
    this.jumpPressQueued = false
    this.placeQueued = false
    this.stickPointer = -1
    this.lookPointer = -1
    this.dragging = false
    if (this.knobEl) this.knobEl.style.transform = ''
  }

  /** 让鼠标进入锁定(桌面沉浸操作);浏览器拒绝就算了,拖拽也能看 */
  requestLock(): void {
    const canvas = this.canvas
    if (!canvas || document.pointerLockElement === canvas) return
    try {
      const r = canvas.requestPointerLock() as unknown
      if (r && typeof (r as Promise<void>).catch === 'function') (r as Promise<void>).catch(() => undefined)
    } catch (_) {
      /* 不支持/被拒绝:退回拖拽视角 */
    }
  }

  exitLock(): void {
    if (!this.canvas || document.pointerLockElement !== this.canvas) return
    this.ignoreUnlock = true
    try {
      document.exitPointerLock()
    } catch (_) {
      /* 忽略 */
    }
  }

  get pointerLocked(): boolean {
    return !!this.canvas && document.pointerLockElement === this.canvas
  }

  /** 前进/后退(-1..1),WASD 和摇杆叠加 */
  get forwardAxis(): number {
    let f = this.joyY
    if (this.keys.has('KeyW')) f += 1
    if (this.keys.has('KeyS')) f -= 1
    return clamp1(f)
  }

  /** 左右平移(-1..1) */
  get strafeAxis(): number {
    let s = this.joyX
    if (this.keys.has('KeyD')) s += 1
    if (this.keys.has('KeyA')) s -= 1
    return clamp1(s)
  }

  get jump(): boolean {
    return this.jumpHeld || this.keys.has('Space')
  }

  get mining(): boolean {
    return this.mineHeld
  }

  /** 方向键转视角(纯键盘也能玩):每帧由主循环按 dt 乘进去 */
  get lookKeys(): { x: number; y: number } {
    let x = 0
    let y = 0
    if (this.keys.has('ArrowLeft')) x -= 1
    if (this.keys.has('ArrowRight')) x += 1
    if (this.keys.has('ArrowUp')) y += 1
    if (this.keys.has('ArrowDown')) y -= 1
    return { x, y }
  }

  consumeLook(): { x: number; y: number } {
    const out = { x: this.lookDX, y: this.lookDY }
    this.lookDX = 0
    this.lookDY = 0
    return out
  }

  consumePlace(): boolean {
    const out = this.placeQueued
    this.placeQueued = false
    return out
  }

  /** 跳跃键「刚按下」的那一帧(给落地前跳跃缓冲用) */
  consumeJumpPress(): boolean {
    const out = this.jumpPressQueued
    this.jumpPressQueued = false
    return out
  }

  // ---------------------------------------------------------------- 事件

  private onKeyDown = (e: KeyboardEvent): void => {
    if (!this.enabled) return
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (e.code === 'Escape') {
      e.preventDefault()
      this.hooks?.onPause()
      return
    }
    const idx = hotbarIndexFromKey(e.key)
    if (idx >= 0) {
      e.preventDefault()
      this.hooks?.onHotbar(idx)
      this.touched = false
      return
    }
    if (e.code === 'Space' && !e.repeat) this.jumpPressQueued = true
    if (MOVE_KEYS.indexOf(e.code) >= 0 || LOOK_KEYS.indexOf(e.code) >= 0) {
      this.keys.add(e.code)
      e.preventDefault()
    }
  }

  private onKeyUp = (e: KeyboardEvent): void => {
    this.keys.delete(e.code)
  }

  private onLockChange = (): void => {
    const canvas = this.canvas
    if (!canvas) return
    const locked = document.pointerLockElement === canvas
    if (locked) {
      this.wasLocked = true
      return
    }
    if (this.ignoreUnlock) {
      this.ignoreUnlock = false
      return
    }
    // 用户按 Esc / 系统收回锁定:当成暂停
    if (this.wasLocked && this.enabled) this.hooks?.onPause()
    this.wasLocked = false
  }

  private onCanvasDown = (e: PointerEvent): void => {
    if (!this.enabled || !this.canvas) return
    if (e.pointerType === 'touch') {
      this.touched = true
      if (this.lookPointer >= 0) return
      this.lookPointer = e.pointerId
      this.lastX = e.clientX
      this.lastY = e.clientY
      try {
        this.canvas.setPointerCapture(e.pointerId)
      } catch (_) {
        /* 忽略 */
      }
      return
    }
    if (e.button === 0) {
      this.dragging = true
      this.lastX = e.clientX
      this.lastY = e.clientY
      this.mineHeld = true
      this.requestLock()
    } else if (e.button === 2) {
      this.placeQueued = true
    }
  }

  private onCanvasMove = (e: PointerEvent): void => {
    if (!this.enabled) return
    if (e.pointerType === 'touch') {
      if (this.lookPointer !== e.pointerId) return
      this.lookDX += (e.clientX - this.lastX) * TOUCH_SENS
      this.lookDY += (e.clientY - this.lastY) * TOUCH_SENS
      this.lastX = e.clientX
      this.lastY = e.clientY
      return
    }
    if (this.pointerLocked) {
      this.lookDX += e.movementX * MOUSE_SENS
      this.lookDY += e.movementY * MOUSE_SENS
    } else if (this.dragging) {
      this.lookDX += (e.clientX - this.lastX) * MOUSE_SENS
      this.lookDY += (e.clientY - this.lastY) * MOUSE_SENS
      this.lastX = e.clientX
      this.lastY = e.clientY
    }
  }

  private onCanvasUp = (e: PointerEvent): void => {
    if (e.pointerType === 'touch') {
      if (this.lookPointer === e.pointerId) this.lookPointer = -1
      return
    }
    if (e.button === 0) {
      this.dragging = false
      this.mineHeld = false
    }
  }

  private bindHold(btn: HTMLElement, down: () => void, up: () => void): void {
    btn.addEventListener('pointerdown', (e) => {
      e.preventDefault()
      down()
      try {
        btn.setPointerCapture((e as PointerEvent).pointerId)
      } catch (_) {
        /* 忽略 */
      }
    })
    const release = (): void => up()
    btn.addEventListener('pointerup', release)
    btn.addEventListener('pointercancel', release)
    btn.addEventListener('lostpointercapture', release)
  }

  private onStickDown = (e: PointerEvent): void => {
    if (!this.enabled || !this.stickEl) return
    e.preventDefault()
    this.touched = true
    this.stickPointer = e.pointerId
    try {
      this.stickEl.setPointerCapture(e.pointerId)
    } catch (_) {
      /* 忽略 */
    }
    this.updateStick(e.clientX, e.clientY)
  }

  private onStickMove = (e: PointerEvent): void => {
    if (e.pointerId !== this.stickPointer) return
    this.updateStick(e.clientX, e.clientY)
  }

  private onStickUp = (e: PointerEvent): void => {
    if (e.pointerId !== this.stickPointer) return
    this.stickPointer = -1
    this.joyX = 0
    this.joyY = 0
    if (this.knobEl) this.knobEl.style.transform = ''
  }

  private updateStick(clientX: number, clientY: number): void {
    const el = this.stickEl
    if (!el) return
    const rect = el.getBoundingClientRect()
    const cx = rect.left + rect.width / 2
    const cy = rect.top + rect.height / 2
    const radius = Math.max(1, rect.width / 2)
    let dx = (clientX - cx) / radius
    let dy = (clientY - cy) / radius
    const len = Math.sqrt(dx * dx + dy * dy)
    if (len < STICK_DEAD) {
      dx = 0
      dy = 0
    } else if (len > 1) {
      dx /= len
      dy /= len
    }
    this.joyX = dx
    this.joyY = -dy
    if (this.knobEl) this.knobEl.style.transform = `translate(${dx * radius * 0.5}px, ${dy * radius * 0.5}px)`
  }
}
