// 星火牌局的入口:存档(本机 + 超级赞云存储)、首页 / 卡牌图鉴 / 对局 / 结算的切换、暂停菜单、
// 新手提示、成就解锁、宿主能力、主题、音效解锁。
//
// 存档两类:
// - state:打到一半的那一局(整份对局状态 + 难度),每一步都存;关了再开、换设备能接着打;
// - best:战绩 / 成就累计数 / 已解锁成就 / 上次选的卡组和难度。
// 规则在 engine.ts / ai.ts(纯函数),界面在 table.ts / view.ts / menus.ts,这里只做串起来。
import '../../shared/src/base.css'
import './style.css'
import './table.css'
import { HEROES, hero } from './data'
import { loadGame, newGame, saveGame } from './engine'
import {
  loadProfile, markTutorialSeen, mergeProfile, newProfile, recordResult, rememberChoice, withAchievements,
  type Outcome, type Profile,
} from './profile'
import { newlyUnlocked } from './achievements'
import { about, gallery, home, result, type App, type Choice, type ResultView, type Screen } from './menus'
import { Table, type MatchResult } from './table'
import { freshSeed } from '../../shared/src/rand'
import { SaveSlot } from '../../shared/src/save'
import {
  $, Overlay, WebApp, button, cacheKey, cloud, confirmBox, el, followTheme, hostGame, local, row,
} from '../../shared/src/ui'
import { play as sfx, resume as audioResume, setSound, soundOn, suspend as audioSuspend, unlock } from './audio'
import type { GameState, Level } from './types'

// ---------------------------------------------------------------- 存档

/** 云端 state 键:打到一半的那一局(没有就是 game: null),带上这局选的难度 */
interface Match {
  v: 1
  game: GameState | null
  level: Level
}

const LEVELS: Level[] = ['easy', 'normal', 'hard']

function loadMatch(raw: unknown): Match | null {
  const m = raw as Match
  if (!m || typeof m !== 'object' || m.v !== 1) return null
  const level = LEVELS.indexOf(m.level) >= 0 ? m.level : 'normal'
  if (m.game === null) return { v: 1, game: null, level }
  const g = loadGame(m.game)
  return { v: 1, game: g, level }
}

const slot = new SaveSlot<Match, Profile>({
  cacheKey: cacheKey('cards'), cloud, local,
  loadState: loadMatch,
  saveState: (m) => ({ v: 1, game: m.game ? saveGame(m.game) : null, level: m.level }),
  loadBest: loadProfile, mergeBest: mergeProfile, emptyBest: newProfile(),
  // 每一步都调 change(本机立刻写);云端合并成 2 秒内的改动一起写,最多 5 秒一次,免得用光云存储配额
  delay: 1200, minGap: 5000,
})

// ---------------------------------------------------------------- 界面状态

const menuRoot = $('screen')
const overlay = new Overlay($('overlay'), () => {
  const focus = document.activeElement as HTMLElement | null
  focus?.blur()
})

let profile: Profile = newProfile()
let choice: Choice = { hero: 'forge', level: 'normal' }
let screen: Screen = 'home'
/** 结算弹层开着:宿主返回键要回首页,而不是只把弹层藏起来(否则会卡在已结束的牌桌) */
let resultShown = false

const table = new Table({
  onEnd: (r) => finishMatch(r),
  onSnapshot: (game) => { slot.change({ v: 1, game, level: choice.level }) },
  onPause: () => pauseMenu(),
  onTutorialSeen: () => {
    profile = markTutorialSeen(profile)
    slot.setBest(profile)
    void slot.flush()
  },
})

const app: App = {
  profile: () => profile,
  choice: () => choice,
  hasSave: () => !!slot.state?.game && !slot.state.game.over,
  saveSummary,
  overlay,
  goHome: () => {
    resultShown = false
    overlay.hide()
    table.stop()
    screen = 'home'
    render()
  },
  goGallery: () => {
    if (table.active) return
    overlay.hide()
    screen = 'gallery'
    sfx('tap')
    render()
    menuRoot.scrollTop = 0
  },
  pickHero: (id) => {
    if (!HEROES.some((h) => h.id === id)) return
    choice = { ...choice, hero: id }
  },
  pickLevel: (level) => { choice = { ...choice, level } },
  start: () => {
    resultShown = false
    overlay.hide()
    void startMatch()
  },
  resume: () => {
    overlay.hide()
    resumeMatch()
  },
  discardSave: () => { void discardSave() },
}

