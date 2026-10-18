// 突击时刻的入口:对局循环、输入(键盘鼠标 + 触屏双摇杆)、弹层流程、存档和宿主能力。
//
// 规则全在 map.ts / nav.ts / combat.ts / ai.ts / match.ts;HUD 在 hud.ts;首页和说明在 screens.ts;
// 画在 render.ts。这里只负责「把输入喂进去、把状态画出来、把流程串起来」。
// 帧率无关:每帧 dt 最多 50ms;暂停、切后台、弹层打开时不推进逻辑,所以回来不会突然跳一大步。

import '../../shared/src/base.css'
import './style.css'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import {
  $, Overlay, WebApp, button, cacheKey, cloud, confirmBox, el, followTheme, hostGame, local, reduced, row,
} from '../../shared/src/ui'
import { play as sfx, resume as audioResume, setSound, soundOn, suspend as audioSuspend, unlock as audioUnlock } from './audio'
import { DIFFICULTY_LABELS, Difficulty } from './combat'
import { announce, bombUrgency, flashBanner, flashHit, formatClock, resetHud, updateHud } from './hud'
import { GameMap, Vec, angleTo, parseMap } from './map'
import {
  GameEvent, MatchState, OverReason, PlayerInput, Round, accuracyOf, advance, finishRound, newMatch, newRound, nextRound,
} from './match'
import { EMPTY_PROFILE, Profile, loadProfile, mergeProfile, recordMatch, withSettings } from './profile'
import { Renderer, readPalette } from './render'
import { renderHome, showAbout, showControls } from './screens'

// ---------------------------------------------------------------- DOM

const screen = $('screen')
const gameEl = $('game')
const canvas = $<HTMLCanvasElement>('field')
const overlay = new Overlay($('overlay'), () => canvas.focus())
const pauseBtn = $<HTMLButtonElement>('pause')
const soundBtn = $<HTMLButtonElement>('sound')
const touchEl = $('touch')
const btnReload = $<HTMLButtonElement>('btn-reload')
const btnPlant = $<HTMLButtonElement>('btn-plant')
const stickMoveEl = $('stick-move')
const stickAimEl = $('stick-aim')

// ---------------------------------------------------------------- 存档

const slot = new SaveSlot<null, Profile>({
  cacheKey: cacheKey('tactical'),
  cloud,
  local,
  // 不存进行中的比赛:state 永远是 null,只有 best(战绩 + 设置)会被写
  loadState: () => null,
  saveState: () => null,
  loadBest: loadProfile,
  mergeBest: mergeProfile,
  emptyBest: EMPTY_PROFILE,
  delay: 600,
  minGap: 3000,
})

let profile: Profile = EMPTY_PROFILE

// ---------------------------------------------------------------- 全局状态

const map: GameMap = parseMap()
const renderer = new Renderer(canvas)
/** 指针是不是「粗」的(手机/平板):决定显示双摇杆还是键鼠提示 */
const coarse = matchMedia('(pointer: coarse)').matches || ('ontouchstart' in window && !matchMedia('(pointer: fine)').matches)

let match: MatchState | null = null
let round: Round | null = null
let running = false
let paused = false
let matchSaved = false
let lastTs = 0
let roundOverTimer = 0

// ---------------------------------------------------------------- 输入

const keys = new Set<string>()
const MOVE_KEYS = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])
let mouseWorld: Vec | null = null
let mouseInside = false
let fireHeld = false
let reloadQueued = false
let plantButtonHeld = false

interface StickState { pointer: number; active: boolean; ox: number; oy: number; dx: number; dy: number }
const moveStick: StickState = { pointer: -1, active: false, ox: 0, oy: 0, dx: 0, dy: 0 }
const aimStick: StickState = { pointer: -1, active: false, ox: 0, oy: 0, dx: 0, dy: 0 }

// ---------------------------------------------------------------- 主题与画布

renderer.setPalette(readPalette())
followTheme(() => renderer.setPalette(readPalette()))

// ---------------------------------------------------------------- 首页

function renderHomeScreen(): void {
  renderHome(screen, {
    profile,
    onStart: startMatch,
    onDifficulty: (difficulty: Difficulty) => {
      profile = withSettings(profile, difficulty, profile.sound)
      slot.setBest(profile)
      void slot.flush()
      sfx('click', { vol: 0.4 })
    },
    onControls: () => showControls(overlay, () => undefined),
    onAbout: () => showAbout(overlay, profile, () => undefined),
    onToggleSound: () => {
      toggleSound()
      return soundOn()
    },
  })
}

