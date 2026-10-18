// 方块原野的菜单和弹层:主菜单、新世界(种子)、操作说明、关于、暂停。
// 只拼 DOM,不碰游戏状态;要做什么通过回调交给 main.ts。
import { parseSeed, seedText } from './worldgen'
import { MAX_EDITS } from './world'
import { $, button, el, row, bullets } from '../../shared/src/ui'
import type { Overlay } from '../../shared/src/ui'

export interface MenuStats {
  hasSave: boolean
  seed: number
  mined: number
  placed: number
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
  toggleSound(): void
  quitToMenu(): void
}

const fmt = (n: number): string => (n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : String(n))

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
    meta.append(el('span', `种子 ${seedText(s.seed)}`), el('span', `挖 ${fmt(s.mined)}`),
      el('span', `放 ${fmt(s.placed)}`), el('span', `已改 ${s.edits}/${MAX_EDITS} 格`))
  } else {
    meta.append(el('span', '还没有存档'), el('span', '新世界用随机种子'))
  }
  hero.append(sky, hills, text, meta)

  const card = el('div', '', 'menu-card')
  if (s.hasSave) {
    const cont = button('继续游戏', () => app.resume(), 'menu-btn primary big')
    cont.id = 'menu-continue'
    const small = el('small', '回到上次的位置和时间')
    cont.append(small)
    card.append(cont)
  }
  const fresh = button(s.hasSave ? '开一个新世界' : '开始新世界', () => app.newWorld(),
    s.hasSave ? 'menu-btn big' : 'menu-btn primary big')
  fresh.id = 'menu-new'
  card.append(fresh)
  const helpBtn = button('操作说明', () => app.help(), 'menu-btn')
  helpBtn.id = 'menu-help'
  const aboutBtn = button('关于', () => app.about(), 'menu-btn')
  aboutBtn.id = 'menu-about'
  const soundBtn = button(s.muted ? '声音:关' : '声音:开', () => app.toggleSound(), 'menu-btn')
  soundBtn.id = 'menu-sound'
  const tools = el('div', '', 'menu-tools')
  tools.append(helpBtn, aboutBtn, soundBtn)
  card.append(tools)
  card.append(el('p', '自动存档 · 没有广告、内购和排行榜', 'menu-foot'))
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
    const start = () => {
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
  overlay.show((p) => {
    p.append(el('h2', '操作说明'), bullets([
      '键盘鼠标:WASD 走,空格跳;方向键也能转视角。按住左键挖,右键放方块;1–9 或滚轮换方块;Esc 暂停。',
      '点一下画面会锁定鼠标,像在游戏里一样转视角;按 Esc 或再点一下浏览器提示退出。不锁也能按住左键拖动转视角。',
      '触屏:左下摇杆走,右侧拖动转视角,右下「跳 / 挖 / 放」三个按钮。',
      '准星对准方块按住挖。不同方块硬度不同:泥土、沙子、树叶快,石头、木板、砖慢;基岩挖不动。',
      '在水里也能挖,只是慢一点;水可以走进去游泳,按跳会往上浮。',
      '放方块放在准星对着的那一面上,放的时候不会卡进自己身体;数量是背包里的,挖到才加。',
      '掉出世界会回到出生点。天黑天亮大约 8 分钟一轮,太阳和月亮会换班。',
      '每 2–3 秒自动存档,搭到一半关掉也不怕;切到后台会立刻暂停并存档。',
      '世界最多记 4000 格改动;到上限会提示,开新世界可以从头来。',
    ]), row(button('知道了', () => {
      overlay.hide()
      back?.()
    }, 'primary')))
  }, { cls: 'about', onDismiss: back ?? (() => undefined) })
}

/** 关于:游戏是什么、数据放哪儿、边界在哪儿,都照实写 */
export function aboutPanel(overlay: Overlay, stats: MenuStats, back?: () => void): void {
  overlay.show((p) => {
    p.append(el('h2', '关于方块原野'), bullets([
      '单机第一人称体素沙盒:一座 128×128 的小岛,挖方块、放方块、搭自己的东西,关了再开还在原地。',
      '没有广告、没有内购、没有排行榜;不联网、不交易,也没有多人游戏。',
      '还没有怪物、合成、任务和剧情:就是一座岛,和你的耐心。',
      '美术全部是代码里画的 16×16 像素纹理,音效由浏览器现场合成;没有用任何外部素材、字体或图片,也没有照搬任何商业游戏的素材和界面。',
      '你的世界(种子、改过的方块、位置、背包、时间、统计)存在超级赞云存储里,按应用和你的账号隔离;官方(也就是这个游戏的开发者)不能从服务端读取,平台管理员在技术上能访问数据库,数据没有端到端加密。',
      '为了打开时不用等网络,这台设备上也缓存一份;声音开关只存在这台设备上。',
      '成绩只存在你自己这里:不上排行榜,不给别人看。',
      ...(stats.hasSave
        ? [`现在的世界:种子 ${seedText(stats.seed)},挖了 ${stats.mined} 块,放了 ${stats.placed} 块,改了 ${stats.edits}/${MAX_EDITS} 格。`]
        : ['还没有存档:开始一个新世界,种子可以自己填,也可以随机。']),
      `版本 ${stats.version} · 代码在开源仓 miniapps/sandbox。`,
    ]), row(button('知道了', () => {
      overlay.hide()
      back?.()
    }, 'primary')))
  }, { cls: 'about', onDismiss: back ?? (() => undefined) })
}

/** 暂停:继续 / 说明 / 关于 / 声音 / 回主菜单 */
export function pausePanel(overlay: Overlay, app: MenuApp): void {
  overlay.show((p) => {
    p.append(el('h2', '已暂停'), el('p', '进度已经存好了,随时可以走。', 'note'))
    const resume = button('继续', () => app.resume(), 'primary')
    const tools = el('div', '', 'pause-tools')
    tools.append(
      button('操作说明', () => app.help()),
      button('关于', () => app.about()),
      button(app.stats().muted ? '声音:关' : '声音:开', () => app.toggleSound()),
    )
    p.append(row(resume))
    p.append(tools)
    p.append(el('p', `种子 ${seedText(app.stats().seed)} · 改了 ${app.stats().edits}/${MAX_EDITS} 格 · 挖 ${app.stats().mined} 放 ${app.stats().placed}`, 'note'))
    p.append(row(button('回到主菜单', () => app.quitToMenu())))
  }, { cls: 'pause', onDismiss: () => app.resume() })
}

