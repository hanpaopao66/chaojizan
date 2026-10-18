// 方块原野的菜单和弹层:主菜单、新世界(种子)、暂停、操作说明、关于、成就/统计、改动清理。
// 只拼 DOM,不碰游戏状态;要做什么通过回调交给 main.ts。
import { ACHIEVEMENTS, LIMITS, TEXT } from './data'
import { achievementProgress, type AchievementContext } from './achievements'
import { formatDistance, formatDuration, unlockedCount, type Profile } from './profile'
import { MAX_EDITS } from './world'
import { parseSeed, seedText } from './worldgen'
import { $, Overlay, button, bullets, confirmBox, el, row } from '../../shared/src/ui'

export interface MenuStats {
  hasSave: boolean
  seed: number
  mined: number
  placed: number
  walked: number
  seconds: number
  achievements: number
  achievementsTotal: number
  edits: number
  muted: boolean
  version: string
}

export interface MenuApp {
  stats(): MenuStats
  resume(): void
  newWorld(): void
  help(): void
  about(): void
  achievements(): void
  toggleSound(): void
  quitToMenu(): void
  /** 打开改动清理面板(局内暂停时才用) */
  cleanup(): void
}

const fmt = (n: number): string => (n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : String(n))
const ratioText = (n: number): string => `${n} / ${LIMITS.MAX_EDITS}`

/** 主菜单;数据变了就重建一次(重建前记住焦点在哪个按钮上) */
export function mainMenu(root: HTMLElement, app: MenuApp): void {
  const s = app.stats()
  const focusId = (document.activeElement as HTMLElement | null)?.id || ''
  root.textContent = ''
  root.hidden = false
  const screen = el('div', '', 'menu-screen')

  const hero = el('div', '', 'menu-hero')
  const sky = el('div', '', 'menu-sky')
  sky.append(el('i', '', 'menu-sun'))
  for (let i = 0; i < 3; i++) sky.append(el('i', '', `menu-cloud c${i + 1}`))
  const hills = el('div', '', 'menu-hills')
  hills.append(el('i', '', 'h1'), el('i', '', 'h2'), el('i', '', 'h3'))
  const text = el('div', '', 'menu-title')
  text.append(
    el('p', '超级赞 · 官方小游戏', 'eyebrow'),
    el('h1', '方块原野'),
    el('p', '一座小岛,想怎么挖、怎么搭,都随你', 'tagline'),
  )
  const meta = el('p', '', 'menu-meta')
  if (s.hasSave) {
    meta.append(
      el('span', `种子 ${seedText(s.seed)}`),
      el('span', `挖 ${fmt(s.mined)} · 放 ${fmt(s.placed)}`),
      el('span', `走了 ${formatDistance(s.walked)}`),
      el('span', `成就 ${s.achievements}/${s.achievementsTotal}`),
      el('span', `已改 ${s.edits}/${LIMITS.MAX_EDITS} 格`),
    )
  } else {
    meta.append(el('span', '还没有存档'), el('span', '新世界用随机种子'))
  }
  hero.append(sky, hills, text, meta)

  const card = el('div', '', 'menu-card')
  if (s.hasSave) {
    const cont = button('继续游戏', () => app.resume(), 'menu-btn primary big')
    cont.id = 'menu-continue'
    cont.append(el('small', '回到上次的位置和时间'))
    card.append(cont)
  }
  const fresh = button(s.hasSave ? '开一个新世界' : '开始新世界', () => app.newWorld(),
    s.hasSave ? 'menu-btn big' : 'menu-btn primary big')
  fresh.id = 'menu-new'
  card.append(fresh)
  const ach = button(`成就 ${s.achievements}/${s.achievementsTotal}`, () => app.achievements(), 'menu-btn')
  ach.id = 'menu-ach'
  const helpBtn = button('操作说明', () => app.help(), 'menu-btn')
  helpBtn.id = 'menu-help'
  const aboutBtn = button('关于', () => app.about(), 'menu-btn')
  aboutBtn.id = 'menu-about'
  const soundBtn = button(s.muted ? '声音:关' : '声音:开', () => app.toggleSound(), 'menu-btn')
  soundBtn.id = 'menu-sound'
  const tools = el('div', '', 'menu-tools')
  tools.append(ach, helpBtn, aboutBtn, soundBtn)
  card.append(tools)
  card.append(el('p', '自动存档 · 没有广告、内购和排行榜', 'menu-foot'))
  card.append(el('p', `v${s.version}`, 'menu-version'))
  screen.append(hero, card)
  root.append(screen)
  // 焦点尽量留在原来的按钮上,键盘用户不会「跳走」
  if (focusId) $(focusId)?.focus()
}