function toggleSound(): void {
  const on = !soundOn()
  profile = withSettings(profile, profile.difficulty, on)
  setSound(on)
  slot.setBest(profile)
  void slot.flush()
  if (on) sfx('click', { vol: 0.4 })
}

// ---------------------------------------------------------------- 弹层:暂停 / 回合结果 / 比赛结果

function pauseGame(): void {
  if (!running || !round || !match || overlay.open || round.phase === 'over') return
  paused = true
  audioSuspend()
  void slot.flush()
  const m = match
  overlay.show((p) => {
    p.append(el('h2', '已暂停'))
    p.append(el('p', `第 ${m.round} 回合 · 比分 ${m.scorePlayer} : ${m.scoreGuard}`, 'sub'))
    const soundRow = el('div', '', 'soundrow')
    soundRow.append(el('span', '声音'))
    const soundToggle = button(soundOn() ? '开' : '关', () => {
      toggleSound()
      soundToggle.textContent = soundOn() ? '开' : '关'
      soundToggle.setAttribute('aria-pressed', String(soundOn()))
    })
    soundToggle.setAttribute('aria-pressed', String(soundOn()))
    soundRow.append(soundToggle)
    p.append(soundRow)
    p.append(row(button('继续', () => { overlay.hide(); paused = false; audioResume() }, 'primary')))
    p.append(row(
      button('重新开始', () => {
        void (async () => {
          if (!(await confirmBox('这一局从头来过?当前比分不保留。'))) return
          overlay.hide()
          startMatch()
        })()
      }),
      button('回首页', () => {
        void (async () => {
          if (!(await confirmBox('结束这一局回首页?没打完的比赛不记战绩。'))) return
          goHome()
        })()
      }),
    ))
    p.append(row(
      button('操作说明', () => showControls(overlay, () => pauseGame())),
      button('关于', () => showAbout(overlay, profile, () => pauseGame())),
    ))
  }, {
    cls: 'pause',
    onDismiss: () => {
      paused = false
      audioResume()
    },
  })
}

function reasonText(reason: OverReason): string {
  switch (reason) {
    case 'exploded': return '炸弹爆炸,回合拿下。'
    case 'defused': return '守卫把炸弹拆掉了。'
    case 'playerKilled': return '你被守卫击倒了。'
    case 'timeout': return '时间耗尽,炸弹还没安放。'
  }
}

function showRoundOver(): void {
  if (!match || !round || !round.over || !match.lastRound) return
  const last = match.lastRound
  const won = last.side === 'player'
  const m = match
  overlay.show((p) => {
    p.append(el('h2', won ? '回合拿下' : '回合失守'))
    p.append(el('p', reasonText(last.reason), 'sub'))
    p.append(statGrid([
      ['本回合击杀', String(last.kills)],
      ['用时', `${Math.round(last.seconds)} 秒`],
      ['比分', `${m.scorePlayer} : ${m.scoreGuard}`],
    ]))
    if (m.over) {
      p.append(row(button('查看战报', showMatchOver, 'primary')))
    } else {
      p.append(row(button('下一回合', () => { overlay.hide(); startNextRound() }, 'primary')))
    }
  }, { cls: won ? 'result-win' : 'result-lose' })
}

function showMatchOver(): void {
  if (!match || !match.over) return
  const m = match
  const won = m.over === 'win'
  if (!matchSaved) {
    matchSaved = true
    profile = recordMatch(profile, {
      won,
      kills: m.stats.kills,
      plants: m.stats.plants,
      shots: m.stats.shots,
      hits: m.stats.hits,
    })
    slot.setBest(profile)
    void slot.flush()
  }
  sfx(won ? 'win' : 'lose')
  WebApp.HapticFeedback.notificationOccurred(won ? 'success' : 'error')
  announce(won ? '比赛胜利' : '比赛失败')
  overlay.show((p) => {
    p.append(el('h2', won ? '行动成功' : '行动失败'))
    p.append(el('p', `${m.scorePlayer} : ${m.scoreGuard} · ${DIFFICULTY_LABELS[m.difficulty]}难度`, 'substat'))
    p.append(statGrid([
      ['总击杀', String(m.stats.kills)],
      ['安放次数', String(m.stats.plants)],
      ['命中率', `${Math.round(accuracyOf(m.stats) * 100)}%`],
      ['最佳连胜', String(profile.bestStreak)],
      ['用时', formatClock(m.stats.seconds)],
    ]))
    p.append(row(
      button('再来一局', () => { overlay.hide(); startMatch() }, 'primary'),
      button('回首页', goHome),
    ))
  }, { cls: won ? 'result-win' : 'result-lose' })
}

