// 首页(关卡地图 / 星星统计 / 无尽 / 成就 / 说明 / 关于)、暂停菜单、结算页。
// 全部用 DOM 真按钮;文案中文;关于页如实写清楚数据和边界。
import { button, el, row, Overlay } from '../../shared/src/ui'
import { ACHIEVEMENTS, THEMES, themeOf } from './data'
import { LEVELS, levelById, levelsOfTheme } from './levels'
import type { RunResult } from './save'
import {
  allCleared, endlessUnlocked, hasSeen, levelStars, levelUnlocked, nextLevelId, totalStars, type Best,
} from './profile'
import type { Theme } from './types'

export interface App {
  best: () => Best
  overlay: Overlay
  /** 回首页(收掉对局) */
  goHome: () => void
  startLevel: (id: number) => void
  startEndless: () => void
  /** 继续上一局 / 开下一关 */
  continueGame: () => void
  /** 从暂停里回来 */
  resume: () => void
  /** 重开这一关 */
  restart: () => void
  hasSave: () => boolean
  saveSummary: () => string
  soundOn: () => boolean
  toggleSound: () => boolean
  /** 当前这局是第几关(不在局内是 null) */
  currentLevel: () => number | 'endless' | null
}

let page: Theme = 'garden'

/** 首页 */
export function home(app: App, root: HTMLElement): void {
  const best = app.best()
  root.textContent = ''
  const wrap = el('div', '', 'home')
  const head = el('div', '', 'home-head')
  head.append(el('p', '单机塔防 · 原创 · 无广告', 'kicker'))
  const h1 = el('h1', '', 'logo')
  h1.append(document.createTextNode('瓜田'), el('em', '防线'))
  head.append(h1)
  head.append(el('p', '虫子沿着土路爬向田中央的大西瓜。在木桩上造塔、升级、卖塔,守住最后一波。', 'tagline'))
  wrap.append(head)

  // 进度
  const stars = totalStars(best)
  const stats = el('div', '', 'home-stats')
  const stat = (label: string, value: string): HTMLElement => {
    const s = el('div', '', 'hstat')
    s.append(el('b', value), el('span', label))
    return s
  }
  stats.append(
    stat('星星', `${stars}/${LEVELS.length * 3}`),
    stat('无尽最高', best.endlessBest > 0 ? `${best.endlessBest} 波` : '—'),
    stat('击杀', String(best.stats.kills)),
  )
  wrap.append(stats)

  // 开始 / 继续
  const startBox = el('div', '', 'start-box')
  const startBtn = button(app.hasSave() ? '继续游戏' : '开始游戏', () => app.continueGame(), 'primary start')
  startBtn.setAttribute('aria-label', app.hasSave() ? '继续上一局' : '开始游戏')
  startBox.append(startBtn)
  if (app.hasSave()) {
    startBox.append(el('p', `上次:${app.saveSummary()}`, 'save-note'))
  } else {
    const next = nextLevelId(best)
    startBox.append(el('p', allCleared(best) ? '全部关卡都通关了,去无尽模式试试?' : `下一站:第 ${next} 关「${levelById(next).name}」`, 'save-note'))
  }
  wrap.append(startBox)

  // 三页主题 + 关卡卡片
  const tabRow = el('div', '', 'seg tabs')
  tabRow.setAttribute('role', 'tablist')
  tabRow.setAttribute('aria-label', '关卡主题')
  for (const theme of THEMES) {
    const b = button(`${theme.name}`, () => {
      page = theme.id
      home(app, root)
    })
    b.setAttribute('role', 'tab')
    b.setAttribute('aria-pressed', String(page === theme.id))
    b.setAttribute('aria-selected', String(page === theme.id))
    tabRow.append(b)
  }
  wrap.append(tabRow)
  wrap.append(el('p', themeOf(page).tagline, 'page-line'))
  const grid = el('div', '', 'level-grid')
  for (const level of levelsOfTheme(page)) {
    const id = level.id as number
    const unlocked = levelUnlocked(best, id)
    const got = levelStars(best, id)
    const card = button('', () => app.startLevel(id), `level-card ${unlocked ? '' : 'locked'} ${got === 3 ? 'perfect' : ''}`)
    card.dataset.level = String(id)
    card.setAttribute('aria-label', `第 ${id} 关 ${level.name},${unlocked ? (got > 0 ? `已拿 ${got} 星` : '还没通关') : '未解锁'}`)
    if (!unlocked) card.disabled = true
    card.append(el('span', `第 ${id} 关`, 'lv-no'), el('b', level.name, 'lv-name'))
    if (unlocked) {
      const starText = got > 0 ? '★'.repeat(got) + '☆'.repeat(3 - got) : '未通关'
      card.append(el('span', starText, `lv-stars ${got === 3 ? 'full' : ''}`))
    } else {
      card.append(el('span', '通关上一关解锁', 'lv-stars'))
      card.append(el('span', '未解锁', 'lv-lock'))
    }
    grid.append(card)
  }
  wrap.append(grid)

  // 其他入口
  const extra = el('div', '', 'home-extra')
  const endBtn = button(
    endlessUnlocked(best) ? `无尽模式${best.endlessBest > 0 ? ` · 最高 ${best.endlessBest} 波` : ''}` : '无尽模式(通关第 12 关解锁)',
    () => app.startEndless(),
    'wide',
  )
  endBtn.disabled = !endlessUnlocked(best)
  const achBtn = button(`成就 ${best.achievements.length}/${ACHIEVEMENTS.length}`, () => achievements(app, () => home(app, root)), 'wide')
  extra.append(endBtn, achBtn)
  const extra2 = el('div', '', 'home-extra two')
  extra2.append(
    button('操作说明', () => controls(app, () => home(app, root)), 'wide'),
    button('关于', () => about(app, () => home(app, root)), 'wide'),
    button(app.soundOn() ? '声音:开' : '声音:关', () => {
      const on = app.toggleSound()
      const b = extra2.querySelector('button:last-child')
      if (b) b.textContent = on ? '声音:开' : '声音:关'
    }, 'wide'),
  )
  extra.append(el('div'), extra2)
  wrap.append(extra)
  wrap.append(el('p', '没有广告、没有内购、没有排行榜。玩法单机,不请求任何第三方服务;进度存在超级赞云存储里,关掉再开、换设备都能接着守。', 'fine'))
  root.append(wrap)
}

