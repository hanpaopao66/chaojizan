// 瓜田防线的入口:存档(本机 + 超级赞云存储)、首页/对局的切换、循环、暂停、结算、宿主能力、主题、键盘。
// 规则在 engine.ts,画在 render.ts,界面零件在 hud.ts / menus.ts,声音在 audio.ts,输入在 input.ts。
import '../../shared/src/base.css'
import './style.css'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import { $, Overlay, WebApp, cacheKey, cloud, followTheme, hostGame, local, reduced } from '../../shared/src/ui'
import { towerDef } from './data'
import { ENDLESS, levelById } from './levels'
import { advance, command, newGame } from './engine'
import { loadGame, resultOf, saveGame } from './save'
import {
  bgm, play, resume as audioResume, setSound, sfxForEvents, soundOn, suspend as audioSuspend, unlock,
} from './audio'
import { Hud } from './hud'
import { FieldInput } from './input'
import { about, home, pause, result, showTutorial, type App, type ResultView } from './menus'
import { loadBest, markSeen, mergeBest, newProfile, recordResult, type Best } from './profile'
import { Renderer } from './render'
import type { GameEvent, GameState, LevelDef, TowerKind } from './types'

// ---------------------------------------------------------------- 存档

/** 云端 state 键:打到一半的那一局(没有就是 game: null) */
interface Match {
  v: 1
  game: GameState | null
}

function loadMatch(raw: unknown): Match | null {
  const m = raw as Match
  if (!m || typeof m !== 'object' || m.v !== 1) return null
  if (m.game === null || m.game === undefined) return { v: 1, game: null }
  const g = loadGame(m.game)
  return g ? { v: 1, game: g } : { v: 1, game: null }
}

const slot = new SaveSlot<Match, Best>({
  cacheKey: cacheKey('tower'), cloud, local,
  loadState: loadMatch,
  saveState: (m) => ({ v: 1, game: m.game ? saveGame(m.game) : null }),
  loadBest, mergeBest, emptyBest: newProfile(),
  // 局内每 1.5 秒记一次本机,云端最多 6 秒写一次;暂停、结算、切后台时立刻写
  delay: 1500, minGap: 6000,
})

// ---------------------------------------------------------------- 界面状态

const screen = $('screen')
const gameEl = $<HTMLElement>('game')
const wrap = $<HTMLElement>('field-wrap')
const canvas = $<HTMLCanvasElement>('field')
const overlay = new Overlay($('overlay'), () => { (document.activeElement as HTMLElement | null)?.blur() })
const renderer = new Renderer(canvas)
const hud = new Hud()
const input = new FieldInput(canvas, $('sites'), renderer, {
  onSlot: (s) => selectSlot(s),
  onTower: (t) => selectTower(t.id),
  onEmpty: () => clearSelection(),
})

let best: Best = newProfile()
let state: GameState | null = null
let level: LevelDef | null = null
let running = false
let resultShown = false
let dark = false
let raf = 0
let lastFrame = 0
let saveAt = 0
let motionReduced = reduced()
let selectedSlot = -1
let selectedTower = 0
let tutorialStep = 0
let announcedWave = 0
/** 关掉建造/塔面板后焦点回哪个建造位 */
let lastSlot = -1

function syncSize(): void {
  if (!level || gameEl.hidden) return
  renderer.resize(wrap.clientWidth, wrap.clientHeight, window.devicePixelRatio || 1)
  input.layout()
}

// ---------------------------------------------------------------- 首页 / 开局

function renderHome(): void {
  screen.hidden = false
  gameEl.hidden = true
  document.body.classList.remove('in-game')
  home(app, screen)
  screen.scrollTop = 0
  WebApp.BackButton.hide()
}

function startGame(id: number | 'endless', resumed?: GameState): void {
  overlay.hide()
  resultShown = false
  stopLoop()
  const lv = id === 'endless' ? ENDLESS : levelById(id)
  level = lv
  state = resumed ?? newGame(lv, freshSeed())
  if (!resumed) state.speed = best.speed
  void unlock()
  // 开始游戏时进全屏、锁竖屏(网页版没有这两个能力时静默失败)
  WebApp.requestFullscreen().catch(() => undefined)
  WebApp.lockOrientation().catch(() => undefined)
  screen.hidden = true
  gameEl.hidden = false
  document.body.classList.add('in-game')
  renderer.setScene(lv, lv.theme, dark)
  input.setLevel(lv)
  hud.reset()
  selectedSlot = -1
  selectedTower = 0
  announcedWave = state.wave
  tutorialStep = !resumed && id === 1 && showTutorial(best) ? 1 : 0
  if (!resumed) slot.change({ v: 1, game: state })
  bgm(lv.theme)
  const recommend = [...new Set(lv.recommend.filter((k) => lv.towers.includes(k)))].slice(0, 3)
    .map((k) => towerDef(k).name).join('、')
  if (recommend) hud.showBanner(`推荐:${recommend}`, 'good', 3600)
  hud.announce(id === 'endless'
    ? `无尽模式开始,守住西瓜。推荐先造:${recommend}`
    : `第 ${id} 关 ${lv.name} 开始。推荐先造:${recommend}`)
  WebApp.BackButton.show()
  syncSize()
  runLoop()
  window.setTimeout(syncSize, 120)
}

