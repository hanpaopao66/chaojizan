// 萌兽三路的入口:存档、界面切换、开一局 / 打完结算、宿主能力。
// 规则在 battle.ts / ai.ts,成长在 progress.ts,画在 render.ts,菜单在 menus.ts,对局界面在 play.ts。
import '../../shared/src/base.css'
import './style.css'
import { loadBattleArt, loadUnits } from './assets'
import { play as sfx, resume as audioResume, suspend as audioSuspend, unlock } from './audio'
import { forfeit, loadBattle, newBattle, saveBattle, starsOf } from './battle'
import { AI_HARD, LEVELS, LEVEL_BY_ID } from './data'
import { Battle } from './field'
import {
  App, Screen, about, achievements, campaign, cardSheet, cards, daily, dayKey, home, resetSwap, result,
} from './menus'
import { Play } from './play'
import {
  Profile, applyResult, claimAchievements, dailyChallenge, isFuture, levelConfig, loadProfile, markSeen, mergeProfile,
  newProfile, setDeck, upgrade, useDeck,
} from './progress'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import {
  $, Overlay, WebApp, button, cacheKey, cloud, confirmBox, el, followTheme, hostGame, local, row,
} from '../../shared/src/ui'

// ---------------------------------------------------------------- 存档

/** 云端 state 键:打到一半的那一局(没有就是 null) */
interface Match { v: 1; battle: Battle | null }

function loadMatch(raw: unknown): Match | null {
  const r = raw as Match
  if (!r || typeof r !== 'object' || r.v !== 1) return null
  if (r.battle === null) return { v: 1, battle: null }
  const b = loadBattle(r.battle)
  return b ? { v: 1, battle: b } : { v: 1, battle: null }
}

const slot = new SaveSlot<Match, Profile>({
  cacheKey: cacheKey('critters'), cloud, local,
  loadState: loadMatch, saveState: (m) => ({ v: 1, battle: m.battle ? saveBattle(m.battle) : null }),
  loadBest: loadProfile, mergeBest: mergeProfile, emptyBest: newProfile(),
  // 对局里每 3 秒记一次,云端最多 8 秒写一次;结算、暂停、切走时立刻写
  delay: 1500, minGap: 8000,
})

/** 这台设备的编号(金币按设备分格记,两台设备合并存档时不会多算也不会丢,见 progress.ts) */
function deviceId(): string {
  try {
    let id = window.localStorage.getItem('critters:device')
    if (!id || !/^[a-z0-9]{8}$/.test(id)) {
      id = Array.from({ length: 8 }, () => 'abcdefghijklmnopqrstuvwxyz0123456789'[Math.floor(Math.random() * 36)]).join('')
      window.localStorage.setItem('critters:device', id)
    }
    return id
  } catch (_) {
    return 'x' // 本机存储用不了:所有这类会话共用一格
  }
}

const device = deviceId()
let profile: Profile = newProfile()
let screen: Screen = 'home'
let screenArg = 1
const menuRoot = $('screen')
const overlay = new Overlay($('overlay'), () => undefined)
let dark = false
let current: { tag: string; name: string } | null = null

const toastEl = $('toast')
function toast(text: string): void {
  toastEl.textContent = text
  toastEl.hidden = false
  toastEl.classList.remove('show')
  void toastEl.offsetWidth
  toastEl.classList.add('show')
  window.clearTimeout(Number(toastEl.dataset.t || 0))
  toastEl.dataset.t = String(window.setTimeout(() => { toastEl.hidden = true }, 2600))
}

const app: App = {
  profile: () => profile,
  commit(p) {
    if (isFuture(profile)) return
    profile = p
    slot.setBest(p)
    render()
  },
  go(s, arg) {
    if (s !== 'cards') resetSwap()
    screen = s
    if (arg !== undefined) screenArg = arg
    sfx('tap', { vol: 0.5 })
    render()
    menuRoot.scrollTop = 0
  },
  startLevel: (id) => { void startLevel(id) },
  startDaily: () => { void startDaily() },
  upgradeCard(id) {
    const next = upgrade(profile, id)
    if (next === profile) return
    const { profile: p2, got } = claimAchievements(next)
    app.commit(p2)
    sfx('upgrade', { vol: 0.7 })
    WebApp.HapticFeedback.notificationOccurred('success')
    void slot.flush()
    overlay.hide()
    cardSheet(app, id)
    if (got.length) toast(`达成成就:${got.length} 个`)
  },
  setDeck(i, list) {
    app.commit(setDeck(profile, i, list, Date.now()))
  },
  useDeck(i) {
    app.commit(useDeck(profile, i, Date.now()))
  },
  overlay,
  now: () => Date.now(),
  toast,
  get frozen() {
    return isFuture(profile)
  },
}

