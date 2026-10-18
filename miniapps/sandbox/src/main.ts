// 方块原野的装配层:菜单 / 进世界 / 主循环 / 存档 / HUD / 音效 / 宿主生命周期。
//
// 玩法在 gameplay.ts(Game 类,可单测),画面在 render.ts,菜单在 menus.ts,输入在 input.ts;
// 这里只做「把设备输入翻译成 GameInput、把副作用接到 HUD/音效/存档/弹层、每帧推进」。
import '../../shared/src/base.css'
import './style.css'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import {
  $, Overlay, WebApp, cacheKey, cloud, confirmBox, followTheme, hostGame, local, reduced,
} from '../../shared/src/ui'
import {
  isMuted, resumeAudio, setAmbience, setMuted, setUnderwater, sound, suspendAudio, unlockAudio,
} from './audio'
import { HOTBAR, WATER, blockName } from './blocks'
import { ACHIEVEMENTS, FEEL, LIMITS, type AchievementDef, type SoundName, type SoundOptions } from './data'
import { achievementsPanel, aboutPanel, cleanupPanel, helpPanel, mainMenu, newWorldPanel, pausePanel,
  type MenuApp, type MenuStats } from './menus'
import { Game, type GameInput } from './gameplay'
import { Hud, type HudState } from './hud'
import { Input } from './input'
import { copyProfile, loadProfile, mergeProfile, unlockedCount, type Profile } from './profile'
import { Renderer, type Camera } from './render'
import { loadSave, newSave, saveOf, type GameSave, type LegacyStats } from './save'
import { legacyOf, mergeLegacy, migrateLegacy, profileForWrite } from './sync'
import { daylight, wrapTime } from './time'
import { World } from './world'
import { seedText } from './worldgen'

const VERSION = '1.1.1'
const nextPaint = (): Promise<void> =>
  new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))

// ---------------------------------------------------------------- 存档

const slot = new SaveSlot<GameSave, Profile>({
  cacheKey: cacheKey('sandbox'),
  cloud,
  local,
  loadState: loadSave,
  saveState: (s) => saveOf(s),
  loadBest: (raw) => loadProfile(raw),
  mergeBest: (a, b) => mergeProfile(a, b),
  emptyBest: copyProfile({ v: 2, mined: 0, placed: 0, walked: 0, seconds: 0, achievements: {} }),
  delay: 900,
  minGap: 2500,
})

// ---------------------------------------------------------------- DOM / 状态

const gameEl = $('game')
const canvas = $<HTMLCanvasElement>('view')
const menuEl = $('menu')
const loadingEl = $('loading')
const overlay = new Overlay($('overlay'), () => undefined)

let screen: 'menu' | 'game' = 'menu'
let paused = true
let entering = false
let saveTimer = 0
let hudTimer = 0
let ambientTimer = 0
let raf = 0
let lastFrame = 0
let quality = 1
let frameSamples = 0
let frameMsSum = 0
let profilePending = false
let pendingCleanup = false
let bobPhase = 0
/** 旧 v1 存档里待迁移的挖/放统计 */
let pendingLegacy: LegacyStats | null = null
/** 云端对账完成(进世界前必须等它,免得拿云对账前的旧档案开局) */
let cloudReady: Promise<unknown> = Promise.resolve()

const hud = new Hud((index) => selectSlot(index))
const game = new Game({
  sound: (name, opts) => soundByName(name, opts),
  toast: (text) => hud.toast(text),
  announce: (text) => hud.announce(text),
  achievement: (def) => onAchievement(def),
  cleanupNeeded: () => { pendingCleanup = true },
  markDirty: (kind) => { if (kind === 'profile') profilePending = true },
})
const renderer = new Renderer(canvas)
const input = new Input()

function soundByName(name: SoundName, opts?: SoundOptions): void {
  sound(name, opts)
}

function selectSlot(i: number): void {
  if (screen !== 'game' || paused) return
  if (game.selectSlot(i)) hud.itemName(blockName(HOTBAR[i]))
}

function onAchievement(def: AchievementDef): void {
  hud.achievement(def)
  sound('achieve')
  hud.announce(`成就解锁:${def.name}`)
  writeProfileSafe()
}

// ---------------------------------------------------------------- 存档动作

