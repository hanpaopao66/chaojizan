// 突击时刻的入口:对局循环、输入(键盘鼠标 + 触屏摇杆/按钮)、弹层流程、存档和宿主能力。
//
// 规则/地图/武器在 map.ts / nav.ts / combat.ts / ai.ts / match.ts;HUD 在 hud.ts;
// 首页与弹层在 screens.ts;画在 render.ts/paint.ts;声音在 audio.ts;触屏输入在 touch.ts。
// 帧率无关:每帧 dt 最多 50ms;暂停、切后台、弹层打开时不推进逻辑。

import '../../shared/src/base.css'
import './style.css'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import { $, Overlay, WebApp, cacheKey, cloud, followTheme, hostGame, local, reduced } from '../../shared/src/ui'
import {
  play as sfx, pauseMusic, resume as audioResume, setSound, soundOn, startMusic, stopMusic,
  suspend as audioSuspend, unlock as audioUnlock,
} from './audio'
import { ACHIEVEMENTS, AchievementDef, evaluateAchievements, newlyUnlocked } from './achievements'
import { Difficulty } from './combat'
import { announce, bombUrgency, flashBanner, flashHit, resetHud, updateHud } from './hud'
import { GameMap, MapDef, MapId, Vec, angleTo, mapById, parseMap } from './map'
import {
  GameEvent, MatchState, PlayerInput, Round, advance, finishRound, newMatch, newRound, nextRound,
} from './match'
import {
  EMPTY_PROFILE, Profile, loadProfile, mergeProfile, recordMatch, unlockAchievements, withMap, withSettings,
} from './profile'
import { Renderer, readPalette } from './render'
import {
  renderHome, showAbout, showAchievements, showControls, showMatchResult, showPause, showRoundResult,
} from './screens'
import { readAim, readMove, resetTouch, setupTouch } from './touch'

// ---------------------------------------------------------------- DOM

const screen = $('screen')
const gameEl = $('game')
const canvas = $<HTMLCanvasElement>('field')
const overlay = new Overlay($('overlay'), () => canvas.focus())
const pauseBtn = $<HTMLButtonElement>('pause')
const soundBtn = $<HTMLButtonElement>('sound')

// ---------------------------------------------------------------- 存档

const slot = new SaveSlot<null, Profile>({
  cacheKey: cacheKey('tactical'),
  cloud,
  local,
  // 不存进行中的比赛:state 永远是 null,只有 best(战绩 + 设置 + 成就)会被写
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

const renderer = new Renderer(canvas)
/** 触屏输入(摇杆 + 换弹/切枪/安放按钮);返回值表示是不是触屏设备 */
const coarse = setupTouch({
  isBlocked: () => overlay.open || !running,
  onGesture: () => audioUnlock(),
  onReload: () => { reloadQueued = true },
  onSwap: () => { swapQueued = true },
  onPlant: (held) => { plantButtonHeld = held },
})

let mapDef: MapDef = mapById(EMPTY_PROFILE.mapId)
let map: GameMap = parseMap(mapDef)
let match: MatchState | null = null
let round: Round | null = null
let running = false
let paused = false
let matchSaved = false
let lastTs = 0
let roundOverTimer = 0
/** 当前这一个 rAF 的 id:重开前一局要先停掉旧循环,不然会叠加 */
let rafId = 0
/** 只给开发服务器上的测试钩子看:一直在涨说明只有一层循环 */
let frameCount = 0
/** 整场结算时展示的新成就 */
let lastUnlocked: readonly AchievementDef[] = []

// ---------------------------------------------------------------- 输入

const keys = new Set<string>()
const MOVE_KEYS = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])
let mouseWorld: Vec | null = null
let mouseInside = false
let fireHeld = false
let reloadQueued = false
let swapQueued = false
let plantButtonHeld = false

// 脚步:按走过的距离触发,不跟帧率绑定
let lastPlayerPos: Vec | null = null
let playerStepDist = 0
const guardPositions = new Map<number, Vec>()

// ---------------------------------------------------------------- 主题与画布

renderer.setPalette(readPalette())
followTheme(() => renderer.setPalette(readPalette()))

// ---------------------------------------------------------------- 首页

