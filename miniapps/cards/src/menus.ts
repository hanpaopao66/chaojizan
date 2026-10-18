// 首页、关于、结算:全是 DOM(字清楚、读屏读得到),用户看得到的字一律 textContent,不拼 HTML。
// 这里只管摆界面和转发操作;对局规则在 engine.ts,战绩在 profile.ts。
import { HEROES, hero } from './data'
import type { Profile } from './profile'
import type { HeroDef, Level } from './types'
import type { MatchResult } from './table'
import { Overlay, bullets, button, el, row } from '../../shared/src/ui'
import { artEl, sparkField } from './art'
import { play as sfx, setSound, soundOn } from './audio'

export interface Choice {
  hero: string
  level: Level
}

export interface App {
  profile(): Profile
  choice(): Choice
  /** 有没有打到一半的对局 */
  hasSave(): boolean
  /** 「上一局:熔火工坊 · 第 7 回合」这类一句话 */
  saveSummary(): string
  readonly overlay: Overlay
  /** 重新画首页 */
  goHome(): void
  pickHero(id: string): void
  pickLevel(level: Level): void
  start(): void
  resume(): void
  discardSave(): void
}

export const LEVEL_NAME: Record<Level, string> = { normal: '标准', hard: '困难' }

/** 结算页要展示的战绩数字(对局结果 + 最新的连胜) */
export interface ResultView extends MatchResult {
  streak: number
  bestStreak: number
}

const pct = (wins: number, games: number): number => (games > 0 ? Math.round((wins / games) * 100) : 0)

function topbar(app: App): HTMLElement {
  const bar = el('header', '', 'topbar')
  const mark = el('span', '单机 · 卡牌对战', 'brandmark')
  mark.setAttribute('aria-hidden', 'true')
  bar.append(mark, el('span', '', 'spacer'))
  const snd = button(soundOn() ? '音效开' : '音效关', () => {
    setSound(!soundOn())
    if (soundOn()) sfx('tap')
    app.goHome()
  }, 'ghost')
  snd.setAttribute('aria-label', soundOn() ? '关掉音效' : '打开音效')
  const info = button('关于', () => about(app), 'ghost')
  bar.append(snd, info)
  return bar
}

function deckCard(app: App, h: HeroDef, selected: boolean): HTMLButtonElement {
  const b = button('', () => {
    sfx('tap')
    app.pickHero(h.id)
    app.goHome()
  }, `deck-pick cls-${h.cls}`)
  b.setAttribute('aria-pressed', String(selected))
  const badge = el('span', '', 'deck-badge')
  badge.append(artEl(h.art))
  const meta = el('span', '', 'deck-meta')
  meta.append(el('b', h.name, 'deck-name'), el('em', h.title, 'deck-title'),
    el('span', h.style, 'deck-style'), el('span', h.desc, 'deck-desc'))
  b.append(badge, meta)
  if (selected) b.append(el('span', '出战', 'deck-on'))
  return b
}

function levelPicker(app: App): HTMLElement {
  const chosen = app.choice().level
  const box = el('div', '', 'levelbox')
  const seg = el('div', '', 'seg')
  seg.setAttribute('role', 'radiogroup')
  seg.setAttribute('aria-label', '难度')
  for (const level of ['normal', 'hard'] as Level[]) {
    const b = button(`${LEVEL_NAME[level]}${level === 'hard' ? ' · 会算斩杀' : ''}`, () => {
      sfx('tap')
      app.pickLevel(level)
      app.goHome()
    })
    b.setAttribute('role', 'radio')
    b.setAttribute('aria-checked', String(chosen === level))
    seg.append(b)
  }
  box.append(seg, el('p', chosen === 'hard'
    ? '困难:电脑会往后算几步找斩杀,低血量时更重视嘲讽保护。'
    : '标准:电脑会解场、换血、抢脸,但不会提前算多步斩杀。', 'fine'))
  return box
}

/** 首页 */
export function home(app: App, root: HTMLElement): void {
  const p = app.profile()
  const choice = app.choice()
  const hero = HEROES.find((h) => h.id === choice.hero) || HEROES[0]
  const scr = el('div', '', 'scr home')
  scr.append(topbar(app), sparkField(18))

  const title = el('div', '', 'hero-title')
  title.append(el('h1', '', 'logo'), el('p', '一桌星火 · 三套牌 · 和电脑打一场', 'tagline'))
  const logo = title.querySelector('.logo') as HTMLElement
  logo.append(el('span', '星火', 'l1'), el('span', '牌局', 'l2'))
  scr.append(title)

  if (app.hasSave()) {
    const save = el('section', '', 'savebox')
    save.append(el('b', '上一局还没打完'), el('span', app.saveSummary(), 'fine'))
    save.append(row(
      button('放弃这一局', () => app.discardSave(), 'ghost'),
      button('继续对局', () => app.resume(), 'primary'),
    ))
    scr.append(save)
  }

  const statsLine = p.games > 0
    ? `总场次 ${p.games} · 胜场 ${p.wins} · 胜率 ${pct(p.wins, p.games)}% · 当前连胜 ${p.streak} · 最佳连胜 ${p.bestStreak}`
    : '还没有战绩:第一局打完会记在这里(只存在你自己的存档里)'
  scr.append(el('p', statsLine, 'record'))

  scr.append(el('h2', '选一套卡组', 'sec'))
  const decks = el('div', '', 'decks')
  for (const h of HEROES) decks.append(deckCard(app, h, h.id === hero.id))
  scr.append(decks)

  scr.append(el('h2', '难度', 'sec'))
  scr.append(levelPicker(app))

  const cta = el('div', '', 'cta-row')
  const start = button('开始对局', () => {
    sfx('tap')
    app.start()
  }, 'cta primary')
  start.append(el('small', `${hero.title} · ${LEVEL_NAME[choice.level]}`, 'cta-sub'))
  cta.append(start, el('p', '点手牌出牌;要选目标的牌再点目标;点自己的随从再点敌方目标就能攻击。', 'fine'))
  scr.append(cta)

  const foot = el('footer', '', 'foot')
  foot.append(button('玩法与关于', () => about(app)), el('span', `${hero.title} · 30 张牌`, 'fine'))
  scr.append(foot)

  root.append(scr)
}

