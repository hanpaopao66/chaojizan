// 触屏输入:左右半屏各一个「按下才出现」的虚拟摇杆 + 换弹/切枪/安放按钮。
//
// 和 main.ts 拆开是为了两边都短一点;这里只管收集触点、算出归一化向量,不碰游戏规则。

import { $ } from '../../shared/src/ui'

export interface TouchHandlers {
  /** 弹层打开 / 不在对局里时忽略触点 */
  isBlocked: () => boolean
  /** 第一次触摸时解锁 AudioContext */
  onGesture: () => void
  onReload: () => void
  onSwap: () => void
  /** 按住安放按钮 = 按住键盘 E */
  onPlant: (held: boolean) => void
}

interface StickState { pointer: number; active: boolean; ox: number; oy: number; dx: number; dy: number }

const moveStick: StickState = { pointer: -1, active: false, ox: 0, oy: 0, dx: 0, dy: 0 }
const aimStick: StickState = { pointer: -1, active: false, ox: 0, oy: 0, dx: 0, dy: 0 }
let enabled = false

function resetStick(stick: StickState, stickEl: HTMLElement): void {
  stick.active = false
  stick.pointer = -1
  stick.dx = 0
  stick.dy = 0
  stickEl.hidden = true
}

function setupStick(zoneId: string, stickId: string, stick: StickState, isAim: boolean, handlers: TouchHandlers): void {
  const zone = $(zoneId)
  const stickEl = $(stickId)
  const knob = stickEl.querySelector('.knob') as HTMLElement | null
  if (isAim) stickEl.classList.add('aim')
  const radius = 48
  zone.addEventListener('pointerdown', (e) => {
    if (handlers.isBlocked()) return
    e.preventDefault()
    handlers.onGesture()
    stick.pointer = e.pointerId
    stick.active = true
    stick.ox = e.clientX
    stick.oy = e.clientY
    stick.dx = 0
    stick.dy = 0
    stickEl.hidden = false
    stickEl.style.left = `${e.clientX}px`
    stickEl.style.top = `${e.clientY}px`
    if (knob) knob.style.transform = 'translate(0px, 0px)'
    try { zone.setPointerCapture(e.pointerId) } catch (_) { /* 老浏览器 */ }
  })
  zone.addEventListener('pointermove', (e) => {
    if (!stick.active || stick.pointer !== e.pointerId) return
    e.preventDefault()
    let dx = e.clientX - stick.ox
    let dy = e.clientY - stick.oy
    const d = Math.hypot(dx, dy)
    if (d > radius) {
      dx = (dx / d) * radius
      dy = (dy / d) * radius
    }
    stick.dx = dx / radius
    stick.dy = dy / radius
    if (knob) knob.style.transform = `translate(${dx}px, ${dy}px)`
  })
  const end = (e: PointerEvent): void => {
    if (stick.pointer !== e.pointerId) return
    resetStick(stick, stickEl)
    if (knob) knob.style.transform = 'translate(0px, 0px)'
  }
  zone.addEventListener('pointerup', end)
  zone.addEventListener('pointercancel', end)
}

/** 初始化触屏 UI;返回是不是触屏设备。桌面端会把整套触屏 DOM 移除 */
export function setupTouch(handlers: TouchHandlers): boolean {
  enabled = matchMedia('(pointer: coarse)').matches || ('ontouchstart' in window && !matchMedia('(pointer: fine)').matches)
  const touchEl = $('touch')
  if (!enabled) {
    touchEl.remove()
    return false
  }
  touchEl.hidden = false
  $('game').classList.add('touch-mode')
  setupStick('zone-move', 'stick-move', moveStick, false, handlers)
  setupStick('zone-aim', 'stick-aim', aimStick, true, handlers)
  $<HTMLButtonElement>('btn-reload').addEventListener('click', () => {
    handlers.onGesture()
    handlers.onReload()
  })
  $<HTMLButtonElement>('btn-swap').addEventListener('click', () => {
    handlers.onGesture()
    handlers.onSwap()
  })
  const plant = $<HTMLButtonElement>('btn-plant')
  plant.addEventListener('pointerdown', (e) => {
    e.preventDefault()
    handlers.onGesture()
    handlers.onPlant(true)
    // 手指按住 2.5 秒不能中途丢:把指针捕获到按钮上,滑出一点也还算按住
    try { plant.setPointerCapture(e.pointerId) } catch (_) { /* 老浏览器 */ }
  })
  const endPlant = (): void => handlers.onPlant(false)
  plant.addEventListener('pointerup', endPlant)
  plant.addEventListener('pointercancel', endPlant)
  plant.addEventListener('lostpointercapture', endPlant)
  return true
}

export function touchEnabled(): boolean {
  return enabled
}

/** 移动摇杆向量;没在推返回 null(让键盘接管) */
export function readMove(): { x: number; y: number } | null {
  return moveStick.active ? { x: moveStick.dx, y: moveStick.dy } : null
}

/** 瞄准摇杆:active 时才改变朝向 / 开火 */
export function readAim(): { dx: number; dy: number; active: boolean } {
  return { dx: aimStick.dx, dy: aimStick.dy, active: aimStick.active }
}

/** 回首页/重开时把手里的摇杆状态清掉 */
export function resetTouch(): void {
  if (!enabled) return
  resetStick(moveStick, $('stick-move'))
  resetStick(aimStick, $('stick-aim'))
}