function statGrid(items: Array<[string, string]>): HTMLElement {
  const grid = el('div', '', 'statgrid')
  for (const [label, value] of items) {
    const cell = el('div')
    cell.append(el('b', value), el('small', label))
    grid.append(cell)
  }
  return grid
}

// ---------------------------------------------------------------- 一局比赛

function startMatch(): void {
  audioUnlock()
  sfx('click', { vol: 0.4 })
  overlay.hide()
  window.clearTimeout(roundOverTimer)
  screen.hidden = true
  gameEl.hidden = false
  document.body.classList.add('in-battle')
  match = newMatch(profile.difficulty, freshSeed())
  matchSaved = false
  paused = false
  running = true
  lastTs = 0
  renderer.reset()
  resetHud()
  startRound()
  // 点开始才进全屏、锁横屏(网页版宿主没有这两项时会失败,失败就算了)
  void WebApp.requestFullscreen().catch(() => undefined)
  void WebApp.lockOrientation().catch(() => undefined)
  window.requestAnimationFrame(loop)
  canvas.focus()
}

function startRound(): void {
  if (!match) return
  round = newRound(match, map)
  renderer.reset()
  resetHud()
  flashBanner(`第 ${match.round} 回合`, 'good', 1100)
  announce(`第 ${match.round} 回合,准备`)
  refreshHud(true)
}

function startNextRound(): void {
  if (!match) return
  match = nextRound(match)
  startRound()
}

function goHome(): void {
  window.clearTimeout(roundOverTimer)
  overlay.hide()
  running = false
  paused = false
  match = null
  round = null
  fireHeld = false
  reloadQueued = false
  plantButtonHeld = false
  keys.clear()
  resetStick(moveStick, stickMoveEl)
  resetStick(aimStick, stickAimEl)
  gameEl.hidden = true
  screen.hidden = false
  document.body.classList.remove('in-battle')
  audioSuspend()
  void slot.flush()
  renderHomeScreen()
  void WebApp.exitFullscreen().catch(() => undefined)
}

// ---------------------------------------------------------------- 对局循环

function refreshHud(force = false): void {
  if (!round || !match) return
  updateHud(round, match, { coarse, active: running && !gameEl.hidden }, force)
}

function loop(ts: number): void {
  if (!running) return
  window.requestAnimationFrame(loop)
  const dt = lastTs === 0 ? 0 : Math.min(0.05, Math.max(0, (ts - lastTs) / 1000))
  lastTs = ts
  renderer.resize()
  if (!round) return
  if (!paused && !overlay.open) {
    const step = advance(round, dt, readInput())
    round = step.round
    handleEvents(step.events)
  }
  renderer.draw(round, {
    mouse: coarse ? null : (mouseInside ? mouseWorld : null),
    aimAngle: coarse && aimStick.active ? Math.atan2(aimStick.dy, aimStick.dx) : null,
    reduced: reduced(),
    now: ts,
  })
  refreshHud()
}

function aliveGuards(): number {
  return round ? round.guards.filter((g) => g.alive).length : 0
}

