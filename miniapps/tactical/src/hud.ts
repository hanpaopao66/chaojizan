// 对局 HUD:顶部比分/计时、血量、弹药、炸弹状态、击杀播报。只读对局状态,不碰规则。
//
// 文本更新按帧节流(约 60ms):每一帧都改 DOM 会让弱一点的手机掉帧,
// 但事件类的东西(击杀、炸弹、胜负)走 flashBanner / flashHit / announce,该立刻出现就立刻出现。

import { $ } from '../../shared/src/ui'
import { BOMB_TIME, MatchState, Round, canPlant } from './match'

const hudRound = $('hud-round')
const scoreMe = $('score-me')
const scoreThem = $('score-them')
const hudTimer = $('hud-timer')
const hpEl = $('hp')
const hpFill = $('hp-fill')
const hpNum = $('hp-num')
const bombStatus = $('bomb-status')
const hudAmmo = $('hud-ammo')
const ammoMag = $('ammo-mag')
const ammoRes = $('ammo-res')
const reloadTip = $('reload-tip')
const hudHint = $('hud-hint')
const bannerEl = $('hud-banner')
const hitEl = $('hud-hit')
const live = $('live')
const btnPlant = $<HTMLButtonElement>('btn-plant')

let lastHudAt = 0
let bannerTimer = 0
let hitTimer = 0

export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const mm = Math.floor(total / 60)
  const ss = total % 60
  return `${mm}:${String(ss).padStart(2, '0')}`
}

/** 读屏播报:回合、击杀、炸弹、胜负都从这里过 aria-live */
export function announce(text: string): void {
  live.textContent = text
}

export function flashBanner(text: string, cls: string, ms: number): void {
  bannerEl.textContent = text
  bannerEl.className = `hud-banner ${cls}`
  bannerEl.hidden = false
  // 重新触发 CSS 动画(和 critters 里 toast 的写法一样)
  void bannerEl.offsetWidth
  window.clearTimeout(bannerTimer)
  bannerTimer = window.setTimeout(() => { bannerEl.hidden = true }, ms)
}

/** 命中反馈:屏幕中间闪一个小 ×。颜色区分打中敌人 / 自己挨打 */
export function flashHit(color: string): void {
  hitEl.style.color = color
  hitEl.hidden = false
  hitEl.classList.remove('show')
  void hitEl.offsetWidth
  hitEl.classList.add('show')
  window.clearTimeout(hitTimer)
  hitTimer = window.setTimeout(() => { hitEl.hidden = true }, 240)
}

export interface HudInfo {
  /** 触屏:安放提示写「按住安放按钮」而不是 E;底部键位提示隐藏 */
  coarse: boolean
  /** 对局界面是不是还显示着(回首页之后别再改 DOM) */
  active: boolean
}

/** 每帧更新 HUD;force 跳过节流(开一回合、暂停结束时用) */
export function updateHud(round: Round, match: MatchState, info: HudInfo, force = false): void {
  if (!info.active) return
  const now = performance.now()
  if (!force && now - lastHudAt < 60) return
  lastHudAt = now
  const p = round.player

  const hp = Math.max(0, Math.round(p.hp))
  hpFill.style.transform = `scaleX(${hp / 100})`
  hpNum.textContent = String(hp)
  hpEl.classList.toggle('low', hp <= 35)

  ammoMag.textContent = String(p.gun.mag)
  ammoRes.textContent = String(p.gun.reserve)
  hudAmmo.classList.toggle('reloading', p.gun.reloadLeft > 0)
  reloadTip.textContent = p.gun.reloadLeft > 0 ? '换弹中…' : p.gun.mag === 0 ? '按 R 换弹' : ''

  hudRound.textContent = `第 ${match.round} 回合`
  scoreMe.textContent = String(match.scorePlayer)
  scoreThem.textContent = String(match.scoreGuard)

  // 计时器:准备 / 回合剩余 / 炸弹倒计时
  hudTimer.classList.remove('low', 'bomb')
  if (round.phase === 'freeze') {
    hudTimer.textContent = `准备 ${Math.ceil(round.clock)}`
  } else if (round.bomb.state === 'planted') {
    hudTimer.textContent = formatClock(round.bomb.timer)
    hudTimer.classList.add('bomb')
    if (round.bomb.timer <= 5) hudTimer.classList.add('low')
  } else {
    hudTimer.textContent = formatClock(round.clock)
    if (round.clock <= 10) hudTimer.classList.add('low')
  }

  // 炸弹状态
  const b = round.bomb
  bombStatus.classList.remove('danger', 'planting')
  if (b.state === 'carried' && p.site) {
    bombStatus.hidden = false
    bombStatus.textContent = `在 ${p.site} 点按住 ${info.coarse ? '「安放」' : ' E '} 2.5 秒安放炸弹`
  } else if (b.state === 'planting') {
    bombStatus.hidden = false
    bombStatus.classList.add('planting')
    bombStatus.textContent = `正在安放炸弹 ${Math.round(b.plant * 100)}%`
  } else if (b.state === 'planted') {
    bombStatus.hidden = false
    if (b.defuse > 0.001) {
      bombStatus.classList.add('danger')
      bombStatus.textContent = `守卫正在拆弹 ${Math.round(b.defuse * 100)}% —— 打断他!`
    } else {
      bombStatus.textContent = `炸弹已安放 · 守住 ${Math.ceil(b.timer)} 秒`
    }
  } else {
    bombStatus.hidden = true
  }

  // 手机上的「安放」按钮:站到 A/B 点上才出现;按住不放等于按住 E
  if (info.coarse) {
    const planting = b.state === 'planting'
    const plantable = !planting && canPlant(round)
    btnPlant.hidden = !(planting || plantable)
    if (planting) btnPlant.textContent = `安放中 ${Math.round(b.plant * 100)}%`
    else if (plantable && p.site) btnPlant.textContent = `安放 ${p.site}`
  }

  hudHint.hidden = info.coarse || round.phase === 'over'
  hudHint.textContent = 'WASD 移动 · 鼠标瞄准 · 左键开火 · R 换弹 · E 安放 · Esc 暂停'
}

/** 新开一局:把上一局残留的红字/弹层文字清掉(元素还在同一个页面上) */
export function resetHud(): void {
  window.clearTimeout(bannerTimer)
  window.clearTimeout(hitTimer)
  bannerEl.hidden = true
  hitEl.hidden = true
  bombStatus.hidden = true
  btnPlant.hidden = true
  // 触屏时上面的 updateHud 会按 canPlant 重新显隐;这里只清掉上一局残留
}

// 炸弹计时的进度(0..1),给音效决定「滴」得多急
export function bombUrgency(round: Round): number {
  if (round.bomb.state !== 'planted') return 1
  return 1 + (1 - Math.min(1, round.bomb.timer / BOMB_TIME)) * 2
}