/** 「关于」:规则、原创说明、隐私,全都如实写。after:关掉之后回到哪儿(暂停菜单看完规则回到暂停) */
export function about(app: App, after?: () => void): void {
  const close = (): void => {
    app.overlay.hide()
    after?.()
  }
  const soundBtn = button(soundOn() ? '关掉音效' : '打开音效', () => {
    setSound(!soundOn())
    soundBtn.textContent = soundOn() ? '关掉音效' : '打开音效'
    if (soundOn()) sfx('tap')
  })
  app.overlay.show((panel) => {
    panel.append(el('h2', '关于星火牌局'))
    panel.append(el('p', '单机回合制卡牌对战:你和电脑各 30 点生命,把对面的英雄打到 0 就赢。'))
    panel.append(bullets([
      '双方英雄 30 点生命,能量上限每回合 +1(最多 10 点),回合开始回满;每回合抽一张牌,牌库 30 张、抽空后受递增的疲劳伤害。',
      '随从站场、法术解场。随从有「嘲讽」(对面必须先打它)、「冲锋」(上场当回合就能攻击)、「圣盾」(免疫第一次伤害)、「战吼」和「亡语」;每方场上最多 7 个随从,手牌最多 10 张。',
      '三套预组卡组:熔火工坊(快攻直伤)、霜林哨站(防守消耗)、暮影集市(铺场换牌);36 张原创卡牌,每套 30 张,同一张最多 2 份。',
      '世界观、卡牌名字、卡面图案和界面都是原创的,没有使用任何商业卡牌游戏的名字、卡牌、角色或素材。所有卡面和图标是程序化 SVG / CSS,音效由 WebAudio 现场合成,没有外部图片、字体、音频或网络请求。',
      '没有广告、没有内购、没有排行榜;没有开包、抽卡、卡牌收集和升级。电脑的每一步都在你的手机上算,不联网。',
      '两档难度:标准会解场换血抢脸;困难会往后算几步找斩杀,低血量时更重视嘲讽保护。',
      '每一手自动存档到超级赞云存储,关了再开、换设备都能接着打;对局中途的手牌、牌库顺序、场面、能量、回合和随机数种子都会存下来。',
      '前端游戏的胜负没法由服务器验证,所以战绩只存在你自己这里,不给别人看。',
      '隐私:游戏数据(对局存档和战绩)存在超级赞云存储里,按应用和你的账号隔离;官方(这个游戏的开发者)不能从服务端读取;平台管理员在技术上能访问数据库,数据没有端到端加密。为了打开时不用等网络,你的设备上也缓存一份。你可以在我 → 设置 → 小程序授权与数据里导出或清空;注销账号时一并删除。不申请昵称、头像、定位等任何其他信息。',
    ]))
    panel.append(row(soundBtn, button('知道了', close, 'primary')))
    // 弹层默认把焦点放在主按钮上,长文会自己滚到底;这里拉回顶部,先看到「关于」的开头
    requestAnimationFrame(() => { panel.scrollTop = 0 })
  }, { cls: 'about', onDismiss: close })
}

/** 结算 */
export function result(app: App, r: ResultView): void {
  app.overlay.show((panel) => {
    panel.append(el('h2', r.draw ? '平局' : r.won ? '胜利' : '失败'))
    panel.append(el('p', `${hero(r.hero).name} · ${LEVEL_NAME[r.level]} · 第 ${r.turns} 回合`, ''))
    const grid = el('div', '', 'result-grid')
    const cells: Array<[string, string]> = [
      ['出牌', `${r.played} 张`],
      ['造成伤害', String(r.dealt)],
      ['损失随从', String(r.lost)],
      ['对局时长', `${r.turns} 回合`],
    ]
    for (const [k, v] of cells) {
      const c = el('div', '', 'result-cell')
      c.append(el('span', k), el('b', v))
      grid.append(c)
    }
    panel.append(grid)
    panel.append(el('p', `当前连胜 ${r.streak} · 最佳连胜 ${r.bestStreak}`, 'fine'))
    if (r.won) panel.append(el('p', '赢了。要不要换套卡组再来一局?', ''))
    panel.append(row(
      button('回首页', () => app.goHome()),
      button('再来一局', () => app.start(), 'primary'),
    ))
  }, { onDismiss: () => app.goHome() })
}