/** 关于:世界观、玩法边界、数据存哪、原创声明 */
export function about(app: App, back: () => void): void {
  app.overlay.show((panel) => {
    panel.append(el('h2', '关于瓜田防线'))
    panel.append(el('p', '单机塔防小游戏。虫子沿着固定土路爬向田中央的大西瓜,你在路边的木桩上造塔拦住它们;撑过全部波次就赢,西瓜被咬到 0 点就输。'))
    const ul = el('ul')
    for (const line of [
      '12 关三主题(菜园 / 果园 / 虫巢)+ 无尽模式;7 种塔 × 3 级、9 种虫(含护甲甲虫、飞行虫、治疗蛹、分裂蚁和 3 只巨虫 Boss)。',
      '一局 3–7 分钟;每波前 3 秒准备,可以点「提前召唤」拿 5 金币;支持 1 倍 / 2 倍速、暂停、静音。',
      '没有广告、没有内购、没有排行榜、没有签到和体力;玩法单机、不联网对战,进度同步走超级赞自带的云存储。',
      '美术全部用 Canvas 2D 程序化绘制,音效和 BGM 由 WebAudio 现场合成:没有外部图片、字体、音频,也不请求任何第三方服务。',
      '所有数值、塔、虫、关卡和界面都是为超级赞原创的;没有使用任何商业塔防游戏(包括《保卫萝卜》)的名字、角色、关卡、美术、数值、音效或界面。',
      '游戏里没有真实货币、抽奖、开箱和社交功能,也没有会让人一直想着回来的机制。',
    ]) ul.append(el('li', line))
    panel.append(ul)
    panel.append(el('h3', '数据存在哪'))
    const ul2 = el('ul')
    for (const line of [
      '打到一半的那一局和你的进度(每关星级、成就、无尽最高波数、累计击杀、声音开关)存在超级赞云存储里,按应用和你的账号隔离。',
      '官方(也就是这个游戏的开发者)不能从服务端读取你的数据;平台管理员在技术上能访问数据库,数据没有端到端加密。',
      '为了打开不用等网络,你的设备上也缓存一份;声音开关同时记在本机。',
      '可以在「我的 → 设置 → 小程序授权与数据」里导出或清空这些数据;注销账号时一并删除。',
      '不申请昵称、头像、定位、通讯录、摄像头、麦克风等任何其他信息。',
    ]) ul2.append(el('li', line))
    panel.append(ul2)
    panel.append(row(button('知道了', () => {
      app.overlay.hide()
      back()
    }, 'primary')))
  }, { cls: 'about', onDismiss: back })
}

/** 操作说明 */
export function controls(app: App, back: () => void): void {
  app.overlay.show((panel) => {
    panel.append(el('h2', '操作说明'))
    const ul = el('ul', '', 'keys')
    const item = (k: string, text: string): HTMLElement => {
      const li = el('li')
      li.append(el('span', k, 'kbd'), document.createTextNode(` ${text}`))
      return li
    }
    ul.append(
      item('点木桩', '弹出建造卡片,选一种塔放上去;金币不够的会灰掉并显示还差多少。'),
      item('点已建的塔', '显示射程圈和面板,可以升级(最多 3 级)或卖出(返还总投入的 70%)。'),
      item('提前召唤', '准备期点底部按钮,立刻开始下一波并奖励 5 金币。'),
      item('1× / 2×', '右上角切换倍速;暂停按钮随时暂停并自动存档。'),
      item('键盘', '空格暂停 / 继续,1 和 2 切倍速,Esc 关闭面板或暂停。'),
      item('切后台', '自动暂停并立刻存档;回来接着打。'),
    )
    panel.append(ul)
    panel.append(el('p', '目标:别让虫子走到大西瓜。每漏一只普通虫掉 1 点 HP,巨虫掉 5 点;HP 归零就输。', 'substat'))
    panel.append(el('p', '星级:全程满血通关 3 星;剩余 ≥60% 2 星;只要通关就有 1 星。', 'substat'))
    panel.append(row(button('知道了', () => {
      app.overlay.hide()
      back()
    }, 'primary')))
  }, { cls: 'about', onDismiss: back })
}