function runLoop(): void {
  if (running) return
  running = true
  lastFrame = 0
  raf = requestAnimationFrame(frame)
}

function stopLoop(): void {
  running = false
  if (raf) cancelAnimationFrame(raf)
  raf = 0
}

function frame(now: number): void {
  raf = 0
  if (!running || !state || !level) return
  raf = requestAnimationFrame(frame)
  const dt = lastFrame === 0 ? 0 : Math.min(0.05, Math.max(0, (now - lastFrame) / 1000))
  lastFrame = now
  if (!state.over) {
    const events = advance(state, dt)
    if (events.length) handleEvents(events)
  }
  if (state.over) {
    if (!resultShown) finish()
    return
  }
  renderer.draw(state, {
    now,
    dt,
    reduced: motionReduced,
    selectedSlot,
    selectedTower,
    highlightSlot: tutorialStep === 1 && level ? level.hintSlot : -1,
    hoverSlot: input.hover,
  })
  hud.update(state, level, tipText())
  input.sync(state, selectedTower)
  if (state.wave !== announcedWave) {
    announcedWave = state.wave
    canvas.setAttribute('aria-label',
      `第 ${state.wave} 波,西瓜 ${state.hp}/${state.maxHp} 点生命,金币 ${state.gold}`)
  }
  if (now - saveAt > 1500) {
    saveAt = now
    slot.change({ v: 1, game: state })
  }
}

/** 一局结束:更新档案、清掉进行中的存档、出结算页 */
function finish(): void {
  if (!state || !level || resultShown) return
  resultShown = true
  const resultData = resultOf(state)
  stopLoop()
  const recorded = recordResult(best, resultData)
  best = recorded.best
  slot.setBest(best)
  slot.change({ v: 1, game: null })
  void slot.flush()
  bgm(null)
  const next = resultData.won && resultData.levelId !== 'endless' && resultData.levelId < 12
    ? (resultData.levelId as number) + 1
    : null
  const view: ResultView = { ...resultData, next, unlocked: recorded.unlocked }
  hud.reset()
  hud.announce(resultData.won ? `通关!${resultData.stars} 星` : '大西瓜被咬坏了')
  result(app, view)
}

function handleEvents(events: GameEvent[]): void {
  if (!state) return
  sfxForEvents(events)
  renderer.fx(events, state)
  for (const e of events) {
    switch (e.e) {
      case 'wave':
        hud.showBanner(`第 ${e.wave} 波`, 'good', 1300)
        hud.announce(`第 ${e.wave} 波开始`)
        break
      case 'waveClear':
        hud.showBanner(`第 ${e.wave} 波清完 +${e.reward + e.marigold} 金币`, 'good', 1500)
        hud.announce(`第 ${e.wave} 波清完,获得 ${e.reward + e.marigold} 金币`)
        break
      case 'boss':
        hud.showBanner('巨虫来了!', 'bad', 2200)
        hud.announce('Boss 巨虫出现')
        WebApp.HapticFeedback.notificationOccurred('warning')
        break
      case 'leak':
        hud.announce(e.boss ? '巨虫咬了一口,大西瓜掉 5 点 HP' : '一只虫子咬到了大西瓜')
        WebApp.HapticFeedback.impactOccurred('medium')
        break
      case 'win':
        hud.showBanner('瓜田守住了!', 'good', 2400)
        WebApp.HapticFeedback.notificationOccurred('success')
        break
      case 'lose':
        hud.showBanner('大西瓜被咬坏了', 'bad', 2400)
        WebApp.HapticFeedback.notificationOccurred('error')
        break
      default:
        break
    }
  }
}

// ---------------------------------------------------------------- 玩家操作

function tipText(): string {
  if (tutorialStep === 1) return '点发光的木桩,放一座豆荚炮'
  if (tutorialStep === 2) return '点刚造好的塔,可以升级或卖出'
  return ''
}

function selectSlot(slotIndex: number): void {
  if (!state || !level || state.over) return
  const tower = state.towers.find((t) => t.slot === slotIndex)
  if (tower) {
    selectTower(tower.id)
    return
  }
  selectedSlot = slotIndex
  selectedTower = 0
  lastSlot = slotIndex
  hud.openBuild(slotIndex, level)
  play('tap', { vol: 0.6 })
}