/** 新世界:输入种子(留空随机)。开始前由 main 决定要不要确认替换 */
export function newWorldPanel(overlay: Overlay, currentSeed: number | null, onStart: (seed: number | null) => void): void {
  overlay.show((p) => {
    p.append(el('h2', '新世界'))
    p.append(el('p', currentSeed === null ? '用种子生成一座小岛,同一个种子永远是同一座岛。' : '会替换现在这个世界;现在的进度已经自动存档,但菜单里只留最新的一个。'))
    const label = el('label', '世界种子(留空 = 随机)', 'field')
    const input = el('input')
    input.type = 'text'
    input.inputMode = 'text'
    input.maxLength = 10
    input.placeholder = currentSeed === null ? '比如 20261018 或 5f' : seedText(currentSeed)
    input.id = 'nw-seed'
    input.autocomplete = 'off'
    input.spellcheck = false
    label.append(input)
    p.append(label)
    const error = el('p', '', 'field-error')
    error.hidden = true
    p.append(error)
    const start = (): void => {
      const raw = input.value.trim()
      const seed = raw ? parseSeed(raw) : null
      if (raw && seed === null) {
        error.textContent = '这个种子看不懂:填 0–4294967295 的数字,或 1–7 位数字/小写字母'
        error.hidden = false
        input.setAttribute('aria-invalid', 'true')
        input.focus()
        return
      }
      overlay.hide()
      onStart(seed)
    }
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        start()
      }
    })
    const go = button('开始生成', start, 'primary')
    go.id = 'nw-start'
    const cancel = button('取消', () => overlay.hide())
    cancel.id = 'nw-cancel'
    p.append(row(cancel, go))
    setTimeout(() => input.focus(), 30)
  }, { cls: 'sheet', onDismiss: () => undefined })
}

/** 操作说明 */
export function helpPanel(overlay: Overlay, back?: () => void): void {
  const close = (): void => {
    overlay.hide()
    back?.()
  }
  overlay.show((p) => {
    p.append(el('h2', '操作说明'), bullets([
      '键盘鼠标:WASD 走,空格跳;方向键也能转视角。按住左键挖,右键放方块;1–9 或滚轮换方块;Esc 暂停。',
      '点一下画面会锁定鼠标,像在游戏里一样转视角;按 Esc 或再点一下浏览器提示退出。不锁也能按住左键拖动转视角。',
      '触屏:左下摇杆走,右侧拖动转视角,右下「跳 / 挖 / 放」三个按钮。',
      '准星对准方块按住挖。不同方块硬度不同:草、沙、树叶快,石头、木板、砖慢;基岩挖不动。挖的时候方块上会出现裂纹。',
      '在水里也能挖,只是慢一点;水可以走进去游泳,按跳会往上浮。',
      '放方块放在准星对着的那一面上,放的时候不会卡进自己身体;数量是背包里的,挖到才加。',
      '掉出世界会回到出生点。天黑天亮大约 8 分钟一轮,太阳和月亮会换班。',
      '每 2–3 秒自动存档,搭到一半关掉也不怕;切到后台会立刻暂停并存档。',
      `世界最多记 ${LIMITS.MAX_EDITS} 格改动;快到上限时 HUD 会提醒,菜单和暂停里可以「成就 / 清理」——撤销最近 ${LIMITS.CLEANUP_BATCH} 处改动,或把整座岛恢复成刚生成的样子。`,
    ]), row(button('知道了', close, 'primary')))
  }, { cls: 'about', onDismiss: back ?? (() => undefined) })
}

