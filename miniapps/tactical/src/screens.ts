// 首页(标题、行动简报、选图、开始/训练/难度/说明/关于/成就/声音)和三个说明弹层。
//
// 首页是每次回主页 / 换难度 / 换图 / 开关声音时整块重建的:内容简单,重建比局部更新更不容易出错。
// 文案上如实写清楚:不是 3D 射击、没有广告内购排行榜、数据只存云存储、成绩只存在自己这里。

import { Overlay, button, bullets, confirmBox, el, row } from '../../shared/src/ui'
import { ACHIEVEMENTS, AchievementDef } from './achievements'
import { DIFFICULTY_LABELS, Difficulty } from './combat'
import { MAPS, MapDef, MapId, ROWS } from './map'
import { Profile, accuracy } from './profile'
import { MatchState, Round, RoundSummary, accuracyOf } from './match'

export interface HomeHandlers {
  profile: Profile
  onStart: () => void
  /** 训练场:不记战绩、守卫无限复活 */
  onTraining: () => void
  onDifficulty: (difficulty: Difficulty) => void
  onMap: (mapId: MapId) => void
  onControls: () => void
  onAbout: () => void
  onAchievements: () => void
  /** 切声音;返回切换之后是不是开着 */
  onToggleSound: () => boolean
}

/** 首页小地图预览:把 ASCII 图缩着画出来,一眼看出两张图布局不一样 */
function drawMapPreview(canvas: HTMLCanvasElement, def: MapDef): void {
  const cols = def.rows[0].length
  const dpr = Math.min(2, window.devicePixelRatio || 1)
  const w = 108
  const h = Math.round((w / cols) * ROWS)
  canvas.width = Math.round(w * dpr)
  canvas.height = Math.round(h * dpr)
  canvas.style.width = `${w}px`
  canvas.style.height = `${h}px`
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.fillStyle = '#2B323B'
  ctx.fillRect(0, 0, w, h)
  const cell = w / cols
  for (let row = 0; row < ROWS; row++) {
    for (let col = 0; col < cols; col++) {
      const ch = def.rows[row]?.[col] ?? '#'
      let color = ''
      if (ch === '#') color = '#78808C'
      else if (ch === 'c') color = '#B9804A'
      else if (ch === 'A') color = '#E0B04A'
      else if (ch === 'B') color = '#6FA9D0'
      else if (ch === 'P') color = '#4FC3F7'
      else if (ch === 'G') color = '#E0643C'
      if (!color) continue
      ctx.fillStyle = color
      ctx.fillRect(col * cell, row * cell, Math.ceil(cell), Math.ceil(cell))
    }
  }
}

