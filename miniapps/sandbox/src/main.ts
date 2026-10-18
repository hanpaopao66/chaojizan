// 方块原野的入口:菜单 / 进世界 / 主循环 / 挖和放 / 存档 / HUD / 宿主生命周期。
// 纯逻辑在 worldgen / world / raycast / player / time / save,画面在 render,菜单在 menus,输入在 input。
import '../../shared/src/base.css'
import './style.css'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import {
  $, Overlay, WebApp, cacheKey, cloud, confirmBox, followTheme, hostGame, local, reduced,
} from '../../shared/src/ui'
import { AIR, HOTBAR, WATER, blockName, breakTime } from './blocks'
import { addBlock, newInventory, takeBlock } from './inventory'
import { Input } from './input'
import { isMuted, setMuted, sfx, suspend as audioSuspend, unlock as audioUnlock } from './audio'
import { Hud } from './hud'
import {
  aboutPanel, helpPanel, mainMenu, newWorldPanel, pausePanel, type MenuApp, type MenuStats,
} from './menus'
import { cameraEye, clampPitch, newPlayer, placePlayer, stepPlayer, type PlayerState } from './player'
import { placePosition, rayFromEye, type RayHit } from './raycast'
import { Renderer, type Camera } from './render'
import { loadSave, newSave, saveOf, type GameSave } from './save'
import { DAY_SECONDS, wrapTime } from './time'
import { MAX_EDITS, World } from './world'
import { SEA_LEVEL, seedText } from './worldgen'

const VERSION = '1.0.0'
/** 准星最多能够到几格 */
const REACH = 5
/** 走动时多久存一次(编辑是立刻存的) */
const SAVE_EVERY = 2.5
/** 一轮昼夜多少秒 */
const DAY_LENGTH = DAY_SECONDS

/** 云端 best 键用不到,但 SaveSlot 需要:放一个空对象就行 */
interface EmptyBest {
  v: 1
}

const slot = new SaveSlot<GameSave, EmptyBest>({
  cacheKey: cacheKey('sandbox'),
  cloud,
  local,
  loadState: loadSave,
  saveState: (s) => saveOf(s),
  loadBest: (raw) => (raw && typeof raw === 'object' && (raw as { v?: unknown }).v === 1 ? { v: 1 } : null),
  mergeBest: (a) => a,
  emptyBest: { v: 1 },
  // 编辑后 1 秒内写一次,云端两次写至少隔 2.5 秒(走动存档也走同一条节流)
  delay: 900,
  minGap: 2500,
})

// ---------------------------------------------------------------- DOM

const gameEl = $('game')
const canvas = $<HTMLCanvasElement>('view')
const menuEl = $('menu')
const loadingEl = $('loading')
const overlay = new Overlay($('overlay'), () => undefined)
const hud = new Hud((index) => selectSlot(index))

let renderer: Renderer
const input = new Input()
let screen: 'menu' | 'game' = 'menu'
let world: World | null = null
let player: PlayerState = newPlayer(64.5, SEA_LEVEL + 4, 64.5, 0)
let inv = newInventory()
let hot = 0
let dayTime = 0.06
let currentSeed = 0
let mined = 0
let placed = 0
let paused = true
let entering = false
let target: RayHit | null = null
let miningProgress = 0
let miningKey = ''
let mineTick = 0
let bedrockWarned = false
let bobPhase = 0
let saveTimer = 0
let hudTimer = 0
let raf = 0
let lastFrame = 0
let quality = 1
let frameSamples = 0
let frameMsSum = 0
let editsDirty = false
let editsCache = ''

const nextPaint = (): Promise<void> =>
  new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))

// ---------------------------------------------------------------- 存档快照

function countEdits(text: string | undefined): number {
  if (!text) return 0
  let n = 0
  for (let i = 0; i < text.length; i++) if (text.charCodeAt(i) === 44) n++
  return text.endsWith(',') ? n : n + 1
}