function countEdits(text: string | undefined): number {
  if (!text) return 0
  let n = 0
  for (let i = 0; i < text.length; i++) if (text.charCodeAt(i) === 44) n++
  return text.endsWith(',') ? n : n + 1
}

/**
 * 把本机档案写回 SaveSlot:一律先和已经和云端对过账的 slot.best 合并。
 * SaveSlot.setBest 是替换语义;如果拿云对账前拷出来的旧档案直接写回,
 * 会把云端较新的统计/成就盖掉,所以这里统一走 merge(统计取大、成就并集)。
 */
function writeProfileSafe(): void {
  const merged = profileForWrite(slot.best, game.profile)
  slot.setBest(merged)
  game.profile = copyProfile(merged)
  profilePending = false
}

/** 云端对账返回后,把它合并进来的档案同步给正在进行的游戏 */
function syncProfileFromSlot(): void {
  if (screen !== 'game' || !game.world) return
  const merged = profileForWrite(slot.best, game.profile)
  slot.setBest(merged)
  game.profile = copyProfile(merged)
  profilePending = false
}

/** 记下旧 v1 存档里的挖/放统计(本机缓存和云端 v1 档都可能带) */
function captureLegacy(): void {
  pendingLegacy = mergeLegacy(pendingLegacy, legacyOf(slot.state))
}

/**
 * v1→v2 迁移:把旧档的挖/放统计并进档案。
 * - 只在云对账完成之后调用(否则「迁移」会让旧本机档看起来更新,盖掉另一台设备较新的云档);
 * - 迁移本身不调用 slot.change,不动存档的时间戳 at。
 */
function applyLegacyProfile(): void {
  if (!pendingLegacy) return
  const legacy = pendingLegacy
  pendingLegacy = null
  const migrated = migrateLegacy(slot.best, legacy)
  if (migrated.changed) slot.setBest(migrated.profile)
  const state = slot.state
  if (state) delete state.legacy
}

/** 立刻把世界和档案写进 SaveSlot(云端由 SaveSlot 节流) */
function saveNow(): void {
  if (!game.world) return
  slot.change(game.snapshot())
  writeProfileSafe()
}

// ---------------------------------------------------------------- 菜单

function currentStats(): MenuStats {
  if (screen === 'game' && game.world) {
    return {
      hasSave: true,
      seed: game.world.seed,
      mined: game.profile.mined,
      placed: game.profile.placed,
      walked: game.profile.walked,
      seconds: game.profile.seconds,
      achievements: unlockedCount(game.profile),
      achievementsTotal: ACHIEVEMENTS.length,
      edits: game.world.editCount,
      muted: isMuted(),
      version: VERSION,
    }
  }
  const s = slot.state
  const p = slot.best
  return {
    hasSave: !!s,
    seed: s ? s.seed : 0,
    mined: p.mined,
    placed: p.placed,
    walked: p.walked,
    seconds: p.seconds,
    achievements: unlockedCount(p),
    achievementsTotal: ACHIEVEMENTS.length,
    edits: s ? countEdits(s.edits) : 0,
    muted: isMuted(),
    version: VERSION,
  }
}

function renderMenu(): void {
  if (screen !== 'menu') return
  mainMenu(menuEl, menuApp)
  hud.sound(isMuted())
  WebApp.BackButton.hide()
}

function toggleSound(): void {
  unlockAudio()
  setMuted(!isMuted())
  if (!isMuted()) sound('click')
  hud.sound(isMuted())
  if (screen === 'menu') renderMenu()
  else if (paused && overlay.open) pausePanel(overlay, pauseApp)
}

const menuApp: MenuApp = {
  stats: currentStats,
  resume: () => {
    const s = slot.state
    if (s) void enterGame(s)
    else openNewWorld()
  },
  newWorld: () => openNewWorld(),
  help: () => helpPanel(overlay),
  about: () => aboutPanel(overlay, currentStats()),
  achievements: () => achievementsPanel(overlay, currentStats(), slot.best, game.achievementContext()),
  toggleSound,
  quitToMenu: () => { void requestQuit() },
  cleanup: () => undefined,
}

const pauseApp: MenuApp = {
  stats: currentStats,
  resume: () => resumeGame(),
  newWorld: () => openNewWorld(),
  help: () => helpPanel(overlay, () => pausePanel(overlay, pauseApp)),
  about: () => aboutPanel(overlay, currentStats(), () => pausePanel(overlay, pauseApp)),
  achievements: () => achievementsPanel(overlay, currentStats(), game.profile, game.achievementContext(),
    () => pausePanel(overlay, pauseApp)),
  toggleSound,
  quitToMenu: () => { void requestQuit() },
  cleanup: () => openCleanup(),
}