function handleEvents(events: GameEvent[]): void {
  for (const ev of events) {
    switch (ev.type) {
      case 'live':
        flashBanner('行动开始', 'good', 900)
        announce('行动开始,75 秒')
        sfx('tick')
        break
      case 'shot':
        if (ev.team === 'player') {
          sfx('shot')
          renderer.addShake(0.6)
        } else {
          sfx('guardShot')
          renderer.addShake(0.35)
        }
        break
      case 'hit':
        if (ev.target === 'player') {
          sfx('hurt')
          renderer.addShake(2.6)
          flashHit('#FF9B8A')
          WebApp.HapticFeedback.impactOccurred('medium')
        } else {
          sfx('hit')
          flashHit('#FFF3C4')
        }
        break
      case 'kill': {
        sfx('hit')
        flashHit('#FFF3C4')
        const left = aliveGuards()
        flashBanner(left > 0 ? '击倒守卫' : '守卫已清空', 'good', 900)
        announce(left > 0 ? `击倒一名守卫,还剩 ${left} 名` : '守卫已清空,去安放炸弹')
        WebApp.HapticFeedback.notificationOccurred('success')
        break
      }
      case 'death':
        sfx('hurt')
        renderer.addShake(6)
        WebApp.HapticFeedback.notificationOccurred('error')
        break
      case 'reload':
        sfx('reload')
        break
      case 'empty':
        sfx('empty')
        break
      case 'planting':
        announce('正在安放炸弹')
        sfx('plant')
        break
      case 'plant':
        sfx('planted')
        renderer.addShake(2)
        flashBanner('炸弹已安放', 'warn', 1300)
        announce('炸弹已安放,守住 30 秒')
        WebApp.HapticFeedback.notificationOccurred('warning')
        break
      case 'defusing':
        sfx('defuse')
        flashBanner('守卫在拆弹!', 'bad', 1200)
        announce('守卫开始拆除炸弹,快去阻止')
        renderer.addShake(1.2)
        break
      case 'defused':
        sfx('defused')
        break
      case 'explode':
        sfx('explode')
        renderer.addShake(9)
        flashBanner('炸弹爆炸', 'good', 1500)
        announce('炸弹爆炸了')
        WebApp.HapticFeedback.notificationOccurred('success')
        break
      case 'beep':
        if (round) sfx('beep', { rate: bombUrgency(round), gap: 120 })
        break
      case 'roundOver':
        if (round && match) match = finishRound(match, round)
        if (ev.side === 'player') {
          sfx('win')
          announce(ev.reason === 'exploded' ? '回合胜利:炸弹爆炸' : '回合胜利')
        } else {
          sfx('lose')
          announce(`回合失败:${reasonText(ev.reason).replace('。', '')}`)
        }
        window.clearTimeout(roundOverTimer)
        roundOverTimer = window.setTimeout(() => {
          if (!running || !round || round.phase !== 'over' || overlay.open) return
          showRoundOver()
        }, ev.reason === 'exploded' ? 1200 : 850)
        break
    }
  }
}

// ---------------------------------------------------------------- 输入读取

function moveVector(): { x: number; y: number } {
  if (moveStick.active) return { x: moveStick.dx, y: moveStick.dy }
  let x = 0
  let y = 0
  if (keys.has('KeyA') || keys.has('ArrowLeft')) x -= 1
  if (keys.has('KeyD') || keys.has('ArrowRight')) x += 1
  if (keys.has('KeyW') || keys.has('ArrowUp')) y -= 1
  if (keys.has('KeyS') || keys.has('ArrowDown')) y += 1
  return { x, y }
}

function readInput(): PlayerInput {
  const mv = moveVector()
  let aim: number | null = null
  if (aimStick.active) {
    aim = Math.atan2(aimStick.dy, aimStick.dx)
  } else if (mouseInside && mouseWorld && round) {
    aim = angleTo(round.player.pos, mouseWorld)
  }
  const fire = aimStick.active ? Math.hypot(aimStick.dx, aimStick.dy) > 0.3 : fireHeld
  const interact = keys.has('KeyE') || plantButtonHeld
  const input: PlayerInput = { moveX: mv.x, moveY: mv.y, aim, fire, reload: reloadQueued, interact }
  reloadQueued = false
  return input
}

// ---------------------------------------------------------------- 键盘鼠标

window.addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const code = e.code
  if (MOVE_KEYS.has(code)) {
    keys.add(code)
    e.preventDefault()
    audioUnlock()
  } else if (code === 'KeyR') {
    reloadQueued = true
    e.preventDefault()
  } else if (code === 'KeyE') {
    e.preventDefault()
  } else if (code === 'KeyM') {
    toggleSound()
    soundBtn.textContent = soundOn() ? '声' : '静'
  } else if (code === 'Escape' && !overlay.open && running) {
    pauseGame()
  }
  if (running && !overlay.open) audioUnlock()
})
window.addEventListener('keyup', (e) => { keys.delete(e.code) })
window.addEventListener('blur', () => { keys.clear(); fireHeld = false })

