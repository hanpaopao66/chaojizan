// 局内 HUD 与两个底部面板:顶栏(西瓜 HP / 金币 / 波次 / 倍速 / 暂停)、Boss 血条、
// 准备期「提前召唤」、建造卡片、塔的面板、教学提示、aria-live 播报和 toast。
// 所有可点的东西都是真 <button>;金币不够的卡会灰掉并写明差多少。
import { $ } from '../../shared/src/ui'
import {
  EARLY_BONUS, TOWERS, sellValue, themeOf, towerDef, towerStats, upgradeCost,
} from './data'
import { unlockLevelOf, waveCount } from './levels'
import type { GameState, LevelDef, Tower, TowerKind } from './types'

export interface HudCallbacks {
  onPause: () => void
  onSpeed: () => void
  onSummon: () => void
  onBuild: (slot: number, kind: TowerKind) => void
  onUpgrade: (tower: Tower) => void
  onSell: (tower: Tower) => void
  onCloseSheet: () => void
}

const GLYPH: Record<TowerKind, string> = {
  pea: '豆', frost: '冰', pepper: '火', vine: '电', mushroom: '毒', bow: '弓', marigold: '花',
}
/** 图标圆底上的字:底色浅就用深墨,底色深就用白字(保证文字对比度) */
function glyphInk(kind: TowerKind): { color: string; background: string } {
  if (kind === 'mushroom') return { color: '#FFFFFF', background: '#7A4E86' }
  if (kind === 'bow') return { color: '#FFFFFF', background: '#7A5F3E' }
  return { color: '#1B1D16', background: towerDef(kind).color }
}

export class Hud {
  private readonly hp = $('hp')
  private readonly gold = $('gold')
  private readonly wave = $('wave')
  private readonly speed = $<HTMLButtonElement>('speed')
  private readonly pause = $<HTMLButtonElement>('pause')
  private readonly boss = $('boss')
  private readonly bossFill = $('boss-fill')
  private readonly summon = $<HTMLButtonElement>('summon')
  private readonly tip = $('tip')
  private readonly themeTag = $('theme-tag')
  private readonly banner = $('banner')
  private readonly build = $<HTMLDivElement>('build')
  private readonly panel = $<HTMLDivElement>('panel')
  private readonly live = $('live')
  private readonly toastEl = $('toast')
  private readonly cache = new Map<string, string>()
  private bannerTimer = 0
  private toastTimer = 0
  private tipText = ''
  /** 正在建造的建造位(-1 = 没开) */
  buildSlot = -1
  /** 正在看面板的塔 id(0 = 没开) */
  panelTower = 0
  private state: GameState | null = null
  private level: LevelDef | null = null

  bind(cb: HudCallbacks): void {
    this.pause.addEventListener('click', () => cb.onPause())
    this.speed.addEventListener('click', () => cb.onSpeed())
    this.summon.addEventListener('click', () => cb.onSummon())
    // 面板用事件委托:每次打开时重建内容
    this.build.addEventListener('click', (e) => {
      const target = (e.target as HTMLElement).closest('button')
      if (!target) return
      if (target.dataset.action === 'close') {
        cb.onCloseSheet()
        return
      }
      const kind = target.dataset.tower as TowerKind | undefined
      if (kind && this.buildSlot >= 0) cb.onBuild(this.buildSlot, kind)
    })
    this.panel.addEventListener('click', (e) => {
      const target = (e.target as HTMLElement).closest('button')
      if (!target) return
      const action = target.dataset.action
      if (action === 'close') {
        cb.onCloseSheet()
        return
      }
      const tower = this.state?.towers.find((t) => t.id === this.panelTower)
      if (!tower) return
      if (action === 'upgrade') cb.onUpgrade(tower)
      else if (action === 'sell') cb.onSell(tower)
    })
  }