function openNewWorld(): void {
  newWorldPanel(overlay, slot.state ? slot.state.seed : null, (seed) => {
    void (async () => {
      if (slot.state) {
        const ok = await confirmBox('开始一个新世界?现在这个世界会自动存档,但菜单里只留最新的一个。')
        if (!ok) return
      }
      await startNewWorld(seed)
    })()
  })
}

async function startNewWorld(seedOrNull: number | null): Promise<void> {
  const seed = (seedOrNull === null ? freshSeed() : seedOrNull) >>> 0
  loadingEl.hidden = false
  await nextPaint()
  const fresh = new World(seed)
  const save = newSave(seed, fresh.spawn, fresh.yaw)
  loadingEl.hidden = true
  await enterGame(save, fresh)
}

async function requestQuit(): Promise<void> {
  const ok = await confirmBox('回到主菜单?进度已经自动存档。')
  if (!ok) {
    if (screen === 'game' && paused) pausePanel(overlay, pauseApp)
    return
  }
  overlay.hide()
  exitToMenu()
}

function exitToMenu(): void {
  if (screen !== 'game') return
  pauseGame(false)
  saveNow()
  void slot.flush()
  stopLoop()
  screen = 'menu'
  game.world = null
  gameEl.hidden = true
  menuEl.hidden = false
  setAmbience(0.6, false)
  renderMenu()
}

// ---------------------------------------------------------------- 进世界

async function enterGame(save: GameSave, prebuilt: World | null = null): Promise<void> {
  if (entering) return
  entering = true
  unlockAudio()
  overlay.hide()
  menuEl.hidden = true
  loadingEl.hidden = false
  // 等云端对账完成:否则可能拿「云对账前」的旧档案开局,再写回去盖掉云端较新的统计/成就
  await cloudReady
  await nextPaint()
  try {
    const world = prebuilt ?? new World(save.seed)
    if (!prebuilt && !world.loadEdits(save.edits)) world.loadEdits('')
    game.load(save, copyProfile(slot.best), world)
    hud.buildHotbar()
    hud.sound(isMuted())
    hud.itemName(blockName(HOTBAR[game.hot]))
    screen = 'game'
    gameEl.hidden = false
    loadingEl.hidden = true
    renderer.setQuality(quality)
    renderer.resize()
    hud.refresh(hudState())
    paused = false
    input.enabled = true
    lastFrame = performance.now()
    saveTimer = 0
    hudTimer = 0
    ambientTimer = 99
    bobPhase = 0
    render()
    startLoop()
    WebApp.requestFullscreen().catch(() => undefined)
    WebApp.lockOrientation().catch(() => undefined)
    WebApp.BackButton.show()
    sound('click')
    if (prebuilt) {
      saveNow()
      void slot.flush()
    }
    hud.announce(`进入世界,种子 ${seedText(world.seed)}`)
  } catch (err) {
    loadingEl.hidden = true
    menuEl.hidden = false
    gameEl.hidden = true
    screen = 'menu'
    game.world = null
    renderMenu()
    throw err
  } finally {
    entering = false
  }
}

function pauseGame(openPanel = true): void {
  if (screen !== 'game' || paused || !game.world) return
  paused = true
  input.enabled = false
  input.releaseAll()
  input.exitLock()
  saveNow()
  void slot.flush()
  setAmbience(daylight(game.time), false)
  render()
  if (openPanel) pausePanel(overlay, pauseApp)
}

function resumeGame(): void {
  if (screen !== 'game' || !paused) return
  overlay.hide()
  paused = false
  input.enabled = true
  lastFrame = performance.now()
  ambientTimer = 99
  setAmbience(daylight(game.time), true)
  render()
}

// ---------------------------------------------------------------- 改动容量清理

function openCleanup(): void {
  if (screen !== 'game' || !game.world) return
  if (!paused) pauseGame(false)
  render()
  const back = (): void => {
    overlay.hide()
    resumeGame()
  }
  cleanupPanel(overlay, game.world.editCount, back, () => {
    game.cleanupRecent()
    saveNow()
    render()
    resumeGame()
  }, () => {
    game.cleanupAll()
    saveNow()
    render()
    resumeGame()
  })
}