/** 重建首页。root 是 #screen */
export function renderHome(root: HTMLElement, opts: HomeHandlers): void {
  const profile = opts.profile
  root.textContent = ''
  const home = el('div', '', 'home')

  // 标题
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

  // 行动简报
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
  ul.append(item('circle', [bold('A / B'), ' 两处炸弹点:按住 2.5 秒安放,炸弹 30 秒后爆炸。']))
  ul.append(item('diamond', [bold('3 名守卫'), ' 会听枪声调查、看见人就开枪;炸弹安好 1–2 秒内去拆。']))
  ul.append(item('tri', [bold('75 秒'), ' 一回合,先赢 2 回合者获胜;训练场不记战绩。']))
  brief.append(ul)
  home.append(brief)

  // 选图:两张地图卡片
  const mapRow = el('div', '', 'maprow')
  mapRow.setAttribute('role', 'radiogroup')
  mapRow.setAttribute('aria-label', '选择地图')
  for (const def of MAPS) {
    const card = el('button', '', `mapcard${def.id === profile.mapId ? ' sel' : ''}`)
    card.type = 'button'
    card.setAttribute('role', 'radio')
    card.setAttribute('aria-checked', String(def.id === profile.mapId))
    card.setAttribute('aria-label', `地图:${def.name}。${def.tagline}`)
    const preview = document.createElement('canvas')
    preview.className = 'map-preview'
    preview.setAttribute('aria-hidden', 'true')
    drawMapPreview(preview, def)
    const text = el('span', '', 'map-text')
    text.append(el('b', def.name), el('small', def.tagline))
    card.append(preview, text)
    card.addEventListener('click', () => opts.onMap(def.id))
    mapRow.append(card)
  }
  home.append(mapRow)

  // 开始 / 训练 / 难度 / 说明
  const ops = el('div', '', 'ops')
  const start = button('开始行动', opts.onStart, 'start')
  ops.append(start)
  const side = el('div', '', 'side-actions')
  const diffRow = el('div', '', 'diffrow')
  diffRow.append(el('span', '难度', 'kicker'))
  const seg = el('div', '', 'seg')
  seg.setAttribute('role', 'radiogroup')
  seg.setAttribute('aria-label', '难度')
  const diffButtons: Array<[Difficulty, HTMLButtonElement]> = []
  for (const [id, label] of [['casual', '休闲'], ['normal', '标准'], ['hard', '困难']] as Array<[Difficulty, string]>) {
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
  row2.append(
    button('训练场', opts.onTraining, 'ghost-btn train'),
    button('操作说明', opts.onControls, 'ghost-btn'),
    button('关于', opts.onAbout, 'ghost-btn'),
  )
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

  // 战绩 + 成就入口
  const stats = el('div', '', 'stats')
  const stat = (label: string, value: string): HTMLElement => {
    const d = el('div', '', 'stat')
    d.append(el('span', label), el('b', value))
    return d
  }
  if (profile.games === 0) {
    stats.append(stat('还没有战绩', '这一局是第一场行动'))
  } else {
    stats.append(
      stat('场次', String(profile.games)),
      stat('胜', String(profile.wins)),
      stat('负', String(profile.losses)),
      stat('最佳连胜', String(profile.bestStreak)),
      stat('命中率', `${Math.round(accuracy(profile) * 100)}%`),
    )
  }
  const ach = el('button', '', 'stat ach-btn')
  ach.type = 'button'
  ach.append(el('span', '成就'), el('b', `${profile.achievements.length}/${ACHIEVEMENTS.length}`))
  ach.addEventListener('click', opts.onAchievements)
  stats.append(ach)
  home.append(stats)

  const fine = el('p', '', 'fine')
  fine.textContent = '突击时刻 1.1 · 没有广告、没有内购、没有排行榜。电脑的每一步都在你的设备上算,不联网;成绩只存在你自己这里。'
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
      line('切枪', ['Q'], ' 步枪 / 手枪;手机上点「切枪」按钮'),
      line('安放', ['E'], ' 在 A/B 炸弹点按住 2.5 秒;手机上按住「安放」按钮'),
      line('暂停', ['Esc'], ';手机上点左上角暂停'),
    )
    p.append(ul)
    p.append(el('p', '回合 75 秒;炸弹 30 秒;守卫拆弹 5 秒。先赢 2 回合者获胜。训练场里守卫会无限复活,不记战绩。', 'substat'))
    p.append(el('p', '难度分休闲、标准、困难三档(默认标准):只影响守卫的反应时间、瞄准误差、视距和移动速度,不改变枪械与伤害。', 'substat'))
    p.append(el('p', '守卫会听枪声过来调查;炸弹安好后 1–2 秒内会跑去拆,露头打他们可以打断。', 'substat'))
    p.append(buttonRow(() => {
      overlay.hide()
      onClose()
    }))
  }, { cls: 'about', onDismiss: onClose })
}