/** 世界有改动时把稀疏编辑表重新编码一次(4000 条排序约几毫秒,只在改动后做) */
function editsText(): string {
  if (world && editsDirty) {
    editsCache = world.serializeEdits()
    editsDirty = false
  }
  return editsCache
}

function snapshot(): GameSave {
  return {
    v: 1,
    seed: currentSeed >>> 0,
    edits: editsText(),
    player: { x: player.x, y: player.y, z: player.z, yaw: player.yaw, pitch: player.pitch },
    time: wrapTime(dayTime),
    inv: inv.slice(),
    hot,
    mined,
    placed,
  }
}

function commitNow(): void {
  if (!world) return
  slot.change(snapshot())
}

/** 当前状态(菜单和「关于」显示用):在游戏里就用内存里的实时数字 */
function currentStats(): MenuStats {
  if (screen === 'game' && world) {
    return {
      hasSave: true, seed: currentSeed, mined, placed, edits: countEdits(editsText()),
      muted: isMuted(), version: VERSION,
    }
  }
  const s = slot.state
  return {
    hasSave: !!s, seed: s ? s.seed : 0, mined: s ? s.mined : 0, placed: s ? s.placed : 0,
    edits: s ? countEdits(s.edits) : 0, muted: isMuted(), version: VERSION,
  }
}

// ---------------------------------------------------------------- 菜单

function renderMenu(): void {
  mainMenu(menuEl, app)
  hud.sound(isMuted())
  WebApp.BackButton.hide()
}