// ---------------------------------------------------------------- 主循环

function startLoop(): void {
  if (raf) return
  lastFrame = performance.now()
  raf = requestAnimationFrame(frame)
}

function stopLoop(): void {
  if (raf) cancelAnimationFrame(raf)
  raf = 0
}

function frame(now: number): void {
  raf = requestAnimationFrame(frame)
  const raw = now - lastFrame
  const dt = Math.min(FEEL.MAX_DT, Math.max(0, raw / 1000))
  lastFrame = now
  if (screen !== 'game' || !game.world || paused) return
  stepGame(dt)
  if (!paused) render()
  // 自适应画质:每 90 帧看一次平均帧时间,跟不上就降内部渲染分辨率
  if (raw > 0 && raw < 250) frameMsSum += raw
  frameSamples++
  if (frameSamples >= 90) {
    const avg = frameMsSum / frameSamples
    if (avg > 24 && quality > FEEL_QUALITY_MIN) {
      quality = Math.max(FEEL_QUALITY_MIN, quality - 0.15)
      renderer.setQuality(quality)
    } else if (avg < 13 && quality < 1) {
      quality = Math.min(1, quality + 0.1)
      renderer.setQuality(quality)
    }
    frameSamples = 0
    frameMsSum = 0
  }
}

const FEEL_QUALITY_MIN = 0.5

function buildInput(): GameInput {
  const look = input.consumeLook()
  const keys = input.lookKeys
  return {
    forward: input.forwardAxis,
    strafe: input.strafeAxis,
    jump: input.jump,
    jumpPressed: input.consumeJumpPress(),
    mine: input.mining,
    placePressed: input.consumePlace(),
    lookDX: look.x,
    lookDY: look.y,
    lookKeyX: keys.x,
    lookKeyY: keys.y,
  }
}

function stepGame(dt: number): void {
  game.update(dt, buildInput())
  const dirty = game.takeDirty()
  if (dirty.world) slot.change(game.snapshot())
  if (dirty.profile) profilePending = true

  // 视角晃动(减少动态效果时不做)
  const moving = Math.hypot(game.player.vx, game.player.vz) > 0.8
  if (!reduced() && moving && game.player.onGround) bobPhase += dt * 8.5
  else if (!moving) bobPhase *= Math.max(0, 1 - dt * 8)

  // 环境声 / 水下音效:每 2 秒更新一次状态
  ambientTimer += dt
  if (ambientTimer >= 2) {
    ambientTimer = 0
    setAmbience(daylight(game.time), true)
    setUnderwater(game.eyeBlock() === WATER)
  }

  // 走动/时间的存档节流 + 档案写回
  saveTimer += dt
  if (saveTimer >= LIMITS.SAVE_EVERY) {
    saveTimer = 0
    if (game.world) slot.change(game.snapshot())
    if (profilePending) writeProfileSafe()
  }

  hudTimer += dt
  if (hudTimer >= LIMITS.HUD_EVERY) {
    hudTimer = 0
    hud.refresh(hudState())
    hud.mine(game.miningProgress)
  }

  if (pendingCleanup) {
    pendingCleanup = false
    openCleanup()
  }
}

function hudState(): HudState {
  return {
    time: game.time,
    x: game.player.x,
    y: game.player.y,
    z: game.player.z,
    target: game.target,
    inv: game.inv,
    hot: game.hot,
    edits: game.world ? game.world.editCount : 0,
  }
}

function render(): void {
  const world = game.world
  if (!world) return
  renderer.resize()
  const eye = game.eye
  const moving = Math.hypot(game.player.vx, game.player.vz) > 0.8
  const bob = !reduced() && moving && game.player.onGround ? Math.sin(bobPhase) * 0.045 : 0
  const cam: Camera = {
    x: eye.x,
    y: eye.y + bob,
    z: eye.z,
    yaw: game.player.yaw,
    pitch: game.player.pitch,
  }
  renderer.render(world, {
    cam,
    time: game.time,
    target: game.target,
    mining: game.miningProgress,
    particles: game.particles,
  })
}

// ---------------------------------------------------------------- 宿主生命周期 / 设备

hostGame(() => {
  if (screen === 'game') {
    if (!paused) pauseGame()
    saveNow()
    void slot.flush()
  }
  suspendAudio()
})

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    resumeAudio()
    unlockAudio()
  }
})