/** 关于:游戏是什么、数据放哪儿、边界在哪儿,都照实写 */
export function aboutPanel(overlay: Overlay, stats: MenuStats, back?: () => void): void {
  const close = (): void => {
    overlay.hide()
    back?.()
  }
  overlay.show((p) => {
    p.append(el('h2', '关于方块原野'), bullets([
      '单机第一人称体素沙盒:一座 128×128 的小岛,挖方块、放方块、搭自己的东西,关了再开还在原地。',
      '没有广告、没有内购、没有排行榜;不联网、不交易,也没有多人游戏。',
      '还没有怪物、合成、任务和剧情:就是一座岛,和你的耐心。',
      '有 13 个成就和一些不打扰人的引导:第一次挖、第一次放、搭到高处、走过三种地形、一口气挖 50 块……成就跨设备保留。',
      '美术全部是代码里画的 16×16 像素纹理(每种方块 3 个变体),云、星星、水面和碎屑也是算出来的;音效由浏览器现场合成,包括按材质区分的脚步和环境声。没有用任何外部素材、字体或图片,也没有照搬任何商业游戏的素材和界面。',
      '你的世界(种子、改过的方块、位置、背包、时间)存在超级赞云存储里,按应用和你的账号隔离;累计统计和成就在同一份云存储里,两台设备的数取较大值、成就取并集。官方(也就是这个游戏的开发者)不能从服务端读取,平台管理员在技术上能访问数据库,数据没有端到端加密。',
      '为了打开时不用等网络,这台设备上也缓存一份;声音开关只存在这台设备上。',
      '成绩只存在你自己这里:不上排行榜,不给别人看。',
      ...(stats.hasSave
        ? [`现在的世界:种子 ${seedText(stats.seed)},挖了 ${stats.mined} 块,放了 ${stats.placed} 块,走了 ${formatDistance(stats.walked)},玩了 ${formatDuration(stats.seconds)},改了 ${stats.edits}/${LIMITS.MAX_EDITS} 格。`]
        : ['还没有存档:开始一个新世界,种子可以自己填,也可以随机。']),
      `版本 ${stats.version} · 代码在开源仓 miniapps/sandbox。`,
    ]), row(button('知道了', close, 'primary')))
  }, { cls: 'about', onDismiss: back ?? (() => undefined) })
}

/** 成就 + 统计面板 */
export function achievementsPanel(overlay: Overlay, stats: MenuStats, profile: Profile,
  ctx: AchievementContext, back?: () => void): void {
  const close = (): void => {
    overlay.hide()
    back?.()
  }
  overlay.show((p) => {
    p.append(el('h2', `成就与统计`), el('p', `已解锁 ${unlockedCount(profile)} / ${ACHIEVEMENTS.length} 个成就`, 'note'))
    const grid = el('div', '', 'stats-grid')
    const cell = (label: string, value: string): HTMLElement => {
      const d = el('div', '', 'stat-card')
      d.append(el('b', value), el('span', label))
      return d
    }
    grid.append(
      cell('挖掉的方块', fmt(profile.mined)),
      cell('放下的方块', fmt(profile.placed)),
      cell('走过的路', formatDistance(profile.walked)),
      cell('在岛上', formatDuration(profile.seconds)),
      cell('改动格子', `${stats.edits}/${LIMITS.MAX_EDITS}`),
      cell('世界种子', seedText(stats.seed)),
    )
    p.append(grid)
    p.append(el('h3', '成就'))
    const list = el('ul', '', 'ach-list')
    for (const def of ACHIEVEMENTS) {
      const prog = achievementProgress(def, profile, ctx)
      const li = el('li', '', prog.done ? 'done' : '')
      li.append(el('i', def.icon, 'ach-icon'))
      const mid = el('div', '', 'ach-mid')
      mid.append(el('b', def.name))
      mid.append(el('span', def.desc))
      li.append(mid)
      const right = el('div', '', 'ach-right')
      if (prog.done) {
        right.append(el('em', '已解锁', 'ach-done'))
        right.append(el('small', dateText(profile.achievements[def.id])))
      } else {
        right.append(el('small', `${Math.min(prog.current, prog.goal)} / ${prog.goal}`))
        const bar = el('div', '', 'prog')
        const fill = el('i')
        fill.style.transform = `scaleX(${Math.min(1, prog.current / Math.max(1, prog.goal)).toFixed(3)})`
        bar.append(fill)
        right.append(bar)
      }
      li.append(right)
      list.append(li)
    }
    p.append(list)
    p.append(el('p', '条件型的成就在「关于」和这里都能看到条件;进度只存在你自己的存档里。', 'note'))
    p.append(row(button('知道了', close, 'primary')))
  }, { cls: 'about achievements', onDismiss: back ?? (() => undefined) })
}