function render(): void {
  if (playCtl.active) return
  menuRoot.textContent = ''
  menuRoot.hidden = false
  if (screen === 'home') home(app, menuRoot)
  else if (screen === 'campaign') campaign(app, menuRoot, screenArg)
  else if (screen === 'cards') cards(app, menuRoot)
  else if (screen === 'ach') achievements(app, menuRoot)
  else if (screen === 'daily') daily(app, menuRoot)
  // 安卓的返回手势:子页面先回主菜单,不直接关掉小程序
  if (screen === 'home') WebApp.BackButton.hide()
  else WebApp.BackButton.show()
  if (isFuture(profile)) {
    menuRoot.prepend(el('p', '这份存档是新版本的萌兽三路写的,这里只能看、不能改。关掉小程序再打开就会更新到新版本。', 'notice'))
  }
}

// ---------------------------------------------------------------- 对局

const playCtl = new Play({
  onEnd: (b) => finishBattle(b),
  onSnapshot: (b) => {
    if (!b.over) slot.change({ v: 1, battle: b })
  },
  onPauseMenu: () => pauseMenu(),
})

async function enterBattle(b: Battle, name: string, resumed: boolean): Promise<void> {
  overlay.hide()
  try {
    await loadBattleArt()
  } catch (_) {
    toast('图片没加载出来,检查一下网络再试')
    return
  }
  current = { tag: b.cfg.tag, name }
  menuRoot.hidden = true
  const hint = b.cfg.tag === '1-1' && profile.seen.indexOf('drag') < 0
  playCtl.start(b, { name, resumed, hint, dark })
  if (hint) app.commit(markSeen(profile, 'drag'))
  if (resumed) resumeMenu()
  else slot.change({ v: 1, battle: b })
}

async function startLevel(id: string): Promise<void> {
  const L = LEVEL_BY_ID[id]
  if (!L) return
  void unlock()
  await enterBattle(newBattle(levelConfig(profile, L, freshSeed())), `${L.id} ${L.name}`, false)
}

async function startDaily(): Promise<void> {
  void unlock()
  const d = dailyChallenge(dayKey(Date.now()))
  await enterBattle(newBattle(d.cfg), `每日挑战 · ${d.name}`, false)
}

function leaveBattle(): void {
  playCtl.stop()
  current = null
  render()
}

function nameOf(tag: string): string {
  if (tag.startsWith('daily:')) return `每日挑战 · ${dailyChallenge(tag.slice(6)).name}`
  const L = LEVEL_BY_ID[tag]
  return L ? `${L.id} ${L.name}` : tag
}

function finishBattle(b: Battle): void {
  const over = b.over
  if (!over) return
  const lanes = 3 - b.cfg.closed.length
  const res = {
    tag: b.cfg.tag, won: over.winner === 0, stars: starsOf(b), kills: b.stats[0].kills, refund: b.stats[0].refund,
    towers: b.stats[0].towers, base: b.stats[0].base, lost: b.stats[0].lost, allLanes: lanes === 3 && b.stats[0].towers >= 3,
  }
  const { profile: p2, reward } = applyResult(profile, res, device)
  if (!isFuture(profile)) {
    profile = p2
    slot.setBest(p2)
  }
  slot.change({ v: 1, battle: null })
  void slot.flush()
  const tag = b.cfg.tag
  const L = LEVEL_BY_ID[tag]
  const idx = L ? LEVELS.indexOf(L) : -1
  const nextL = idx >= 0 && over.winner === 0 && idx + 1 < LEVELS.length ? LEVELS[idx + 1] : null
  result(app, b, reward, {
    back: () => {
      overlay.hide()
      if (L) {
        screen = 'campaign'
        screenArg = L.chapter
      } else screen = tag.startsWith('daily:') ? 'daily' : 'home'
      leaveBattle()
    },
    retry: () => {
      overlay.hide()
      playCtl.stop()
      if (tag.startsWith('daily:')) void startDaily()
      else void startLevel(tag)
    },
    next: nextL ? () => {
      overlay.hide()
      playCtl.stop()
      screen = 'campaign'
      screenArg = nextL.chapter
      void startLevel(nextL.id)
    } : undefined,
  })
}