window.addEventListener('resize', () => {
  if (screen !== 'game') return
  renderer.resize()
  if (paused) render()
})

window.addEventListener('pointerdown', () => unlockAudio(), { once: true, capture: true })
window.addEventListener('keydown', () => unlockAudio(), { once: true, capture: true })

followTheme()
input.attach(canvas, $('stick'), $('stick-knob'), {
  jump: $('btn-jump'),
  mine: $('btn-mine'),
  place: $('btn-place'),
}, {
  onHotbar: (index) => selectSlot(index),
  onCycle: (dir) => {
    if (screen !== 'game' || paused) return
    game.cycleSlot(dir)
    hud.itemName(blockName(HOTBAR[game.hot]))
  },
  onPause: () => pauseGame(),
})

const touch = matchMedia('(pointer: coarse)').matches || 'ontouchstart' in window
if (touch) {
  $('touch').hidden = false
  $('hud-hint').hidden = true
}

$('btn-pause').addEventListener('click', () => pauseGame())
$('btn-sound').addEventListener('click', toggleSound)
WebApp.SettingsButton.show().onClick(() => {
  if (screen === 'game') pauseGame()
  else aboutPanel(overlay, currentStats())
})
WebApp.BackButton.onClick(() => {
  if (overlay.open) {
    overlay.hide()
    if (screen === 'game' && paused) resumeGame()
    return
  }
  if (screen === 'game') pauseGame()
})

// ---------------------------------------------------------------- 启动

renderMenu()
slot.restoreLocal()
captureLegacy()
if (slot.state) renderMenu()
// 云对账:完成后再迁移 v1 统计/同步档案;'cleared'(用户在宿主里清空过数据)时丢弃待迁移统计
cloudReady = slot.restoreCloud().then((restored) => {
  if (restored === 'cleared') {
    pendingLegacy = null
  } else {
    captureLegacy()
    applyLegacyProfile()
  }
  syncProfileFromSlot()
  if (screen === 'menu') renderMenu()
  return restored
}).catch(() => undefined)
let readied = false
const ready = (): void => {
  if (readied) return
  readied = true
  WebApp.ready().catch(() => undefined)
}
setTimeout(ready, 900)

// 开发时的测试钩子:浏览器冒烟脚本用它确认世界真的在跑/拨时间看昼夜。
// 生产构建里 import.meta.env.DEV 是 false,整段会被去掉(check_miniapp_meta 会扫构建产物里的 __sandbox)。
if (import.meta.env.DEV) {
  (window as unknown as Record<string, unknown>).__sandbox = {
    screen: () => screen,
    paused: () => paused,
    version: () => VERSION,
    seed: () => (game.world ? game.world.seed : 0),
    player: () => ({ x: game.player.x, y: game.player.y, z: game.player.z, yaw: game.player.yaw, pitch: game.player.pitch }),
    edits: () => (game.world ? game.world.editCount : 0),
    target: () => game.target,
    stats: () => currentStats(),
    achievements: () => game.profile.achievements,
    time: () => game.time,
    setTime(t: number) {
      game.time = wrapTime(t)
      if (game.world) render()
    },
    give(slotIndex: number, n: number) {
      game.inv[slotIndex] = Math.max(0, Math.min(LIMITS.MAX_STACK, n))
      hud.refresh(hudState())
    },
    /** 只给 QA 用:直接把视角转到指定朝向(0..2π, -1.3..1.3) */
    look(yaw: number, pitch: number) {
      game.player.yaw = yaw
      game.player.pitch = Math.max(-FEEL.PITCH_LIMIT, Math.min(FEEL.PITCH_LIMIT, pitch))
      if (game.world) render()
    },
    /** 只给 QA 用:在空中造 n 处编辑,模拟接近/到达 4000 格上限 */
    fillEdits(n: number) {
      const world = game.world
      if (!world) return 0
      let made = 0
      for (let y = 47; y >= 30 && made < n; y--) {
        for (let z = 5; z < 120 && made < n; z++) {
          for (let x = 5; x < 120 && made < n; x++) {
            if (world.blockAt(x, y, z) !== 0) continue
            if (world.setBlock(x, y, z, 3) === 'ok') made++
          }
        }
      }
      hud.refresh(hudState())
      return made
    },
  }
}