function toggleSound(): void {
  audioUnlock()
  setMuted(!isMuted())
  if (!isMuted()) sfx('click')
  hud.sound(isMuted())
  if (screen === 'menu') renderMenu()
  else if (paused && overlay.open) pausePanel(overlay, pauseApp)
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

const app: MenuApp = {
  stats: currentStats,
  resume: () => {
    const s = slot.state
    if (s) void enterGame(s)
    else openNewWorld()
  },
  newWorld: openNewWorld,
  help: () => helpPanel(overlay),
  about: () => aboutPanel(overlay, currentStats()),
  toggleSound,
  quitToMenu: () => { void requestQuit() },
}

const pauseApp: MenuApp = {
  stats: currentStats,
  resume: () => resumeGame(),
  newWorld: openNewWorld,
  help: () => helpPanel(overlay, () => pausePanel(overlay, pauseApp)),
  about: () => aboutPanel(overlay, currentStats(), () => pausePanel(overlay, pauseApp)),
  toggleSound,
  quitToMenu: () => { void requestQuit() },
}

async function requestQuit(): Promise<void> {
  const ok = await confirmBox('回到主菜单?进度已经自动存档。')
  if (!ok) {
    if (paused) pausePanel(overlay, pauseApp)
    return
  }
  overlay.hide()
  exitToMenu()
}

function exitToMenu(): void {
  if (screen !== 'game') return
  paused = true
  input.enabled = false
  input.releaseAll()
  input.exitLock()
  commitNow()
  void slot.flush()
  stopLoop()
  screen = 'menu'
  gameEl.hidden = true
  menuEl.hidden = false
  world = null
  target = null
  miningProgress = 0
  miningKey = ''
  renderMenu()
}

// ---------------------------------------------------------------- 进世界

async function enterGame(save: GameSave, prebuilt: World | null = null): Promise<void> {
  if (entering) return
  entering = true
  audioUnlock()
  overlay.hide()
  menuEl.hidden = true
  loadingEl.hidden = false
  await nextPaint()
  try {
    let w = prebuilt
    if (!w) {
      w = new World(save.seed)
      // 存档里的编辑串在 loadSave 里验过格式,这里再对一遍方块底座;失败就当新世界
      if (!w.loadEdits(save.edits)) w.loadEdits('')
    }
    world = w
    currentSeed = save.seed >>> 0
    inv = save.inv.slice()
    hot = Math.max(0, Math.min(HOTBAR.length - 1, Math.floor(save.hot)))
    dayTime = wrapTime(save.time)
    mined = save.mined
    placed = save.placed
    editsCache = save.edits
    editsDirty = false
    player = newPlayer(save.player.x, save.player.y, save.player.z, save.player.yaw)
    player.pitch = clampPitch(save.player.pitch)
    placePlayer(w, player, save.player.x, save.player.y, save.player.z)
    target = null
    miningProgress = 0
    miningKey = ''
    bedrockWarned = false
    bobPhase = 0
    saveTimer = 0
    hudTimer = 0
    hud.buildHotbar()
    hud.sound(isMuted())
    screen = 'game'
    gameEl.hidden = false
    loadingEl.hidden = true
    renderer.setQuality(quality)
    renderer.resize()
    hud.refresh({ time: dayTime, x: player.x, y: player.y, z: player.z, target, inv, hot })
    paused = false
    input.enabled = true
    lastFrame = performance.now()
    render()
    startLoop()
    WebApp.requestFullscreen().catch(() => undefined)
    WebApp.lockOrientation().catch(() => undefined)
    WebApp.BackButton.show()
    if (prebuilt) {
      // 新世界:马上把种子和位置写进存档,不然关掉就丢了
      commitNow()
      void slot.flush()
    }
    hud.announce(`进入世界,种子 ${seedText(currentSeed)}`)
  } catch (err) {
    loadingEl.hidden = true
    menuEl.hidden = false
    gameEl.hidden = true
    screen = 'menu'
    world = null
    renderMenu()
    throw err
  } finally {
    entering = false
  }
}

function pauseGame(): void {
  if (screen !== 'game' || paused || !world) return
  paused = true
  input.enabled = false
  input.releaseAll()
  input.exitLock()
  miningProgress = 0
  miningKey = ''
  hud.mine(0)
  commitNow()
  void slot.flush()
  render()
  pausePanel(overlay, pauseApp)
}

function resumeGame(): void {
  if (screen !== 'game' || !paused) return
  overlay.hide()
  paused = false
  input.enabled = true
  lastFrame = performance.now()
  render()
}

function respawnPlayer(): void {
  const w = world
  if (!w) return
  placePlayer(w, player, w.spawn.x, w.spawn.y, w.spawn.z)
  player.yaw = w.yaw
  player.pitch = 0
  sfx('respawn')
  hud.announce('掉出世界了,回到出生点')
  commitNow()
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
  const dt = Math.min(0.05, Math.max(0, raw / 1000))
  lastFrame = now
  if (screen !== 'game' || !world || paused) return
  update(dt)
  render()
  // 自适应画质:每 90 帧看一次平均帧时间,跟不上就降内部渲染分辨率
  if (raw > 0 && raw < 250) frameMsSum += raw
  frameSamples++
  if (frameSamples >= 90) {
    const avg = frameMsSum / frameSamples
    if (avg > 24 && quality > 0.5) {
      quality = Math.max(0.5, quality - 0.15)
      renderer.setQuality(quality)
    } else if (avg < 13 && quality < 1) {
      quality = Math.min(1, quality + 0.1)
      renderer.setQuality(quality)
    }
    frameSamples = 0
    frameMsSum = 0
  }
}

function update(dt: number): void {
  const w = world
  if (!w) return
  dayTime = wrapTime(dayTime + dt / DAY_LENGTH)

  // 视角:鼠标/触屏的增量 + 方向键
  const look = input.consumeLook()
  player.yaw += look.x
  player.pitch = clampPitch(player.pitch - look.y)
  const keys = input.lookKeys
  if (keys.x || keys.y) {
    player.yaw += keys.x * 1.9 * dt
    player.pitch = clampPitch(player.pitch + keys.y * 1.35 * dt)
  }
  const tau = Math.PI * 2
  player.yaw = ((player.yaw % tau) + tau) % tau

  const wasInWater = player.inWater
  const res = stepPlayer(w, player, {
    forward: input.forwardAxis,
    strafe: input.strafeAxis,
    jump: input.jump,
  }, dt)
  if (res.jumped && !player.inWater) sfx('jump', 0.8)
  if (res.landed && !player.inWater) sfx('land', 0.7)
  if (!wasInWater && player.inWater) sfx('splash', 0.8)
  if (res.fellOut) respawnPlayer()

  const moving = Math.hypot(player.vx, player.vz) > 0.8
  if (moving && player.onGround && !reduced()) bobPhase += dt * 8.5
  else if (!moving) bobPhase *= Math.max(0, 1 - dt * 8)

  const eye = cameraEye(player)
  target = rayFromEye(w, eye.x, eye.y, eye.z, player.yaw, player.pitch, REACH)
  updateMining(dt)
  if (input.consumePlace()) tryPlace()

  saveTimer += dt
  if (saveTimer >= SAVE_EVERY) {
    saveTimer = 0
    commitNow()
  }
  hudTimer += dt
  if (hudTimer >= 0.12) {
    hudTimer = 0
    hud.refresh({ time: dayTime, x: player.x, y: player.y, z: player.z, target, inv, hot })
  }
}

function render(): void {
  if (!world) return
  renderer.resize()
  const eye = cameraEye(player)
  const moving = Math.hypot(player.vx, player.vz) > 0.8
  const bob = !reduced() && moving && player.onGround ? Math.sin(bobPhase) * 0.045 : 0
  const cam: Camera = { x: eye.x, y: eye.y + bob, z: eye.z, yaw: player.yaw, pitch: player.pitch }
  renderer.render(world, { cam, time: dayTime, target, mining: miningProgress })
}

// ---------------------------------------------------------------- 挖 / 放

function targetKey(hit: RayHit): string {
  return `${hit.x},${hit.y},${hit.z}`
}

function updateMining(dt: number): void {
  const w = world
  if (!w) return
  if (!input.mining || !target) {
    if (miningProgress !== 0) {
      miningProgress = 0
      miningKey = ''
      hud.mine(0)
    }
    return
  }
  const key = targetKey(target)
  if (key !== miningKey) {
    miningKey = key
    miningProgress = 0
  }
  const total = breakTime(target.block, player.inWater)
  if (!Number.isFinite(total)) {
    if (!bedrockWarned) {
      bedrockWarned = true
      sfx('deny')
      hud.toast('基岩挖不动:世界最底下两层是基岩')
      hud.announce('基岩挖不动')
    }
    return
  }
  miningProgress += dt / total
  mineTick -= dt
  if (mineTick <= 0) {
    mineTick = 0.2
    sfx('mine', 0.5)
  }
  if (miningProgress >= 1) {
    miningProgress = 0
    miningKey = ''
    breakBlock(target)
  }
  hud.mine(miningProgress)
}

function breakBlock(hit: RayHit): void {
  const w = world
  if (!w) return
  const result = w.setBlock(hit.x, hit.y, hit.z, AIR)
  if (result === 'ok') {
    editsDirty = true
    mined++
    addBlock(inv, hit.block)
    sfx('break')
    hud.announce(`挖掉了${blockName(hit.block)}`)
    commitNow()
    hud.counts(inv)
    target = null
    } else if (result === 'full') {
    sfx('full')
    hud.toast(`改动已经到 ${MAX_EDITS} 格上限:把方块改回去,或者开一个新世界`)
    hud.announce('改动到上限了')
  } else if (result === 'bedrock') {
    sfx('deny')
  }
}

/** 放方块要检查的格子会不会卡住玩家自己 */
function intersectsPlayer(x: number, y: number, z: number): boolean {
  const minX = player.x - 0.3
  const maxX = player.x + 0.3
  const minY = player.y
  const maxY = player.y + 1.8
  const minZ = player.z - 0.3
  const maxZ = player.z + 0.3
  return x + 1 > minX + 1e-4 && x < maxX - 1e-4 && y + 1 > minY + 1e-4 && y < maxY - 1e-4
    && z + 1 > minZ + 1e-4 && z < maxZ - 1e-4
}

function tryPlace(): void {
  const w = world
  if (!w || !target) return
  const pos = placePosition(target)
  if (pos.y <= 1 || pos.y >= 48 || pos.x < 0 || pos.x >= 128 || pos.z < 0 || pos.z >= 128) {
    sfx('deny')
    return
  }
  const blockId = HOTBAR[hot]
  if (inv[hot] <= 0) {
    sfx('deny')
    hud.toast(`没有${blockName(blockId)}了:先去挖一点`)
    hud.announce(`没有${blockName(blockId)}了`)
    return
  }
  const existing = w.blockAt(pos.x, pos.y, pos.z)
  if (existing !== AIR && existing !== WATER) {
    sfx('deny')
    return
  }
  if (intersectsPlayer(pos.x, pos.y, pos.z)) {
    sfx('deny')
    hud.toast('这里放不下:会卡住自己')
    return
  }
  const result = w.setBlock(pos.x, pos.y, pos.z, blockId)
  if (result === 'ok') {
    editsDirty = true
    placed++
    if (takeBlock(inv, hot)) hud.counts(inv)
    sfx('place')
    hud.announce(`放了${blockName(blockId)}`)
    commitNow()
  } else if (result === 'full') {
    sfx('full')
    hud.toast(`改动已经到 ${MAX_EDITS} 格上限:把方块改回去,或者开一个新世界`)
  } else if (result === 'bedrock') {
    sfx('deny')
  }
}

// ---------------------------------------------------------------- HUD

function selectSlot(i: number): void {
  if (i < 0 || i >= HOTBAR.length || i === hot) return
  hot = i
  hud.selection(hot)
  audioUnlock()
  sfx('click', 0.5)
  hud.announce(blockName(HOTBAR[hot]))
}

function cycleSlot(dir: number): void {
  selectSlot((hot + (dir > 0 ? 1 : -1) + HOTBAR.length) % HOTBAR.length)
}

// ---------------------------------------------------------------- 宿主生命周期

hostGame(() => {
  if (screen === 'game') {
    if (!paused) pauseGame()
    commitNow()
    void slot.flush()
  }
  audioSuspend()
})

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') audioUnlock()
})