function selectTower(id: number): void {
  if (!state || !level) return
  const tower = state.towers.find((t) => t.id === id)
  if (!tower) return
  selectedSlot = -1
  selectedTower = id
  lastSlot = tower.slot
  hud.openTower(tower, level)
  play('tap', { vol: 0.5 })
}

function clearSelection(): void {
  const hadSheet = hud.sheetOpen
  selectedSlot = -1
  selectedTower = 0
  hud.closeSheets()
  // 用键盘打开面板再关掉时,焦点回到原来那个建造位,不要飘到页面顶部
  if (hadSheet && lastSlot >= 0) input.focusSlot(lastSlot)
}

/** 执行一条命令:失败给原因,成功播事件、写一次本机存档 */
function act(fn: (events: GameEvent[]) => { ok: boolean; reason?: string }, after?: () => void): void {
  if (!state) return
  const events: GameEvent[] = []
  const r = fn(events)
  if (!r.ok) {
    play('error')
    hud.toast(r.reason || '现在不能这么做')
    hud.announce(r.reason || '操作失败')
    return
  }
  if (events.length) handleEvents(events)
  slot.change({ v: 1, game: state })
  after?.()
}

function performBuild(slotIndex: number, kind: TowerKind): void {
  if (!state) return
  const before = state.towers.length
  act((events) => command(state as GameState, { kind: 'build', slot: slotIndex, tower: kind }, events), () => {
    if (!state || state.towers.length <= before) return
    clearSelection()
    if (tutorialStep === 1) {
      tutorialStep = 2
      best = markSeen(best, 'build')
      slot.setBest(best)
      hud.announce('豆荚炮造好了。点它就能升级或卖出')
    }
  })
}

function toggleSpeed(): void {
  if (!state) return
  const speed: 1 | 2 = state.speed === 2 ? 1 : 2
  command(state, { kind: 'speed', speed })
  best = { ...best, speed }
  slot.setBest(best)
  play('tap')
  hud.announce(speed === 2 ? '2 倍速' : '1 倍速')
}

hud.bind({
  onPause: () => openPause(),
  onSpeed: () => toggleSpeed(),
  onSummon: () => {
    act((events) => (state ? command(state, { kind: 'summon' }, events) : { ok: false }),
      () => hud.announce('提前召唤下一波,奖励 5 金币'))
  },
  onBuild: (slotIndex, kind) => performBuild(slotIndex, kind),
  onUpgrade: (tower) => {
    act((events) => (state ? command(state, { kind: 'upgrade', id: tower.id }, events) : { ok: false }), () => {
      if (!state || !level) return
      const t = state.towers.find((x) => x.id === tower.id)
      if (t) hud.openTower(t, level)
      if (tutorialStep === 1) tutorialStep = 0
    })
  },
  onSell: (tower) => {
    act((events) => (state ? command(state, { kind: 'sell', id: tower.id }, events) : { ok: false }),
      () => {
        clearSelection()
        if (tutorialStep === 2) tutorialStep = 0
      })
  },
  onCloseSheet: () => clearSelection(),
})

// ---------------------------------------------------------------- 暂停 / 回首页 / 继续

function persistNow(): void {
  if (state && !state.over) slot.change({ v: 1, game: state })
  void slot.flush()
}

function openPause(): void {
  if (!state || !running || state.over || overlay.open) return
  stopLoop()
  audioSuspend()
  persistNow()
  pause(app)
}

function resumeGame(): void {
  if (!state || !level) return
  overlay.hide()
  void unlock()
  audioResume()
  bgm(level.theme)
  runLoop()
}

function goHome(): void {
  if (state && !state.over) {
    slot.change({ v: 1, game: state })
    if (state.endless && state.wave > best.endlessBest) {
      best = { ...best, endlessBest: state.wave }
      slot.setBest(best)
    }
    void slot.flush()
  }
  stopLoop()
  bgm(null)
  state = null
  level = null
  resultShown = false
  renderHome()
}

function restart(): void {
  if (!state) return
  const id = state.levelId
  startGame(id)
}

function nextLevel(): number {
  for (let id = 1; id <= 12; id++) {
    if (!best.stars[String(id)]) return id
  }
  return 12
}

function continueGame(): void {
  const saved = slot.state?.game
  if (saved && !saved.over) {
    startGame(saved.levelId, saved)
    return
  }
  startGame(nextLevel())
}

