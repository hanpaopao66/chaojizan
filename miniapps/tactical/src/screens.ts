// 首页(标题、行动简报、开始/难度/说明/关于/声音)和「操作说明」「关于」两个弹层。
//
// 首页是每次回主页 / 换难度 / 开关声音时整块重建的:内容简单,重建比局部更新更不容易出错。
// 文案上如实写清楚:不是 3D 射击、没有广告内购排行榜、数据只存云存储、成绩只存在自己这里。

import { Overlay, button, bullets, el } from '../../shared/src/ui'
import { DIFFICULTIES, DIFFICULTY_LABELS, Difficulty } from './combat'
import { Profile, accuracy } from './profile'

export interface HomeHandlers {
  profile: Profile
  onStart: () => void
  onDifficulty: (difficulty: Difficulty) => void
  onControls: () => void
  onAbout: () => void
  /** 切声音;返回切换之后是不是开着 */
  onToggleSound: () => boolean
}

/** 重建首页。root 是 #screen */
export function renderHome(root: HTMLElement, opts: HomeHandlers): void {
  const profile = opts.profile
  root.textContent = ''
  const home = el('div', '', 'home')

  // 左侧:标题
  const title = el('div', '', 'home-title')
  title.append(el('p', '单机 · 2D 俯视 · 回合制拆弹', 'kicker'))
  const logo = el('h1', '', 'logo')
  logo.append(document.createTextNode('突击'))
  const em = document.createElement('em')
  em.textContent = '时刻'
  logo.append(em)
  title.append(logo)
  title.append(el('p', '突破 3 名守卫的防线,到 A 或 B 点安放炸弹,再守住 30 秒。', 'tagline'))
  const hazard = el('div', '', 'hazard')
  hazard.append(el('i'), el('i'), el('i'))
  title.append(hazard)
  home.append(title)

  // 右侧:行动简报
  const brief = el('div', '', 'brief')
  brief.append(el('h2', '行动简报'))
  const ul = el('ul')
  const item = (mark: string, parts: Array<string | HTMLElement>): HTMLLIElement => {
    const li = el('li')
    li.append(el('i', '', `mark ${mark}`))
    for (const part of parts) {
      if (typeof part === 'string') li.append(document.createTextNode(part))
      else li.append(part)
    }
    return li
  }
  const bold = (text: string): HTMLElement => {
    const b = el('b')
    b.textContent = text
    return b
  }
  ul.append(item('circle', [bold('A / B'), ' 两个炸弹点:按住 2.5 秒安放,炸弹 30 秒后爆炸。']))
  ul.append(item('diamond', [bold('3 名守卫'), ' 会听枪声过来查、看见你就开枪;炸弹安好后 1–2 秒内跑去拆。']))
  ul.append(item('tri', [bold('75 秒'), ' 一个回合。先赢 2 回合者获胜;没安放炸弹时时间耗尽算失败。']))
  brief.append(ul)
  home.append(brief)

  // 操作区:开始 + 难度 + 说明/关于/声音
  const ops = el('div', '', 'ops')
  ops.append(button('开始行动', opts.onStart, 'start'))

  const side = el('div', '', 'side-actions')
  const diffRow = el('div', '', 'diffrow')
  diffRow.append(el('span', '难度', 'kicker'))
  const seg = el('div', '', 'seg')
  seg.setAttribute('role', 'radiogroup')
  seg.setAttribute('aria-label', '难度')
  const diffButtons: Array<[Difficulty, HTMLButtonElement]> = []
  for (const id of DIFFICULTIES) {
    const label = DIFFICULTY_LABELS[id]
    const b = button(label, () => {
      opts.onDifficulty(id)
      for (const [bid, btn] of diffButtons) btn.setAttribute('aria-checked', String(bid === id))
    })
    b.setAttribute('role', 'radio')
    b.setAttribute('aria-checked', String(profile.difficulty === id))
    diffButtons.push([id, b])
    seg.append(b)
  }
  diffRow.append(seg)
  side.append(diffRow)

  const row2 = el('div', '', 'row2')
  row2.append(button('操作说明', opts.onControls, 'ghost-btn'), button('关于', opts.onAbout, 'ghost-btn'))
  const soundToggle = button(profile.sound ? '声音:开' : '声音:关', () => {
    const on = opts.onToggleSound()
    soundToggle.textContent = `声音:${on ? '开' : '关'}`
    soundToggle.setAttribute('aria-pressed', String(on))
  })
  soundToggle.className = 'ghost-btn'
  soundToggle.setAttribute('aria-pressed', String(profile.sound))
  row2.append(soundToggle)
  side.append(row2)
  ops.append(side)
  home.append(ops)

  // 战绩
  const stats = el('div', '', 'stats')
  if (profile.games === 0) {
    const first = el('div', '', 'stat first')
    first.append(el('span', '还没有战绩'), el('b', '这一局是第一场行动,打完会记在这里。'))
    stats.append(first)
  } else {
    const stat = (label: string, value: string): HTMLElement => {
      const d = el('div', '', 'stat')
      d.append(el('span', label), el('b', value))
      return d
    }
    stats.append(
      stat('场次', String(profile.games)),
      stat('胜', String(profile.wins)),
      stat('负', String(profile.losses)),
      stat('最佳连胜', String(profile.bestStreak)),
      stat('命中率', `${Math.round(accuracy(profile) * 100)}%`),
    )
  }
  home.append(stats)

  const fine = el('p', '', 'fine')
  fine.textContent = '没有广告、没有内购、没有排行榜。电脑的每一步都在你的设备上算,不联网;成绩只存在你自己这里。'
  home.append(fine)

  root.append(home)
  root.scrollTop = 0
}