canvas.addEventListener('pointermove', (e) => {
  if (e.pointerType !== 'mouse') return
  mouseInside = true
  mouseWorld = renderer.worldAt(e.clientX, e.clientY)
})
canvas.addEventListener('pointerleave', (e) => {
  if (e.pointerType === 'mouse') mouseInside = false
})
canvas.addEventListener('pointerdown', (e) => {
  if (e.pointerType !== 'mouse' || e.button !== 0) return
  e.preventDefault()
  mouseInside = true
  mouseWorld = renderer.worldAt(e.clientX, e.clientY)
  fireHeld = true
  audioUnlock()
})
window.addEventListener('pointerup', (e) => {
  if (e.pointerType === 'mouse' && e.button === 0) fireHeld = false
})
canvas.addEventListener('contextmenu', (e) => e.preventDefault())

// ---------------------------------------------------------------- 触屏双摇杆

function resetStick(stick: StickState, stickEl: HTMLElement): void {
  stick.active = false
  stick.pointer = -1
  stick.dx = 0
  stick.dy = 0
  stickEl.hidden = true
}

function setupStick(zoneId: string, stickId: string, stick: StickState, isAim: boolean): void {
  const zone = $(zoneId)
  const stickEl = $(stickId)
  const knob = stickEl.querySelector('.knob') as HTMLElement | null
  if (isAim) stickEl.classList.add('aim')
  const radius = 48
  zone.addEventListener('pointerdown', (e) => {
    if (overlay.open || !running) return
    e.preventDefault()
    audioUnlock()
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

if (coarse) {
  touchEl.hidden = false
  gameEl.classList.add('touch-mode')
  setupStick('zone-move', 'stick-move', moveStick, false)
  setupStick('zone-aim', 'stick-aim', aimStick, true)
  btnReload.addEventListener('click', () => {
    reloadQueued = true
    audioUnlock()
  })
  btnPlant.addEventListener('pointerdown', (e) => { e.preventDefault(); plantButtonHeld = true; audioUnlock() })
  const endPlant = (): void => { plantButtonHeld = false }
  btnPlant.addEventListener('pointerup', endPlant)
  btnPlant.addEventListener('pointercancel', endPlant)
  btnPlant.addEventListener('pointerleave', endPlant)
} else {
  touchEl.remove()
}

// ---------------------------------------------------------------- 宿主

pauseBtn.addEventListener('click', () => pauseGame())
soundBtn.addEventListener('click', () => {
  toggleSound()
  soundBtn.textContent = soundOn() ? '声' : '静'
})
soundBtn.textContent = soundOn() ? '声' : '静'

WebApp.SettingsButton.show().onClick(() => {
  if (overlay.open) return
  if (running) pauseGame()
  else showAbout(overlay, profile, () => undefined)
})
WebApp.BackButton.onClick(() => {
  if (overlay.open) {
    const wasPaused = paused
    overlay.hide()
    if (wasPaused && running) pauseGame()
    return
  }
  if (running) pauseGame()
})
hostGame(() => {
  audioSuspend()
  if (running && round && round.phase !== 'over') {
    if (!overlay.open) pauseGame()
    else paused = true
  }
  void slot.flush()
})
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') audioResume()
})
window.addEventListener('resize', () => renderer.resize())

// ---------------------------------------------------------------- 启动

renderer.resize()
profile = slot.best
setSound(profile.sound)
renderHomeScreen()
canvas.focus()

// 第一次点击/按键之后才解锁音频(浏览器的自动播放限制)
window.addEventListener('pointerdown', () => audioUnlock(), { once: true, capture: true })
window.addEventListener('keydown', () => audioUnlock(), { once: true, capture: true })

let readied = false
const ready = (): void => {
  if (readied) return
  readied = true
  WebApp.ready().catch(() => undefined)
}
setTimeout(ready, 1500)

slot.restoreLocal()
profile = slot.best
setSound(profile.sound)
if (!running) renderHomeScreen()

slot.restoreCloud().then((restored) => {
  profile = slot.best
  setSound(profile.sound)
  if (restored === 'cleared') profile = EMPTY_PROFILE
  if (!running) renderHomeScreen()
}).finally(ready)