  /** 每帧刷新(只在文字变了才碰 DOM) */
  update(state: GameState, level: LevelDef, tip: string): void {
    this.state = state
    this.level = level
    this.set('hp', `${state.hp}/${state.maxHp}`)
    this.set('gold', String(state.gold))
    const total = waveCount(level)
    this.set('wave', state.endless || !Number.isFinite(total) ? `第 ${Math.max(1, state.wave)} 波` : `${state.wave}/${total}`)
    this.set('speed', state.speed === 2 ? '2×' : '1×')
    if (this.speed.getAttribute('aria-pressed') !== String(state.speed === 2)) {
      this.speed.setAttribute('aria-pressed', String(state.speed === 2))
      this.speed.setAttribute('aria-label', state.speed === 2 ? '当前 2 倍速,点一下切回 1 倍' : '当前 1 倍速,点一下切到 2 倍')
    }
    // Boss 血条
    const boss = state.enemies.find((e) => e.kind === 'boss')
    if (boss) {
      this.boss.hidden = false
      const pct = Math.max(0, Math.min(100, (boss.hp / boss.maxHp) * 100))
      this.bossFill.style.width = `${pct.toFixed(1)}%`
    } else {
      this.boss.hidden = true
    }
    // 提前召唤
    const canSummon = state.phase === 'prep' && !state.over
    if (this.summon.disabled === canSummon) this.summon.disabled = !canSummon
    const summonText = state.phase === 'prep' && !state.over
      ? `提前召唤 +${EARLY_BONUS}`
      : (state.over ? '本局结束' : `第 ${state.wave} 波进行中`)
    this.set('summonText', summonText)
    if (this.summon.textContent !== summonText) this.summon.textContent = summonText
    this.summon.setAttribute('aria-label', state.phase === 'prep'
      ? `提前召唤下一波,立刻开始并奖励 ${EARLY_BONUS} 金币`
      : '波次进行中,不能提前召唤')
    // 提示 / 倒计时
    let text = tip
    if (!text) {
      if (state.over === 'win') text = '瓜田守住了'
      else if (state.over === 'lose') text = '大西瓜被咬坏了'
      else if (state.phase === 'prep') text = `第 ${state.wave + 1} 波:${Math.ceil(state.prep)} 秒后出发,现在可以造塔`
      else text = '虫子来了,守住大西瓜'
    }
    if (text !== this.tipText) {
      this.tipText = text
      this.tip.textContent = text
    }
    this.themeTag.textContent = level.id === 'endless'
      ? '无尽 · 虫巢'
      : `第 ${level.id} 关 · ${themeOf(level.theme).name}`
    if (this.buildSlot >= 0) this.refreshBuildAffordability(state)
    if (this.panelTower > 0) this.refreshPanelAffordability(state)
  }

  private set(key: string, value: string): void {
    if (this.cache.get(key) === value) return
    this.cache.set(key, value)
    if (key === 'hp') this.hp.textContent = value
    else if (key === 'gold') this.gold.textContent = value
    else if (key === 'wave') this.wave.textContent = value
    else if (key === 'speed') this.speed.textContent = value
    else if (key === 'summonText') this.summon.textContent = value
  }

  /** 打开发建造位卡片 */
  openBuild(slot: number, level: LevelDef): void {
    this.closeTowerPanel()
    this.buildSlot = slot
    const state = this.state
    this.build.hidden = false
    this.build.textContent = ''
    const head = document.createElement('div')
    head.className = 'sheet-head'
    const title = document.createElement('b')
    title.textContent = `建造位 ${slot + 1}`
    const close = document.createElement('button')
    close.type = 'button'
    close.className = 'x'
    close.dataset.action = 'close'
    close.setAttribute('aria-label', '收起建造面板')
    close.textContent = '×'
    head.append(title, close)
    this.build.append(head)
    const grid = document.createElement('div')
    grid.className = 'cards'
    for (const kind of level.towers) {
      const def = towerDef(kind)
      const card = document.createElement('button')
      card.type = 'button'
      card.className = 'card'
      card.dataset.tower = kind
      card.setAttribute('aria-label', `${def.name},${def.role},造价 ${def.cost} 金币`)
      const glyph = document.createElement('span')
      glyph.className = 'glyph'
      const ink = glyphInk(kind)
      glyph.style.background = ink.background
      glyph.style.color = ink.color
      glyph.textContent = GLYPH[kind]
      const name = document.createElement('b')
      name.textContent = def.name
      const role = document.createElement('small')
      role.textContent = def.role
      const cost = document.createElement('span')
      cost.className = 'cost'
      cost.textContent = `${def.cost} 金`
      card.append(glyph, name, role, cost)
      if (!state || state.gold < def.cost) card.classList.add('poor')
      grid.append(card)
    }
    // 没解锁的塔也显示出来,让玩家知道后面能造什么
    for (const def of TOWERS) {
      if (level.towers.includes(def.kind)) continue
      const card = document.createElement('button')
      card.type = 'button'
      card.className = 'card locked'
      card.disabled = true
      card.setAttribute('aria-label', `${def.name},第 ${unlockLevelOf(def.kind)} 关解锁`)
      const glyph = document.createElement('span')
      glyph.className = 'glyph'
      const ink = glyphInk(def.kind)
      glyph.style.background = ink.background
      glyph.style.color = ink.color
      glyph.textContent = GLYPH[def.kind]
      const name = document.createElement('b')
      name.textContent = def.name
      const role = document.createElement('small')
      role.textContent = `第${unlockLevelOf(def.kind)}关解锁`
      card.append(glyph, name, role)
      grid.append(card)
    }
    this.build.append(grid)
    if (state) this.refreshBuildAffordability(state)
  }

  /** 金币变化时刷新卡片的灰度和「还差多少」 */
  private refreshBuildAffordability(state: GameState): void {
    const level = this.level
    if (!level) return
    for (const card of this.build.querySelectorAll<HTMLButtonElement>('.card')) {
      const kind = card.dataset.tower as TowerKind | undefined
      if (!kind) continue
      const cost = towerDef(kind).cost
      const can = state.gold >= cost
      card.classList.toggle('poor', !can)
      const costEl = card.querySelector('.cost')
      if (costEl) costEl.textContent = can ? `${cost} 金` : `还差 ${cost - state.gold}`
    }
  }