function saveSummary(): string {
  const g = slot.state?.game
  if (!g) return ''
  const me = g.sides[0]
  const h = hero(me.hero)
  return `${h.title} · 第 ${g.turn} 回合 · 你 ${me.hp} 血 / 电脑 ${g.sides[1].hp} 血`
}

const toastEl = $('toast')
function toast(text: string): void {
  toastEl.textContent = text
  toastEl.hidden = false
  toastEl.classList.remove('show')
  void toastEl.offsetWidth
  toastEl.classList.add('show')
  window.clearTimeout(Number(toastEl.dataset.t || 0))
  toastEl.dataset.t = String(window.setTimeout(() => { toastEl.hidden = true }, 3000))
}

// ---------------------------------------------------------------- 页面 / 对局

function render(): void {
  if (table.active) return
  menuRoot.textContent = ''
  menuRoot.hidden = false
  if (screen === 'gallery') gallery(app, menuRoot)
  else home(app, menuRoot)
  if (screen === 'home') WebApp.BackButton.hide()
  else WebApp.BackButton.show()
}

async function startMatch(): Promise<void> {
  void unlock()
  // 开始对局时进全屏、锁竖屏(网页版没有这两个能力时会静默失败)
  WebApp.requestFullscreen().catch(() => undefined)
  WebApp.lockOrientation().catch(() => undefined)
  const seed = freshSeed()
  const playerHero = HEROES.find((h) => h.id === choice.hero) || HEROES[0]
  // 电脑从另外两套卡组里挑一套,按种子选,同一局可复现
  const others = HEROES.filter((h) => h.id !== playerHero.id)
  const aiHero = others[(seed >>> 8) % others.length]
  const level = LEVELS.indexOf(choice.level) >= 0 ? choice.level : 'normal'
  const game = newGame({ seed, hero0: playerHero.id, hero1: aiHero.id }).state
  profile = rememberChoice(profile, playerHero.id, level)
  slot.setBest(profile)
  choice = { hero: playerHero.id, level }
  menuRoot.hidden = true
  table.stop()
  table.start(game, level, false, { tutorial: !profile.tutorialSeen })
  slot.change({ v: 1, game, level })
  void slot.flush()
}

function resumeMatch(): void {
  const m = slot.state
  if (!m || !m.game || m.game.over) {
    toast('没有可以继续的对局')
    screen = 'home'
    render()
    return
  }
  void unlock()
  WebApp.requestFullscreen().catch(() => undefined)
  WebApp.lockOrientation().catch(() => undefined)
  choice = { hero: m.game.sides[0].hero, level: m.level }
  menuRoot.hidden = true
  table.stop()
  table.start(m.game, m.level, true)
}

async function discardSave(): Promise<void> {
  if (!(await confirmBox('放弃这一局?这一局的进度会清掉,不记输赢。'))) return
  table.stop()
  slot.change({ v: 1, game: null, level: choice.level })
  await slot.flush()
  screen = 'home'
  render()
}

/** 一局结束:记战绩/成就 → 弹结算(星级 + 统计 + 新成就) */
function finishMatch(r: MatchResult): void {
  const outcome: Outcome = {
    won: r.won, draw: r.draw, hero: r.hero, level: r.level, reason: r.reason,
    myHp: r.myHp, dealt: r.dealt, played: r.played,
  }
  profile = recordResult(profile, outcome)
  const unlocked = newlyUnlocked(profile)
  profile = withAchievements(profile, unlocked.map((a) => a.id))
  slot.setBest(profile)
  choice = { hero: r.hero, level: r.level }
  slot.change({ v: 1, game: null, level: r.level })
  void slot.flush()
  // 星级:赢局按剩余血量 1–3 颗星,平局 1 颗,输 0 颗(结算页展示用)
  const stars = r.won ? (r.myHp >= 20 ? 3 : r.myHp >= 10 ? 2 : 1) : r.draw ? 1 : 0
  const view: ResultView = {
    ...r, streak: profile.streak, bestStreak: profile.bestStreak, stars,
    unlocked: unlocked.map((a) => ({ name: a.name, badge: a.badge })),
  }
  resultShown = true
  result(app, view)
  if (unlocked.length > 0) toast(`解锁成就:${unlocked.map((a) => a.name).join('、')}`)
}