function renderHomeScreen(): void {
  renderHome(screen, {
    profile,
    onStart: () => startMatch(false),
    onTraining: () => startMatch(true),
    onDifficulty: (difficulty: Difficulty) => {
      profile = withSettings(profile, difficulty, profile.sound)
      slot.setBest(profile)
      void slot.flush()
      sfx('click', { vol: 0.4 })
    },
    onMap: (mapId: MapId) => {
      if (profile.mapId === mapId) return
      profile = withMap(profile, mapId)
      slot.setBest(profile)
      void slot.flush()
      sfx('click', { vol: 0.4 })
      renderHomeScreen()
    },
    onControls: () => showControls(overlay, () => undefined),
    onAbout: () => showAbout(overlay, profile, () => undefined),
    onAchievements: () => showAchievements(overlay, profile, () => undefined),
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

// ---------------------------------------------------------------- 暂停 / 结算弹层

function pauseGame(): void {
  if (!running || !round || !match || overlay.open || round.phase === 'over') return
  paused = true
  audioSuspend()
  void slot.flush()
  const current = round
  const currentMatch = match
  showPause(overlay, {
    round: current,
    match: currentMatch,
    profile,
    soundOn: () => soundOn(),
    onToggleSound: () => {
      toggleSound()
      return soundOn()
    },
    onResume: () => {
      paused = false
      overlay.hide()
      audioResume()
    },
    onRestart: () => startMatch(current.training),
    onHome: () => goHome(),
    onControls: () => showControls(overlay, () => overlay.hide()),
    onAbout: () => showAbout(overlay, profile, () => overlay.hide()),
    onDismiss: () => {
      paused = false
      audioResume()
    },
  })
}

/** 整场比赛一结束就记战绩(不是等玩家点「查看战报」才记),matchSaved 保证只记一次 */
function saveMatchResult(): void {
  if (!match || !match.over || matchSaved || match.training) return
  const m = match
  matchSaved = true
  profile = recordMatch(profile, {
    won: m.over === 'win',
    kills: m.stats.kills,
    plants: m.stats.plants,
    shots: m.stats.shots,
    hits: m.stats.hits,
  })
  const satisfied = evaluateAchievements(m)
  const fresh = newlyUnlocked(profile.achievements, satisfied)
  if (fresh.length) {
    profile = unlockAchievements(profile, fresh)
    lastUnlocked = fresh
      .map((id) => ACHIEVEMENTS.find((def) => def.id === id))
      .filter((def): def is AchievementDef => !!def)
    sfx('achieve')
    announce(`解锁成就:${lastUnlocked.map((def) => def.name).join('、')}`)
  } else {
    lastUnlocked = []
  }
  slot.setBest(profile)
  void slot.flush()
}

function showRoundOverFlow(): void {
  if (!match || !round || !round.over || !match.lastRound) return
  showRoundResult(overlay, {
    match,
    summary: match.lastRound,
    onNext: () => {
      overlay.hide()
      startNextRound()
    },
    onReport: showMatchOverFlow,
  })
}

function showMatchOverFlow(): void {
  if (!match || !match.over) return
  sfx(match.over === 'win' ? 'win' : 'lose')
  WebApp.HapticFeedback.notificationOccurred(match.over === 'win' ? 'success' : 'error')
  announce(match.over === 'win' ? '比赛胜利' : '比赛失败')
  showMatchResult(overlay, {
    match,
    profile,
    unlocked: lastUnlocked,
    onRetry: () => {
      overlay.hide()
      startMatch(false)
    },
    onHome: goHome,
  })
}

// ---------------------------------------------------------------- 一局比赛

function startMatch(training: boolean): void {
  // 重开/再来一局:先把上一局的渲染循环停掉,否则每开一局多叠一层 rAF
  stopLoop()
  mapDef = mapById(profile.mapId)
  map = parseMap(mapDef)
  document.documentElement.dataset.map = map.theme
  renderer.setPalette(readPalette())
  audioUnlock()
  if (!training) startMusic()
  sfx('click', { vol: 0.4 })
  overlay.hide()
  window.clearTimeout(roundOverTimer)
  screen.hidden = true
  gameEl.hidden = false
  document.body.classList.add('in-battle')
  match = newMatch(profile.difficulty, freshSeed(), { mapId: profile.mapId, training })
  matchSaved = false
  lastUnlocked = []
  paused = false
  running = true
  lastTs = 0
  renderer.reset()
  resetHud()
  startRound()
  // 点开始才进全屏、锁横屏(网页版宿主没有这两项时会失败,失败就算了)
  void WebApp.requestFullscreen().catch(() => undefined)
  void WebApp.lockOrientation().catch(() => undefined)
  rafId = window.requestAnimationFrame(loop)
  canvas.focus()
}

function startRound(): void {
  if (!match) return
  round = newRound(match, map)
  renderer.reset()
  resetHud()
  lastPlayerPos = null
  playerStepDist = 0
  guardPositions.clear()
  flashBanner(round.training ? '训练场' : `第 ${match.round} 回合`, 'good', 1100)
  announce(round.training ? '训练场开始,守卫会不断复活' : `第 ${match.round} 回合,准备`)
  refreshHud(true)
}

function startNextRound(): void {
  if (!match || match.training) return
  match = nextRound(match)
  startRound()
}

function goHome(): void {
  window.clearTimeout(roundOverTimer)
  overlay.hide()
  running = false
  paused = false
  stopLoop()
  stopMusic()
  match = null
  round = null
  fireHeld = false
  reloadQueued = false
  swapQueued = false
  plantButtonHeld = false
  keys.clear()
  lastPlayerPos = null
  guardPositions.clear()
  resetTouch()
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

/** 停掉当前渲染循环;startMatch / goHome 都从这里过,保证整个页面只有一层循环 */
function stopLoop(): void {
  if (rafId) window.cancelAnimationFrame(rafId)
  rafId = 0
}

function loop(ts: number): void {
  rafId = 0
  if (!running) return
  rafId = window.requestAnimationFrame(loop)
  frameCount++
  const dt = lastTs === 0 ? 0 : Math.min(0.05, Math.max(0, (ts - lastTs) / 1000))
  lastTs = ts
  renderer.resize()
  if (!round) return
  if (!paused && !overlay.open) {
    const step = advance(round, dt, readInput())
    round = step.round
    handleEvents(step.events)
    updateFootsteps(round)
  }
  const aim = readAim()
  renderer.draw(round, {
    mouse: coarse ? null : (mouseInside ? mouseWorld : null),
    aimAngle: coarse && aim.active ? Math.atan2(aim.dy, aim.dx) : null,
    reduced: reduced(),
    now: ts,
  })
  refreshHud()
  // 暂停 / 弹层打开时 BGM 一起降下来
  pauseMusic(paused || overlay.open)
}

function aliveGuards(): number {
  return round ? round.guards.filter((g) => g.alive).length : 0
}

/** 脚步声:玩家按走过的距离触发;附近的守卫也踩出声,给玩家听声辨位 */
function updateFootsteps(r: Round): void {
  const p = r.player
  if (p.alive) {
    if (lastPlayerPos) {
      playerStepDist += Math.hypot(p.pos.x - lastPlayerPos.x, p.pos.y - lastPlayerPos.y)
      if (playerStepDist > 30) {
        playerStepDist = 0
        sfx('step', { x: p.pos.x, y: p.pos.y, listener: p.pos, vol: 0.2, gap: 220 })
      }
    }
    lastPlayerPos = { x: p.pos.x, y: p.pos.y }
  } else {
    lastPlayerPos = null
  }
  for (const g of r.guards) {
    const last = guardPositions.get(g.id)
    if (!g.alive) {
      guardPositions.delete(g.id)
      continue
    }
    if (last) {
      const moved = Math.hypot(g.pos.x - last.x, g.pos.y - last.y)
      const near = Math.hypot(g.pos.x - p.pos.x, g.pos.y - p.pos.y) < 460
      if (moved > 22 && near && p.alive) {
        sfx('step', { x: g.pos.x, y: g.pos.y, listener: p.pos, vol: 0.09, gap: 110 })
      }
    }
    guardPositions.set(g.id, { x: g.pos.x, y: g.pos.y })
  }
}

function handleEvents(events: GameEvent[]): void {
  const playerPos = round ? round.player.pos : null
  for (const ev of events) {
    switch (ev.type) {
      case 'live':
        flashBanner('行动开始', 'good', 900)
        announce('行动开始,75 秒')
        sfx('tick')
        break
      case 'shot':
        if (ev.team === 'player') {
          sfx('shot', { x: ev.x, y: ev.y, listener: playerPos ?? undefined, vol: 0.5 })
          renderer.addShake(0.6)
        } else {
          sfx('guardShot', { x: ev.x, y: ev.y, listener: playerPos ?? undefined, vol: 0.32 })
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
        if (!round?.training) {
          flashBanner(left > 0 ? '击倒守卫' : '守卫已清空', 'good', 900)
          announce(left > 0 ? `击倒一名守卫,还剩 ${left} 名` : '守卫已清空,去安放炸弹')
        }
        WebApp.HapticFeedback.notificationOccurred('success')
        break
      }
      case 'death':
        sfx('hurt')
        renderer.addShake(6)
        WebApp.HapticFeedback.notificationOccurred('error')
        if (round?.training) flashBanner('被击倒 · 马上复活', 'bad', 1200)
        break
      case 'respawn':
        if (ev.side === 'player') {
          announce('重新投入训练')
          sfx('tick')
          flashBanner('重新投入', 'good', 700)
        }
        break
      case 'reload':
        sfx('reload')
        break
      case 'swap':
        sfx('swap')
        announce(ev.weapon === 'pistol' ? '切换到 手枪' : '切换到 步枪')
        flashBanner(ev.weapon === 'pistol' ? '手枪' : '步枪', 'warn', 600)
        break
      case 'empty':
        sfx('empty')
        break
      case 'planting':
        announce('正在安放炸弹')
        sfx('plant', { x: round?.player.pos.x, y: round?.player.pos.y, listener: playerPos ?? undefined })
        break
      case 'plant':
        sfx('planted', { x: ev.pos.x, y: ev.pos.y, listener: playerPos ?? undefined })
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
        sfx('explode', { x: ev.pos.x, y: ev.pos.y, listener: playerPos ?? undefined })
        renderer.addShake(9)
        flashBanner('炸弹爆炸', 'good', 1500)
        announce('炸弹爆炸了')
        WebApp.HapticFeedback.notificationOccurred('success')
        break
      case 'beep':
        if (round?.bomb.pos) {
          sfx('beep', {
            x: round.bomb.pos.x, y: round.bomb.pos.y, listener: playerPos ?? undefined,
            rate: bombUrgency(round), gap: 120,
          })
        }
        break
      case 'roundOver':
        if (round && match) match = finishRound(match, round)
        saveMatchResult()
        if (ev.side === 'player') {
          sfx('win')
          announce(ev.reason === 'exploded' ? '回合胜利:炸弹爆炸' : '回合胜利')
        } else {
          sfx('lose')
          announce(`回合失败:${reasonText(ev.reason)}`)
        }
        window.clearTimeout(roundOverTimer)
        roundOverTimer = window.setTimeout(() => {
          if (!running || !round || round.phase !== 'over' || overlay.open) return
          showRoundOverFlow()
        }, ev.reason === 'exploded' ? 1200 : 850)
        break
    }
  }
}

function reasonText(reason: string): string {
  switch (reason) {
    case 'exploded': return '炸弹爆炸'
    case 'defused': return '守卫把炸弹拆掉了'
    case 'playerKilled': return '你被守卫击倒了'
    case 'timeout': return '时间耗尽,炸弹还没安放'
    default: return reason
  }
}

// ---------------------------------------------------------------- 输入读取

function moveVector(): { x: number; y: number } {
  const stick = readMove()
  if (stick) return stick
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
  const aimStick = readAim()
  let aim: number | null = null
  if (aimStick.active) {
    aim = Math.atan2(aimStick.dy, aimStick.dx)
  } else if (mouseInside && mouseWorld && round) {
    aim = angleTo(round.player.pos, mouseWorld)
  }
  const fire = aimStick.active ? Math.hypot(aimStick.dx, aimStick.dy) > 0.3 : fireHeld
  const interact = keys.has('KeyE') || plantButtonHeld
  const input: PlayerInput = {
    moveX: mv.x, moveY: mv.y, aim, fire,
    reload: reloadQueued, swap: swapQueued, interact,
  }
  reloadQueued = false
  swapQueued = false
  return input
}

// ---------------------------------------------------------------- 键盘鼠标

window.addEventListener('keydown', (e) => {
  // Overlay 的 Esc 处理已经 preventDefault 了(它自己 hide + onDismiss),这里别再补一刀
  if (e.defaultPrevented) return
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const code = e.code
  if (MOVE_KEYS.has(code)) {
    keys.add(code)
    e.preventDefault()
    audioUnlock()
  } else if (code === 'KeyR') {
    reloadQueued = true
    e.preventDefault()
  } else if (code === 'KeyQ') {
    swapQueued = true
    e.preventDefault()
  } else if (code === 'KeyE') {
    keys.add('KeyE')
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
mapDef = mapById(profile.mapId)
map = parseMap(mapDef)
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
mapDef = mapById(profile.mapId)
map = parseMap(mapDef)
setSound(profile.sound)
if (!running) renderHomeScreen()

slot.restoreCloud().then((restored) => {
  profile = slot.best
  mapDef = mapById(profile.mapId)
  map = parseMap(mapDef)
  setSound(profile.sound)
  if (restored === 'cleared') profile = EMPTY_PROFILE
  if (!running) renderHomeScreen()
}).finally(ready)

// 只在开发服务器上有的测试钩子(只读状态,操作仍走真实键鼠)。生产构建里这段会被去掉。
if (import.meta.env.DEV) {
  void import('./devhook').then(({ installDevHook }) => {
    installDevHook({
      round: () => round,
      match: () => match,
      running: () => running,
      paused: () => paused,
      coarse: () => coarse,
      map: () => map,
      frames: () => frameCount,
    })
  })
}