  /** 打开塔的面板(升级 / 卖出) */
  openTower(tower: Tower, _level: LevelDef): void {
    this.closeBuild()
    this.panelTower = tower.id
    const def = towerDef(tower.kind)
    const stats = towerStats(tower.kind, tower.level)
    this.panel.hidden = false
    this.panel.textContent = ''
    const head = document.createElement('div')
    head.className = 'sheet-head'
    const title = document.createElement('b')
    title.textContent = `${def.name} · ${tower.level} 级`
    const close = document.createElement('button')
    close.type = 'button'
    close.className = 'x'
    close.dataset.action = 'close'
    close.setAttribute('aria-label', '收起塔的面板')
    close.textContent = '×'
    head.append(title, close)
    this.panel.append(head)
    const line = document.createElement('p')
    line.className = 'statline'
    line.textContent = tower.kind === 'marigold'
      ? `每波产出 ${stats.goldPerWave} 金币 · 不攻击`
      : `伤害 ${stats.damage} · 攻速 ${stats.rate}/秒 · 射程 ${stats.range} 格${stats.splash ? ` · 溅射 ${stats.splash} 格` : ''}${stats.chain ? ` · 链电 ${stats.chain}` : ''}`
    const desc = document.createElement('p')
    desc.className = 'desc'
    desc.textContent = def.desc
    this.panel.append(line, desc)
    const actions = document.createElement('div')
    actions.className = 'sheet-actions'
    const up = document.createElement('button')
    up.type = 'button'
    up.className = 'primary up'
    up.dataset.action = 'upgrade'
    const sell = document.createElement('button')
    sell.type = 'button'
    sell.className = 'sell'
    sell.dataset.action = 'sell'
    sell.textContent = `卖出 +${sellValue(tower.invested)}`
    sell.setAttribute('aria-label', `卖掉${def.name},返还 ${sellValue(tower.invested)} 金币`)
    actions.append(up, sell)
    this.panel.append(actions)
    const state = this.state
    if (state) this.refreshPanelAffordability(state)
  }

  /** 金币变化时刷新升级按钮 */
  private refreshPanelAffordability(state: GameState): void {
    const tower = state.towers.find((t) => t.id === this.panelTower)
    if (!tower) {
      this.closeTowerPanel()
      return
    }
    const up = this.panel.querySelector<HTMLButtonElement>('[data-action="upgrade"]')
    if (!up) return
    if (tower.level >= 3) {
      up.disabled = true
      up.textContent = '已满级'
      up.setAttribute('aria-label', '这座塔已经满级了')
      return
    }
    const cost = upgradeCost(tower.kind, tower.level)
    const can = state.gold >= cost
    up.disabled = false
    up.textContent = can ? `升到 ${tower.level + 1} 级 · ${cost} 金` : `升到 ${tower.level + 1} 级 · 还差 ${cost - state.gold}`
    up.setAttribute('aria-label', `把${towerDef(tower.kind).name}升到 ${tower.level + 1} 级,花费 ${cost} 金币`)
  }

  closeBuild(): void {
    this.build.hidden = true
    this.build.textContent = ''
    this.buildSlot = -1
  }

  closeTowerPanel(): void {
    this.panel.hidden = true
    this.panel.textContent = ''
    this.panelTower = 0
  }

  closeSheets(): void {
    this.closeBuild()
    this.closeTowerPanel()
  }

  get sheetOpen(): boolean {
    return this.buildSlot >= 0 || this.panelTower > 0
  }

  /** 顶部飘过的一句话(波次开始 / Boss / 胜负) */
  showBanner(text: string, tone: 'good' | 'warn' | 'bad' = 'good', ms = 1600): void {
    this.banner.textContent = text
    this.banner.className = `banner show ${tone}`
    this.banner.hidden = false
    window.clearTimeout(this.bannerTimer)
    this.bannerTimer = window.setTimeout(() => {
      this.banner.hidden = true
      this.banner.className = 'banner'
    }, ms)
  }

  /** 读屏播报(同一条重复也要能播出来) */
  announce(text: string): void {
    this.live.textContent = ''
    window.setTimeout(() => {
      this.live.textContent = text
    }, 20)
  }

  toast(text: string): void {
    this.toastEl.textContent = text
    this.toastEl.hidden = false
    this.toastEl.classList.remove('show')
    void this.toastEl.offsetWidth
    this.toastEl.classList.add('show')
    window.clearTimeout(this.toastTimer)
    this.toastTimer = window.setTimeout(() => {
      this.toastEl.hidden = true
    }, 2400)
  }

  /** 结算时收掉所有面板 */
  reset(): void {
    this.closeSheets()
    this.boss.hidden = true
    this.banner.hidden = true
    this.cache.clear()
  }

  /** 当前关卡和地图(给 main 判断用) */
  currentLevel(): LevelDef | null {
    return this.level
  }
}