function saveSummary(): string {
  const saved = slot.state?.game
  if (!saved) return ''
  const lv = saved.levelId === 'endless' ? '无尽瓜田' : `第 ${saved.levelId} 关`
  return `${lv} · 第 ${Math.max(1, saved.wave)} 波 · 西瓜 ${saved.hp}/${saved.maxHp}`
}

// ---------------------------------------------------------------- App(menus 用)

const app: App = {
  best: () => best,
  overlay,
  goHome,
  startLevel: (id) => startGame(id),
  startEndless: () => startGame('endless'),
  continueGame,
  resume: resumeGame,
  restart,
  hasSave: () => !!(slot.state?.game && !slot.state.game.over),
  saveSummary,
  soundOn,
  toggleSound: () => {
    const on = !soundOn()
    setSound(on)
    best = { ...best, sound: on }
    slot.setBest(best)
    if (on) void unlock()
    return on
  },
  currentLevel: () => (state ? state.levelId : null),
}

// ---------------------------------------------------------------- 键盘

window.addEventListener('keydown', (e) => {
  if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return
  if (e.code === 'Escape') {
    if (overlay.open) return
    if (state && running) {
      e.preventDefault()
      if (hud.sheetOpen) clearSelection()
      else openPause()
    }
    return
  }
  if (!state || !running || state.over || overlay.open) return
  if (e.code === 'Space' || e.code === 'KeyP') {
    e.preventDefault()
    openPause()
  } else if (e.code === 'Digit1' || e.code === 'Digit2') {
    const want = e.code === 'Digit2' ? 2 : 1
    if (state.speed !== want) toggleSpeed()
  }
})

// ---------------------------------------------------------------- 宿主 / 主题 / 启动

// 第一次点击或按键之后才出声(浏览器的规定)
window.addEventListener('pointerdown', () => { void unlock() }, { once: true, capture: true })
window.addEventListener('keydown', () => { void unlock() }, { once: true, capture: true })

followTheme(() => {
  dark = document.documentElement.classList.contains('dark')
  if (level && !gameEl.hidden) {
    renderer.setScene(level, level.theme, dark)
    renderer.clearFx()
  }
})

WebApp.SettingsButton.show().onClick(() => {
  if (state && running) openPause()
  else about(app, () => renderHome())
})
WebApp.BackButton.onClick(() => {
  if (overlay.open) {
    overlay.hide()
    if (resultShown) {
      resultShown = false
      goHome()
    } else if (state && !state.over && !running) {
      resumeGame()
    }
    return
  }
  // 局内:先关建造/塔面板,再暂停;首页的返回交给宿主
  if (hud.sheetOpen) {
    clearSelection()
    return
  }
  if (state && running) openPause()
})
hostGame(() => {
  if (state && running) {
    stopLoop()
    audioSuspend()
    persistNow()
    if (!overlay.open && !state.over) pause(app)
  }
  audioSuspend()
  persistNow()
})
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') audioResume()
})

window.addEventListener('resize', syncSize)
const motionMq = window.matchMedia('(prefers-reduced-motion: reduce)')
const onMotion = (): void => { motionReduced = motionMq.matches }
if (motionMq.addEventListener) motionMq.addEventListener('change', onMotion)
else motionMq.addListener(onMotion)
if (typeof ResizeObserver !== 'undefined') {
  new ResizeObserver(() => syncSize()).observe(wrap)
}

// 本机缓存先读(秒开),再和云端对账
slot.restoreLocal()
best = slot.best
setSound(best.sound)
renderHome()

let readied = false
const ready = (): void => {
  if (readied) return
  readied = true
  WebApp.ready().catch(() => undefined)
}
window.setTimeout(ready, 1500)
slot.restoreCloud().then((r) => {
  best = slot.best
  setSound(best.sound)
  if (!state) renderHome()
  if (r === 'cloud' && slot.state?.game && !slot.state.game.over) {
    hud.toast('云端有一局还没打完,点「继续游戏」接着守')
  }
}).catch(() => undefined).finally(ready)

// 只在开发服务器上有的调试钩子(浏览器里自动跑一局用);生产构建里 import.meta.env.DEV 是 false,整段会被去掉
if (import.meta.env.DEV) {
  ;(window as unknown as Record<string, unknown>).__tower = {
    state: () => state,
    best: () => best,
    startLevel: (id: number | 'endless') => startGame(id),
    goHome,
    speed: () => toggleSpeed(),
    /** 开发服务器上的测试用:直接发一条引擎命令 / 快进模拟(生产构建里没有这段) */
    command: (cmd: Parameters<typeof command>[1]) => (state ? command(state, cmd) : { ok: false }),
    advance: (dt: number) => (state ? advance(state, dt).length : 0),
    flush: () => slot.flush(),
    slotOpen: () => overlay.open,
  }
}