/** 成就列表 */
export function achievements(app: App, back: () => void): void {
  app.overlay.show((panel) => {
    const got = app.best().achievements
    const h = el('h2', `成就 ${got.length}/${ACHIEVEMENTS.length}`)
    panel.append(h)
    const ul = el('ul', '', 'ach-list')
    for (const a of ACHIEVEMENTS) {
      const li = el('li', '', got.includes(a.id) ? 'got' : '')
      li.append(el('b', got.includes(a.id) ? `✓ ${a.name}` : a.name))
      li.append(el('span', a.desc))
      ul.append(li)
    }
    panel.append(ul)
    panel.append(row(button('知道了', () => {
      app.overlay.hide()
      back()
    }, 'primary')))
  }, { cls: 'about', onDismiss: back })
}

export interface ResultView extends RunResult {
  /** 下一关 id(没有就是 null) */
  next: number | null
  /** 这一局新点亮的成就 id */
  unlocked: string[]
}

/** 结算页:胜负、星级、剩余血量、击杀、用时、再来一次 / 下一关 / 回首页 */
export function result(app: App, view: ResultView): void {
  const win = view.won
  app.overlay.show((panel) => {
    panel.append(el('h2', win ? '瓜田守住了' : '大西瓜被咬坏了'))
    const starsEl = el('div', '', 'result-stars')
    if (win) {
      for (let i = 0; i < 3; i++) starsEl.append(el('span', i < view.stars ? '★' : '☆', i < view.stars ? 'on' : ''))
    }
    panel.append(starsEl)
    panel.append(el('p', win
      ? (view.stars === 3 ? '满血通关,漂亮!' : `还剩 ${view.hp}/${view.maxHp} 点 HP`)
      : (view.levelId === 'endless' ? `无尽模式坚持到了第 ${view.endlessWave} 波` : `倒在第 ${view.waves} 波,再来一次吧。`), 'substat'))
    const grid = el('div', '', 'statgrid')
    const cell = (label: string, v: string): HTMLElement => {
      const d = el('div')
      d.append(el('b', v), el('small', label))
      return d
    }
    grid.append(
      cell('剩余西瓜 HP', `${view.hp}/${view.maxHp}`),
      cell('击杀', String(view.kills)),
      cell('用时', timeText(view.time)),
      cell('赚到金币', String(view.goldEarned)),
    )
    panel.append(grid)
    if (view.unlocked.length) {
      panel.append(el('p', `新成就:${view.unlocked.length} 个!去成就页看看。`, 'ach-note'))
    }
    if (view.levelId === 'endless' && view.endlessWave > 0) {
      panel.append(el('p', `无尽最高波数:${Math.max(app.best().endlessBest, view.endlessWave)} 波`, 'substat'))
    }
    panel.append(row(
      button('再来一次', () => {
        app.overlay.hide()
        app.restart()
      }),
      win && view.next !== null
        ? button('下一关', () => {
          app.overlay.hide()
          app.startLevel(view.next as number)
        }, 'primary')
        : button('回首页', () => {
          app.overlay.hide()
          app.goHome()
        }, 'primary'),
    ))
    if (win && view.next !== null) {
      panel.append(row(button('回首页', () => {
        app.overlay.hide()
        app.goHome()
      })))
    }
  }, { cls: win ? 'result-win' : 'result-lose', onDismiss: () => app.goHome() })
}

/** 暂停菜单 */
export function pause(app: App): void {
  const level = app.currentLevel()
  app.overlay.show((panel) => {
    panel.append(el('h2', '已暂停'))
    panel.append(el('p', level === 'endless' ? '无尽瓜田 · 进度已自动保存' : level ? `第 ${level} 关 · 进度已自动保存` : '进度已自动保存'))
    panel.append(row(button('继续', () => {
      app.overlay.hide()
      app.resume()
    }, 'primary')))
    const soundBtn = button(app.soundOn() ? '关掉声音' : '打开声音', () => {
      const on = app.toggleSound()
      soundBtn.textContent = on ? '关掉声音' : '打开声音'
    })
    panel.append(row(
      soundBtn,
      button('操作说明', () => controls(app, () => pause(app))),
      button('关于', () => about(app, () => pause(app))),
    ))
    panel.append(row(
      button('重新开始', () => {
        app.overlay.hide()
        app.restart()
      }),
      button('回首页', () => {
        app.overlay.hide()
        app.goHome()
      }),
    ))
  }, { cls: 'pause', onDismiss: () => {
    app.overlay.hide()
    app.resume()
  } })
}

/** 秒 → 分:秒 */
export function timeText(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** 首页要不要显示新手提示(给 main 判断) */
export function showTutorial(best: Best): boolean {
  return !hasSeen(best, 'build') && levelStars(best, 1) === 0
}