function dateText(at: number | undefined): string {
  if (!at || at <= 1) return ''
  try {
    const d = new Date(at)
    return `${d.getMonth() + 1}/${d.getDate()}`
  } catch (_) {
    return ''
  }
}

/** 改动容量清理:快到上限/已满时给玩家真正的出口(撤销最近改动 / 恢复原始小岛) */
export function cleanupPanel(overlay: Overlay, edits: number, back: () => void,
  onRecent: () => void, onAll: () => void): void {
  overlay.show((p) => {
    p.append(el('h2', edits >= MAX_EDITS ? TEXT.FULL_LIMIT : TEXT.FULL_WARN))
    p.append(el('p', `现在的改动:${ratioText(edits)} 格。${TEXT.FULL_HINT}`, 'note'))
    p.append(row(
      button('先看看', back),
      button(TEXT.CLEANUP_RECENT, () => {
        overlay.hide()
        onRecent()
      }, 'primary'),
    ))
    p.append(row(button(TEXT.CLEANUP_ALL, () => {
      void (async () => {
        const ok = await confirmBox('把整座岛恢复成刚生成的样子?你搭的东西会全部消失(背包、位置和统计保留)。')
        if (!ok) return
        overlay.hide()
        onAll()
      })()
    }, 'danger')))
  }, { cls: 'sheet', onDismiss: back })
}

/** 暂停:继续 / 成就 / 说明 / 关于 / 声音 / 回主菜单 */
export function pausePanel(overlay: Overlay, app: MenuApp): void {
  const s = app.stats()
  overlay.show((p) => {
    p.append(el('h2', '已暂停'), el('p', '进度已经存好了,随时可以走。', 'note'))
    const resume = button('继续', () => app.resume(), 'primary')
    const tools = el('div', '', 'pause-tools')
    tools.append(
      button(`成就 ${s.achievements}/${s.achievementsTotal}`, () => app.achievements()),
      button('操作说明', () => app.help()),
      button('关于', () => app.about()),
      button(s.muted ? '声音:关' : '声音:开', () => app.toggleSound()),
    )
    p.append(row(resume))
    p.append(tools)
    const line = el('div', '', 'pause-stats')
    line.append(
      el('span', `挖 ${fmt(s.mined)}`),
      el('span', `放 ${fmt(s.placed)}`),
      el('span', `走 ${formatDistance(s.walked)}`),
      el('span', `玩 ${formatDuration(s.seconds)}`),
      el('span', `改 ${s.edits}/${LIMITS.MAX_EDITS} 格`),
    )
    p.append(line)
    if (s.edits >= Math.ceil(LIMITS.MAX_EDITS * LIMITS.FULL_WARN_RATIO)) {
      p.append(row(button(`清理改动 ${s.edits}/${LIMITS.MAX_EDITS} 格`, () => app.cleanup(), 'danger')))
    }
    p.append(el('p', `种子 ${seedText(s.seed)} · v${s.version}`, 'note'))
    p.append(row(button('回到主菜单', () => app.quitToMenu())))
  }, { cls: 'pause', onDismiss: () => app.resume() })
}