/** 成就弹层 */
export function showAchievements(overlay: Overlay, profile: Profile, onClose: () => void): void {
  overlay.show((p) => {
    p.append(el('h2', '成就'))
    p.append(el('p', `已解锁 ${profile.achievements.length} / ${ACHIEVEMENTS.length}`, 'sub'))
    const list = el('ul', '', 'ach-list')
    for (const def of ACHIEVEMENTS) {
      const got = profile.achievements.indexOf(def.id) >= 0
      const li = el('li', '', got ? 'got' : '')
      const badge = el('i', def.icon, 'ach-badge')
      const text = el('span', '', 'ach-text')
      text.append(el('b', def.name), el('small', def.desc))
      li.append(badge, text)
      list.append(li)
    }
    p.append(list)
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
      '单机 2D 俯视战术射击:两张地图(旧仓库 / 霓虹夜市),整张地图一屏可见。不是 3D 射击游戏,不含任何真实武器品牌、真实地图或他人的素材。',
      '你是进攻方:75 秒内清掉或绕开 3 名 AI 守卫,到 A 或 B 点按住 2.5 秒安放炸弹,再守 30 秒不让守卫拆掉;先赢 2 回合者获胜。',
      '主武器是步枪(30 发弹匣),副武器是手枪(12 发、单发伤害更高),按 Q 或点「切枪」切换,两把枪弹匣独立;训练场里守卫无限复活,不记战绩。',
      '美术全部用 Canvas 2D 程序化绘制,枪声、脚步、爆炸等音效由 WebAudio 现场合成并做空间化(左右/远近),BGM 也是现场合成的循环 —— 没有外部图片、字体、音频,不联网。',
      '守卫有休闲、标准、困难三档(默认标准):只影响反应时间、瞄准误差、视距和移动速度,枪的伤害、弹匣和射速和玩家完全一样。',
      '6 个成就记在存档里;没有血腥暴力表现:命中是火花、烟和弹壳,倒下的角色只留一个装备标记。',
      '数据只存超级赞云存储,按应用和你的账号隔离:战绩(场次、胜、负、最佳连胜)、累计击杀/安放/命中、成就、上次选的地图、难度和声音开关。不保存进行中的比赛 —— 回合制,关掉就从首页开新局。官方(也就是这个游戏的开发者)不能从服务端读取;平台管理员在技术上能访问数据库,数据没有端到端加密。可以在「我的 → 设置 → 小程序授权与数据」里导出或清空;注销账号时一并删除。',
      '明确不做:多人联机、开箱/饰品、内购、广告、排行榜、体力与签到。',
      '没有广告,没有内购,没有排行榜;成绩只存在你自己这里,不上排行榜、不给别人看。',
      profile.games > 0
        ? `你的战绩:${profile.games} 场,${profile.wins} 胜 ${profile.losses} 负,最佳连胜 ${profile.bestStreak},成就 ${profile.achievements.length}/${ACHIEVEMENTS.length}。`
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

// ---------------------------------------------------------------- 对局弹层

export interface PauseActions {
  round: Round
  match: MatchState
  profile: Profile
  soundOn: () => boolean
  onToggleSound: () => boolean
  onResume: () => void
  onRestart: () => void
  onHome: () => void
  onControls: () => void
  onAbout: () => void
  /** 点空白处 / Esc 关掉时回调(继续游戏) */
  onDismiss: () => void
}

/** 暂停弹层:继续 / 重新开始 / 回首页 / 说明 / 关于 / 声音 */
export function showPause(overlay: Overlay, actions: PauseActions): void {
  const { round, match } = actions
  overlay.show((p) => {
    p.append(el('h2', round.training ? '训练场已暂停' : '已暂停'))
    p.append(el('p', round.training
      ? `无限练习 · 已坚持 ${formatClock(round.elapsed)}`
      : `${round.map.name} · 第 ${match.round} 回合 · 比分 ${match.scorePlayer} : ${match.scoreGuard}`, 'sub'))
    const soundRow = el('div', '', 'soundrow')
    soundRow.append(el('span', '声音'))
    const soundToggle = button(actions.soundOn() ? '开' : '关', () => {
      actions.onToggleSound()
      soundToggle.textContent = actions.soundOn() ? '开' : '关'
      soundToggle.setAttribute('aria-pressed', String(actions.soundOn()))
    })
    soundToggle.setAttribute('aria-pressed', String(actions.soundOn()))
    soundRow.append(soundToggle)
    p.append(soundRow)
    p.append(row(button('继续', () => { overlay.hide(); actions.onResume() }, 'primary')))
    const restart = (): void => {
      void (async () => {
        if (!(await confirmBox(round.training ? '重新开始训练?' : '这一局从头来过?当前比分不保留。'))) return
        overlay.hide()
        actions.onRestart()
      })()
    }
    const home = (): void => {
      void (async () => {
        if (!(await confirmBox(round.training ? '结束训练回首页?' : '结束这一局回首页?没打完的比赛不记战绩。'))) return
        overlay.hide()
        actions.onHome()
      })()
    }
    p.append(row(
      button(round.training ? '重新开始训练' : '重新开始', restart),
      button('回首页', home),
    ))
    p.append(row(
      button('操作说明', () => showControls(overlay, () => overlay.hide())),
      button('关于', () => showAbout(overlay, actions.profile, () => overlay.hide())),
    ))
  }, { cls: 'pause', onDismiss: actions.onDismiss })
}

export interface RoundResultActions {
  match: MatchState
  summary: RoundSummary
  onNext: () => void
  onReport: () => void
}

const REASON_TEXT: Record<string, string> = {
  exploded: '炸弹爆炸,回合拿下。',
  defused: '守卫把炸弹拆掉了。',
  playerKilled: '你被守卫击倒了。',
  timeout: '时间耗尽,炸弹还没安放。',
}

/** 回合结算:比分、本回合击杀、用时;整场结束时按钮变成「查看战报」 */
export function showRoundResult(overlay: Overlay, actions: RoundResultActions): void {
  const { match, summary } = actions
  const won = summary.side === 'player'
  overlay.show((p) => {
    p.append(el('h2', won ? '回合拿下' : '回合失守'))
    p.append(el('p', REASON_TEXT[summary.reason] ?? '', 'sub'))
    const grid = el('div', '', 'statgrid')
    for (const [label, value] of [
      ['本回合击杀', String(summary.kills)],
      ['用时', `${Math.round(summary.seconds)} 秒`],
      ['比分', `${match.scorePlayer} : ${match.scoreGuard}`],
    ] as Array<[string, string]>) {
      const cell = el('div')
      cell.append(el('b', value), el('small', label))
      grid.append(cell)
    }
    p.append(grid)
    p.append(row(match.over
      ? button('查看战报', () => actions.onReport(), 'primary')
      : button('下一回合', () => actions.onNext(), 'primary')))
  }, { cls: won ? 'result-win' : 'result-lose' })
}

export interface MatchResultActions {
  match: MatchState
  profile: Profile
  unlocked: readonly AchievementDef[]
  onRetry: () => void
  onHome: () => void
}

/** 整场结算:胜负、总击杀、安放、命中率、最佳连胜、新成就 */
export function showMatchResult(overlay: Overlay, actions: MatchResultActions): void {
  const { match, profile, unlocked } = actions
  const won = match.over === 'win'
  overlay.show((p) => {
    p.append(el('h2', won ? '行动成功' : '行动失败'))
    p.append(el('p', `${match.scorePlayer} : ${match.scoreGuard} · ${DIFFICULTY_LABELS[match.difficulty]}难度 · ${match.mapId === 'market' ? '霓虹夜市' : '旧仓库'}`, 'substat'))
    const grid = el('div', '', 'statgrid')
    for (const [label, value] of [
      ['总击杀', String(match.stats.kills)],
      ['安放次数', String(match.stats.plants)],
      ['命中率', `${Math.round(accuracyOf(match.stats) * 100)}%`],
      ['最佳连胜', String(profile.bestStreak)],
      ['用时', formatClock(match.stats.seconds)],
    ] as Array<[string, string]>) {
      const cell = el('div')
      cell.append(el('b', value), el('small', label))
      grid.append(cell)
    }
    p.append(grid)
    if (unlocked.length) {
      const box = el('div', '', 'unlocked')
      box.append(el('b', '解锁新成就'))
      for (const def of unlocked) box.append(el('span', `${def.icon} ${def.name}`))
      p.append(box)
    }
    p.append(row(
      button('再来一局', () => actions.onRetry(), 'primary'),
      button('回首页', () => actions.onHome()),
    ))
  }, { cls: won ? 'result-win' : 'result-lose' })
}

function formatClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