function pauseMenu(): void {
  if (!playCtl.battle || playCtl.phase === 'ending') return
  playCtl.pause()
  void slot.flush()
  const b = playCtl.battle
  overlay.show((p) => {
    p.append(el('h2', '已暂停'), el('p', current ? current.name : ''))
    p.append(row(button('继续', () => {
      overlay.hide()
      playCtl.resume()
    }, 'primary')))
    p.append(row(
      button('重新开始', () => {
        void (async () => {
          if (!(await confirmBox('这一局从头来过?'))) return
          overlay.hide()
          playCtl.stop()
          if (b.cfg.tag.startsWith('daily:')) void startDaily()
          else void startLevel(b.cfg.tag)
        })()
      }),
      button('认输', () => {
        void (async () => {
          if (!(await confirmBox('认输这一局?算输,不扣任何东西。'))) return
          overlay.hide()
          const f = forfeit(playCtl.battle || b)
          playCtl.pause()
          finishBattle(f)
        })()
      }),
    ))
  }, { cls: 'pause', onDismiss: () => playCtl.resume() })
}

/** 打开时有一局没打完:先停在战场上,问一句 */
function resumeMenu(): void {
  overlay.show((p) => {
    p.append(el('h2', '上一局还没打完'), el('p', current ? current.name : ''),
      el('p', '接着打会从关掉时的那一刻继续。'))
    p.append(row(
      button('认输', () => {
        const b = playCtl.battle
        if (!b) return
        overlay.hide()
        finishBattle(forfeit(b))
      }),
      button('接着打', () => {
        overlay.hide()
        void unlock()
        playCtl.resume()
      }, 'primary'),
    ))
  }, { cls: 'pause' })
}

// ---------------------------------------------------------------- 宿主、主题、启动

function applyTheme(): void {
  dark = document.documentElement.classList.contains('dark')
  playCtl.setDark(dark)
}

// 第一次点击或按键之后才出声(浏览器的规定)
window.addEventListener('pointerdown', () => { void unlock() }, { once: true, capture: true })
window.addEventListener('keydown', () => { void unlock() }, { once: true, capture: true })

followTheme(applyTheme)
WebApp.SettingsButton.show().onClick(() => {
  if (playCtl.active && playCtl.phase !== 'paused') pauseMenu()
  else about(app)
})
WebApp.BackButton.onClick(() => {
  if (overlay.open) {
    overlay.hide()
    if (playCtl.phase === 'paused' && playCtl.battle && !playCtl.battle.over) playCtl.resume()
    return
  }
  if (playCtl.active) pauseMenu()
  else if (screen !== 'home') app.go('home')
})
hostGame(() => {
  if (playCtl.active) {
    const running = playCtl.phase === 'running' || playCtl.phase === 'countdown'
    playCtl.pause()
    if (running) pauseMenu()
  }
  audioSuspend()
  void slot.flush()
})
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') audioResume() })

void loadUnits().catch(() => undefined)
slot.restoreLocal()
profile = slot.best
const localBattle = slot.state?.battle || null
render()
if (localBattle && !localBattle.over) void enterBattle(localBattle, nameOf(localBattle.cfg.tag), true)

let readied = false
const ready = () => {
  if (readied) return
  readied = true
  WebApp.ready().catch(() => undefined)
}
setTimeout(ready, 1500)
slot.restoreCloud().then((r) => {
  profile = slot.best
  if (r === 'cloud' && slot.state?.battle && !slot.state.battle.over && !playCtl.active) {
    const b = slot.state.battle
    void enterBattle(b, nameOf(b.cfg.tag), true)
  } else if (r === 'cleared' && playCtl.active) {
    leaveBattle()
  }
  if (!playCtl.active) render()
}).finally(ready)

// 预先把对局要用的图下载好(不挡主菜单)
setTimeout(() => { void loadBattleArt().catch(() => undefined) }, 800)

// 只在开发服务器上有的测试钩子(浏览器里自动跑一局用):生产构建里 import.meta.env.DEV 是 false,整段被去掉
if (import.meta.env.DEV) {
  (window as unknown as Record<string, unknown>).__critters = {
    play: playCtl,
    profile: () => profile,
    /** 让电脑替玩家下(测试用,不走界面) */
    autoplay() {
      const b = playCtl.battle
      if (!b) return
      playCtl.battle = { ...b, cfg: { ...b.cfg, ai: [AI_HARD, b.cfg.ai[1]] }, ai: [{ next: b.t, alarm: [-1, -1, -1], lane: 1 }, b.ai[1]] }
    },
  }
}