/** 操作说明弹层 */
export function showControls(overlay: Overlay, onClose: () => void): void {
  overlay.show((p) => {
    p.append(el('h2', '操作说明'))
    const ul = el('ul', '', 'keys')
    const key = (text: string): HTMLElement => el('span', text, 'kbd')
    const line = (title: string, keys: string[], desc: string): HTMLLIElement => {
      const li = el('li')
      li.append(document.createTextNode(`${title}:`))
      for (const k of keys) li.append(key(k))
      li.append(document.createTextNode(desc))
      return li
    }
    ul.append(
      line('移动', ['W', 'A', 'S', 'D'], '/ 方向键;手机上用左半屏摇杆'),
      line('瞄准', ['鼠标'], ';手机上用右半屏摇杆,推杆即开火'),
      line('开火', ['左键'], ';手机推右摇杆'),
      line('换弹', ['R'], ';手机上点「换弹」按钮(打空会自动换)'),
      line('安放', ['E'], ' 在 A/B 炸弹点按住 2.5 秒;手机上按住「安放」按钮'),
      line('暂停', ['Esc'], ';手机上点左上角暂停'),
    )
    p.append(ul)
    p.append(el('p', '回合 75 秒;炸弹 30 秒;守卫拆弹 5 秒。先赢 2 回合者获胜。', 'substat'))
    p.append(el('p', '难度分休闲、标准、困难三档(默认标准):只影响守卫的反应时间、瞄准误差、视距和移动速度,不改变枪械与伤害。', 'substat'))
    p.append(el('p', '守卫会听枪声过来调查;炸弹安好后 1–2 秒内会跑去拆,露头打他们可以打断。', 'substat'))
    p.append(buttonRow(() => {
      overlay.hide()
      onClose()
    }))
  }, { cls: 'about', onDismiss: onClose })
}

/** 关于弹层:如实写清楚做了什么、没做什么、数据存在哪 */
export function showAbout(overlay: Overlay, profile: Profile, onClose: () => void): void {
  overlay.show((p) => {
    p.append(el('h2', '关于突击时刻'))
    p.append(bullets([
      '单机 2D 俯视战术射击:整张地图一屏可见。不是 3D 射击游戏,不含任何真实武器品牌、真实地图或他人的素材。',
      '你是进攻方:75 秒内清掉或绕开 3 名 AI 守卫,到 A 或 B 点按住 2.5 秒安放炸弹,再守 30 秒不让守卫拆掉;先赢 2 回合者获胜。',
      '美术全部用 Canvas 2D 程序化绘制,枪声、换弹、爆炸等音效由 WebAudio 现场合成 —— 没有外部图片、字体、音频,不联网。',
      '守卫有休闲、标准、困难三档(默认标准):只影响反应时间、瞄准误差、视距和移动速度,枪的伤害、弹匣和射速和玩家完全一样。',
      '没有血腥暴力表现:命中是火花、烟和弹壳,倒下的角色只留一个装备标记。',
      '数据只存超级赞云存储,按应用和你的账号隔离:战绩(场次、胜、负、最佳连胜)、累计击杀/安放/命中、难度和声音开关。不保存进行中的比赛 —— 回合制,关掉就从首页开新局。官方(也就是这个游戏的开发者)不能从服务端读取;平台管理员在技术上能访问数据库,数据没有端到端加密。可以在「我的 → 设置 → 小程序授权与数据」里导出或清空;注销账号时一并删除。',
      '明确不做:多人联机、开箱/饰品、内购、广告、排行榜、体力与签到。',
      '没有广告,没有内购,没有排行榜;成绩只存在你自己这里,不上排行榜、不给别人看。',
      profile.games > 0
        ? `你的战绩:${profile.games} 场,${profile.wins} 胜 ${profile.losses} 负,最佳连胜 ${profile.bestStreak}。`
        : '还没有战绩记录。',
    ]))
    p.append(buttonRow(() => {
      overlay.hide()
      onClose()
    }))
  }, { cls: 'about', onDismiss: onClose })
}

/** 弹层里那排「知道了」按钮 */
function buttonRow(onClick: () => void): HTMLElement {
  const rowEl = el('div', '', 'row')
  rowEl.append(button('知道了', onClick, 'primary'))
  return rowEl
}