window.addEventListener('resize', () => {
  if (screen !== 'game') return
  renderer.resize()
  if (paused) render()
})

window.addEventListener('pointerdown', () => audioUnlock(), { once: true, capture: true })
window.addEventListener('keydown', () => audioUnlock(), { once: true, capture: true })

followTheme()
renderer = new Renderer(canvas)
input.attach(canvas, $('stick'), $('stick-knob'), {
  jump: $('btn-jump'),
  mine: $('btn-mine'),
  place: $('btn-place'),
}, {
  onHotbar: selectSlot,
  onCycle: cycleSlot,
  onPause: pauseGame,
})

const touch = matchMedia('(pointer: coarse)').matches || 'ontouchstart' in window
if (touch) {
  $('touch').hidden = false
  $('hud-hint').hidden = true
}

$('btn-pause').addEventListener('click', pauseGame)
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
if (slot.state) renderMenu() // 本机有存档:主菜单出现「继续游戏」
void slot.restoreCloud().then(() => {
  if (screen === 'menu') renderMenu()
})
let readied = false
const ready = (): void => {
  if (readied) return
  readied = true
  WebApp.ready().catch(() => undefined)
}
setTimeout(ready, 900)

// 开发时的测试钩子:浏览器冒烟脚本用它确认世界真的在跑(生产构建里这段会被去掉)
if (import.meta.env.DEV) {
  (window as unknown as Record<string, unknown>).__sandbox = {
    screen: () => screen,
    paused: () => paused,
    seed: () => currentSeed,
    player: () => ({ x: player.x, y: player.y, z: player.z, yaw: player.yaw, pitch: player.pitch }),
    edits: () => (world ? world.editCount : 0),
    target: () => target,
    /** 开发时把时间拨到指定的 0..1(截图检查昼夜光照用) */
    setTime(t: number) {
      dayTime = wrapTime(t)
      if (world) render()
    },
  }
}