// ---------------------------------------------------------------- 暂停

function pauseMenu(): void {
  if (!table.active || overlay.open) return
  table.pause()
  void slot.flush()
  overlay.show((panel) => {
    panel.append(el('h2', '已暂停'), el('p', saveSummary() || '对局会自动存档'))
    panel.append(row(button('继续', () => {
      overlay.hide()
      table.resume()
    }, 'primary')))
    const soundBtn = button(soundOn() ? '关掉音效' : '打开音效', () => {
      setSound(!soundOn())
      soundBtn.textContent = soundOn() ? '关掉音效' : '打开音效'
      if (soundOn()) sfx('tap')
    })
    panel.append(row(
      soundBtn,
      button('玩法与关于', () => {
        overlay.hide()
        about(app, () => pauseMenu())
      }),
    ))
    panel.append(row(
      button('认输', () => {
        void (async () => {
          if (!(await confirmBox('认输这一局?算输,进度会清掉。'))) return
          overlay.hide()
          table.resume()
          table.surrender()
        })()
      }),
      button('回首页', () => {
        overlay.hide()
        table.stop()
        screen = 'home'
        render()
      }),
    ))
  }, { cls: 'pause', onDismiss: () => table.resume() })
}

// ---------------------------------------------------------------- 宿主、主题、启动

// 第一次点击或按键之后才出声(浏览器的规定)
window.addEventListener('pointerdown', () => { void unlock() }, { once: true, capture: true })
window.addEventListener('keydown', () => { void unlock() }, { once: true, capture: true })

followTheme()

WebApp.SettingsButton.show().onClick(() => {
  // 有任何弹层开着(结算 / 暂停 / 关于 / 图鉴详情 / 成就)就忽略设置键:
  // 尤其结算页,不能被「关于」盖掉之后再关掉,把玩家留在已结束的牌桌上。
  // 对局刚结束、结算页还没出来的那一小段也忽略,避免「关于」盖住即将弹出的结算。
  if (overlay.open || table.ending) return
  if (table.active) pauseMenu()
  else about(app)
})
WebApp.BackButton.onClick(() => {
  if (overlay.open) {
    // 结算页:返回 = 回首页(结算弹层的 onDismiss 也是回首页,这里走同一条路)
    if (resultShown) {
      app.goHome()
      return
    }
    overlay.hide()
    if (table.active) table.resume()
    return
  }
  if (table.ending) return // 结算页马上出来,等它接管返回键(再按一次就会回首页)
  if (table.active) pauseMenu()
  else if (screen !== 'home') app.goHome()
})
hostGame(() => {
  if (table.active) {
    table.pause()
    if (!overlay.open) pauseMenu()
  }
  audioSuspend()
  void slot.flush()
})
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') audioResume()
})

// 本机缓存先读(秒开),再和云端对账
slot.restoreLocal()
profile = slot.best
choice = { hero: profile.lastHero, level: profile.lastLevel }
render()

let readied = false
const ready = (): void => {
  if (readied) return
  readied = true
  WebApp.ready().catch(() => undefined)
}
setTimeout(ready, 1500)
slot.restoreCloud().then((r) => {
  profile = slot.best
  choice = { hero: profile.lastHero, level: profile.lastLevel }
  if (!table.active) render()
  if (r === 'cloud' && slot.state?.game && !slot.state.game.over) toast('云端有一局还没打完,点「继续对局」接着打')
  else if (r === 'cleared' && !table.active) render()
}).catch(() => undefined).finally(ready)
