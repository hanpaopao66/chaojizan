/*!
 * 超级赞小程序 SDK v2 —— window.SuperZ.WebApp(DEV-PROMPTS-39 §5.4、#323)
 *
 * 用法:托管页在 <head> 里同源引一份(每个托管 origin 下都有):
 *
 *   <script src="/_sdk/2/sz-webapp.js"></script>
 *   <script>
 *     const app = SuperZ.WebApp
 *     app.ready()
 *     fetch('https://你的后端/login', {method: 'POST', body: app.initData})  // 后端验签
 *   </script>
 *
 * 或者把 SDK 打进自己的包:`import { WebApp } from '@superz/miniapp-sdk'`。
 *
 * ## 协议(和宿主两端逐字一致,改一处三处一起改)
 *
 * - 启动参数在 URL 片段里(§5.2):加载时同步读,读完用 history.replaceState 抹掉,
 *   存进 sessionStorage(页面在 WebView 里刷新仍可用;复制地址不会把身份包带出去);
 * - 消息体 {v:2, type, id, method, params, token}:
 *   页面 → 宿主:hello(握手)、call(调用)、notice(CSP 违规等,宿主可以不理)、pong(应答宿主的 ping);
 *   宿主 → 页面:init(带会话令牌与初始状态)、reply、event、ping(网页版确认页面还是这个小程序);
 * - **会话令牌**:宿主每次加载生成、只发给主框架。不带或带错令牌的调用一律被宿主丢弃 ——
 *   原生 JS 通道对页面里所有 frame 都可见,光看主框架 URL 挡不住 iframe 冒充;
 * - 传输:手机端是原生注入的 SuperzBridge 通道(宿主经 window.__szReceive 回话),
 *   web 端是跨域 iframe + postMessage(只认 event.source === window.parent)。
 *
 * 所有方法返回 Promise;同时兼容 Telegram 风格的回调参数。不在宿主里时 inHost=false,调用回 4008。
 * 本地调试加 `?sz_mock=1`:弹窗用浏览器原生、云存储落 localStorage、initData 带 mock=1
 * 且**签名必然无效** —— 开发者后端照常验签就会拒绝,没人能拿 mock 冒充真用户。
 *
 * 同时挂 window.Telegram.WebApp:Telegram Mini App 的前端把 telegram-web-app.js 换成这个地址就能跑(2.1.0 起)。
 */

export const SDK_VERSION = '2.1.0'

/**
 * 这份 SDK 说的宿主协议版本。`?sz_mock=1` 时就当宿主是这个版本。
 * 2.1:所有应用都能全屏、setBottomBarColor、主题色 16 个键(Telegram 的 15 个 + line_color)。
 */
const PROTOCOL_VERSION = '2.1'

// ---------------------------------------------------------------- 类型

export type ColorScheme = 'light' | 'dark'
export type Platform = 'android' | 'ios' | 'web' | 'unknown'

/** 键名和 Telegram 的 ThemeParams 一致(15 个),多一个超级赞自己的 line_color。值都是 #RRGGBB */
export interface ThemeParams {
  bg_color?: string
  secondary_bg_color?: string
  text_color?: string
  hint_color?: string
  link_color?: string
  button_color?: string
  button_text_color?: string
  accent_text_color?: string
  destructive_text_color?: string
  header_bg_color?: string
  bottom_bar_bg_color?: string
  section_bg_color?: string
  section_header_text_color?: string
  section_separator_color?: string
  subtitle_text_color?: string
  /** 超级赞多出来的:发丝线(Telegram 没有这个键) */
  line_color?: string
}

export interface SafeAreaInset { top: number; bottom: number; left: number; right: number }

export interface WebAppUser {
  open_id: string
  language_code?: string
  /** 用户同意过 requestProfile 的应用才有 */
  nickname?: string
  avatar_url?: string
}

export interface InitDataUnsafe {
  app_id?: string
  auth_date?: number
  launch_id?: string
  user?: WebAppUser
  start_param?: string
  /** 模拟器启动时是 'sim':你的后端应据此区分测试流量 */
  env?: string
  sig_kid?: string
  hash?: string
  signature?: string
}

export interface PopupButton {
  id?: string
  type?: 'default' | 'ok' | 'close' | 'cancel' | 'destructive'
  text?: string
}

export interface PopupParams { title?: string; message: string; buttons?: PopupButton[] }

export interface BottomButtonParams {
  text?: string
  /** #RRGGBB;传 null / false 回到默认色(跟主题走) */
  color?: string | null | false
  text_color?: string | null | false
  is_visible?: boolean
  is_active?: boolean
  is_progress_visible?: boolean
  /** 和 Telegram 一样收下;宿主暂不画闪光 */
  has_shine_effect?: boolean
  /** 只有 SecondaryButton 用:相对主按钮的位置 */
  position?: 'left' | 'right' | 'top' | 'bottom'
}

export interface StoredItem { value: string; rev: number }

export type EventName =
  | 'themeChanged' | 'viewportChanged' | 'safeAreaChanged' | 'contentSafeAreaChanged'
  | 'mainButtonClicked' | 'secondaryButtonClicked' | 'backButtonClicked' | 'settingsButtonClicked'
  | 'popupClosed' | 'activated' | 'deactivated' | 'fullscreenChanged' | 'fullscreenFailed'

/** 桥错误码(§5.4)。页面按 code 判断,不按 message —— message 会改措辞,code 不会。 */
export const ERRORS = {
  CAPABILITY_NOT_GRANTED: 4001,
  USER_DENIED: 4002,
  NOT_SUPPORTED: 4003,
  INVALID_PARAMS: 4004,
  RATE_LIMITED: 4005,
  QUOTA_EXCEEDED: 4006,
  REV_CONFLICT: 4007,
  NOT_IN_HOST: 4008,
  APP_SUSPENDED: 4009,
  INTERNAL: 5000,
  NETWORK: 5001,
} as const

export class SzError extends Error {
  code: number
  constructor(code: number, message: string) {
    super(message)
    this.name = 'SzError'
    this.code = code
  }
}

/** 线上的方法名(宿主的分发表按它注册;文档参考页由 scripts/check_sdk_docs.mjs 对照) */
export const BRIDGE_METHODS = [
  'ready', 'expand', 'close', 'setHeaderColor', 'setBackgroundColor', 'setBottomBarColor',
  'setClosingConfirmation', 'mainButton', 'secondaryButton', 'backButton', 'settingsButton', 'haptic',
  'showPopup', 'openLink', 'share', 'CloudStorage.getItems', 'CloudStorage.setItem',
  'CloudStorage.removeItems', 'CloudStorage.getKeys', 'requestFullscreen', 'exitFullscreen',
  'lockOrientation', 'unlockOrientation', 'requestProfile', 'legacy.getInitData',
] as const

// ---------------------------------------------------------------- 环境

const w: any = typeof window !== 'undefined' ? window : {}
const LAUNCH_KEY = '__szLaunch'
const CALL_TIMEOUT = 30000
const HELLO_TIMEOUT = 3000

function readLaunch(): Record<string, string> {
  let out: Record<string, string> = {}
  const hash = String(w.location?.hash || '').replace(/^#/, '')
  if (/(^|&)szWebApp(Data|Version)=/.test(hash)) {
    new URLSearchParams(hash).forEach((v, k) => { out[k] = v })
    try { w.sessionStorage?.setItem(LAUNCH_KEY, JSON.stringify(out)) } catch (_) { /* 无存储 */ }
    try {
      w.history?.replaceState(w.history.state, '', w.location.pathname + w.location.search)
    } catch (_) { /* 老 WebView */ }
  } else {
    try { out = JSON.parse(w.sessionStorage?.getItem(LAUNCH_KEY) || '{}') || {} } catch (_) { out = {} }
  }
  return out
}

function parseInitData(raw: string): InitDataUnsafe {
  const o: any = {}
  if (!raw) return o
  new URLSearchParams(raw).forEach((v, k) => { o[k] = v })
  if (o.user) { try { o.user = JSON.parse(o.user) } catch (_) { delete o.user } }
  if (o.auth_date) o.auth_date = Number(o.auth_date)
  return o
}

function parseJson<T>(s: string | undefined, fallback: T): T {
  try { return s ? (JSON.parse(s) as T) : fallback } catch (_) { return fallback }
}

function versionAtLeast(have: string, want: string): boolean {
  const a = String(have).split('.').map(Number)
  const b = String(want).split('.').map(Number)
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] || 0
    const y = b[i] || 0
    if (x !== y) return x > y
  }
  return true
}

function brightness(hex: string | undefined): ColorScheme | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '')
  if (!m) return null
  const n = parseInt(m[1], 16)
  const lum = (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255
  return lum < 0.5 ? 'dark' : 'light'
}

/** '#RRGGBB'、'#RGB'、'rgb(r, g, b)' → '#RRGGBB'(和 Telegram 收的写法一样);认不出回 null */
function toHex(color: unknown): string | null {
  const s = String(color ?? '').trim()
  let m = /^#([0-9a-f]{6})$/i.exec(s)
  if (m) return '#' + m[1].toUpperCase()
  m = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(s)
  if (m) return ('#' + m[1] + m[1] + m[2] + m[2] + m[3] + m[3]).toUpperCase()
  m = /^rgba?\((\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})(?:,\s*[\d.]+)?\)$/i.exec(s)
  if (m && [m[1], m[2], m[3]].every((x) => Number(x) <= 255)) {
    return '#' + [m[1], m[2], m[3]].map((x) => Number(x).toString(16).padStart(2, '0')).join('').toUpperCase()
  }
  return null
}

/**
 * 老宿主(协议 2.0)只下发 10 个主题色。缺的 Telegram 键按新宿主的取法补上(和 App 的 theme.dart 同一张对应表),
 * 页面在新老 App 里读到的是同一套键。宿主给了的不动。
 */
const DERIVED_THEME: Array<[keyof ThemeParams, keyof ThemeParams]> = [
  ['header_bg_color', 'bg_color'],
  ['bottom_bar_bg_color', 'secondary_bg_color'],
  ['section_bg_color', 'secondary_bg_color'],
  ['section_header_text_color', 'hint_color'],
  ['section_separator_color', 'line_color'],
  ['subtitle_text_color', 'hint_color'],
]

function withDerived(t: ThemeParams | null | undefined): ThemeParams {
  const out: ThemeParams = { ...(t || {}) }
  for (const [key, from] of DERIVED_THEME) {
    if (!out[key] && out[from]) out[key] = out[from]
  }
  return out
}

// ---------------------------------------------------------------- 传输

type Pending = { resolve: (v: any) => void; reject: (e: SzError) => void; timer: any }
type Listener = (data?: any) => void

const launch = readLaunch()
const mock = !!w.location && /[?&]sz_mock=1(&|$)/.test(String(w.location.search || ''))
const native = w.SuperzBridge && typeof w.SuperzBridge.postMessage === 'function' ? w.SuperzBridge : null
const parentWin = !native && w.parent && w.parent !== w ? w.parent : null

let token = ''
let hostOrigin = '*'
let seq = 0
let initialized = false
let inHost = !!(native || parentWin)
const pending: Record<number, Pending> = {}
const queue: Array<{ send: () => void; fail: () => void }> = []
const listeners: Record<string, Listener[]> = {}

function post(msg: any): void {
  if (native) native.postMessage(JSON.stringify(msg))
  else if (parentWin) parentWin.postMessage({ __sz: 2, ...msg }, hostOrigin)
}

function call<T = any>(method: string, params: any = {}, timeout = CALL_TIMEOUT): Promise<T> {
  if (mock) return mockHost(method, params) as Promise<T>
  return new Promise<T>((resolve, reject) => {
    if (!inHost) {
      reject(new SzError(ERRORS.NOT_IN_HOST, '不在超级赞里打开,这个功能用不了'))
      return
    }
    const send = () => {
      const id = ++seq
      pending[id] = {
        resolve, reject,
        timer: setTimeout(() => {
          delete pending[id]
          reject(new SzError(ERRORS.INTERNAL, '宿主没有应答'))
        }, timeout),
      }
      post({ v: 2, type: 'call', id, method, params, token })
    }
    if (initialized) send()
    else queue.push({ send, fail: () => reject(new SzError(ERRORS.NOT_IN_HOST, '不在超级赞里打开,这个功能用不了')) })
  })
}

function emit(name: string, data?: any): void {
  for (const fn of (listeners[name] || []).slice()) {
    try { fn.call(WebApp, data) } catch (e) { setTimeout(() => { throw e }) }
  }
}

function receive(msg: any): void {
  if (!msg || msg.v !== 2) return
  if (msg.type === 'init') {
    if (initialized && msg.token !== token) return
    token = String(msg.token || '')
    applyInit(msg)
    initialized = true
    inHost = true
    queue.splice(0).forEach((q) => q.send())
    return
  }
  if (msg.type === 'reply') {
    const p = pending[msg.id]
    if (!p) return
    delete pending[msg.id]
    clearTimeout(p.timer)
    if (msg.ok) p.resolve(msg.data)
    else p.reject(new SzError(Number(msg.error?.code) || ERRORS.INTERNAL, String(msg.error?.message || '调用失败')))
    return
  }
  if (msg.type === 'event') applyEvent(String(msg.name), msg.data)
  if (msg.type === 'ping') {
    // 网页版宿主在 iframe 每次加载后问一声「还是这个小程序吗」:它的 targetOrigin 写的是托管 origin,
    // 只有托管 origin 上的页面收得到。回一声就行,不带令牌(页面跳去别的站后,这一问没人答 → 宿主停止显示)
    post({ v: 2, type: 'pong', nonce: String(msg.nonce || '') })
  }
}

if (native) {
  // 宿主只在主框架里执行这句 —— 页面里嵌的 iframe 收不到令牌
  w.__szReceive = (m: any) => receive(typeof m === 'string' ? parseJson(m, null) : m)
}
if (parentWin && w.addEventListener) {
  w.addEventListener('message', (e: MessageEvent) => {
    if (e.source !== parentWin) return
    const d: any = e.data
    if (!d || d.__sz !== 2) return
    if (d.type === 'init' && e.origin && e.origin !== 'null') hostOrigin = e.origin
    receive(d)
  })
}

// ---------------------------------------------------------------- 状态

const SIDES = ['top', 'bottom', 'left', 'right'] as const

const state = {
  version: launch.szWebAppVersion || '2.0',
  platform: (launch.szWebAppPlatform || (native ? 'unknown' : 'web')) as Platform,
  themeParams: withDerived(parseJson<ThemeParams>(launch.szWebAppThemeParams, {})),
  colorScheme: 'light' as ColorScheme,
  viewportHeight: w.innerHeight || 0,
  viewportStableHeight: w.innerHeight || 0,
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 } as SafeAreaInset,
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 } as SafeAreaInset,
  isExpanded: false,
  isFullscreen: false,
  isOrientationLocked: false,
  isActive: true,
  isClosingConfirmationEnabled: false,
  capabilities: [] as string[],
  initData: launch.szWebAppData || '',
}
state.colorScheme = brightness(state.themeParams.bg_color) || 'light'

/**
 * 页面设的三处颜色,记的是「写法」:#RRGGBB,或者一个主题色的键('bg_color' 这类,和 Telegram 一样)。
 * 写的是键的,宿主换主题时 SDK 按新主题重新算一遍发过去 —— 顶栏跟着亮暗走。空串 = 没设过(用宿主默认)。
 */
const colorSpec = { header: '', background: '', bottomBar: '' }
const COLOR_KEYS: Record<keyof typeof colorSpec, string[]> = {
  header: ['bg_color', 'secondary_bg_color', 'header_bg_color'],
  background: ['bg_color', 'secondary_bg_color'],
  bottomBar: ['bg_color', 'secondary_bg_color', 'bottom_bar_bg_color'],
}
const COLOR_METHOD: Record<keyof typeof colorSpec, string> = {
  header: 'setHeaderColor', background: 'setBackgroundColor', bottomBar: 'setBottomBarColor',
}
const COLOR_DEFAULT: Record<keyof typeof colorSpec, Array<keyof ThemeParams>> = {
  header: ['header_bg_color', 'bg_color'],
  background: ['bg_color'],
  bottomBar: ['bottom_bar_bg_color', 'secondary_bg_color'],
}

function resolveColor(spec: string): string {
  return spec.charAt(0) === '#' ? spec : String((state.themeParams as any)[spec] || '')
}

/** 现在实际的颜色:页面设过的,否则主题里的默认(Telegram 的 headerColor 等也是这么读的) */
function effectiveColor(which: keyof typeof colorSpec): string {
  const own = colorSpec[which] && resolveColor(colorSpec[which])
  if (own) return own
  for (const k of COLOR_DEFAULT[which]) if (state.themeParams[k]) return state.themeParams[k] as string
  return ''
}

function setColor(which: keyof typeof colorSpec, color: string): Promise<void> {
  const key = COLOR_KEYS[which].indexOf(String(color)) >= 0 ? String(color) : ''
  const spec = key || toHex(color)
  const hex = spec ? resolveColor(spec) : ''
  if (!spec || !hex) {
    return Promise.reject(new SzError(ERRORS.INVALID_PARAMS,
      `颜色要写 #RRGGBB,或者主题色的键:${COLOR_KEYS[which].join(' / ')}`))
  }
  colorSpec[which] = spec
  return call(COLOR_METHOD[which], { color: hex }).then(() => undefined)
}

/** Telegram 的 contentSafeAreaInset 是在安全区**里面**再让出的那一截(两者相加才是总边距);超级赞的是从屏幕边算起的总边距 */
function tgContentInset(): SafeAreaInset {
  const out = { top: 0, bottom: 0, left: 0, right: 0 }
  for (const side of SIDES) {
    out[side] = Math.max(0, (Number(state.contentSafeAreaInset[side]) || 0) - (Number(state.safeAreaInset[side]) || 0))
  }
  return out
}

function cssVars(): void {
  const root = w.document?.documentElement
  if (!root?.style) return
  const set = (k: string, v: string) => root.style.setProperty(k, v)
  // 每个变量同时写超级赞(--sz-*)和 Telegram(--tg-*)两个名字:Telegram 的页面换了 script 就能读到
  for (const [k, v] of Object.entries(state.themeParams)) {
    if (typeof v !== 'string') continue
    const name = k.replace(/_/g, '-')
    set(`--sz-theme-${name}`, v)
    set(`--tg-theme-${name}`, v)
  }
  set('--tg-color-scheme', state.colorScheme)
  for (const p of ['sz', 'tg']) {
    set(`--${p}-viewport-height`, `${state.viewportHeight}px`)
    set(`--${p}-viewport-stable-height`, `${state.viewportStableHeight}px`)
  }
  const tg = tgContentInset()
  for (const side of SIDES) {
    const safe = `${Number(state.safeAreaInset[side]) || 0}px`
    set(`--sz-safe-area-inset-${side}`, safe)
    set(`--tg-safe-area-inset-${side}`, safe)
    set(`--sz-content-safe-area-inset-${side}`, `${Number(state.contentSafeAreaInset[side]) || 0}px`)
    set(`--tg-content-safe-area-inset-${side}`, `${tg[side]}px`)
  }
  root.style.colorScheme = state.colorScheme
}

/** 主题换了:写成主题色键的那几处颜色按新主题重发(顶栏、容器底色、底栏跟着亮暗走) */
function resyncKeyedColors(before: ThemeParams): void {
  for (const which of Object.keys(colorSpec) as Array<keyof typeof colorSpec>) {
    const spec = colorSpec[which]
    if (!spec || spec.charAt(0) === '#') continue
    const hex = resolveColor(spec)
    if (hex && hex !== (before as any)[spec]) call(COLOR_METHOD[which], { color: hex }).catch(() => undefined)
  }
}

function applyInit(m: any): void {
  if (m.version) state.version = String(m.version)
  if (m.platform) state.platform = m.platform
  if (m.themeParams) state.themeParams = withDerived(m.themeParams)
  state.colorScheme = m.colorScheme || brightness(state.themeParams.bg_color) || 'light'
  if (m.viewport) {
    state.viewportHeight = Number(m.viewport.height) || state.viewportHeight
    state.viewportStableHeight = Number(m.viewport.stableHeight) || state.viewportHeight
    state.isExpanded = !!m.viewport.isExpanded
  }
  if (m.safeArea) state.safeAreaInset = m.safeArea
  if (m.contentSafeArea) state.contentSafeAreaInset = m.contentSafeArea
  if (Array.isArray(m.capabilities)) state.capabilities = m.capabilities
  state.isFullscreen = !!m.isFullscreen
  cssVars()
}

function applyEvent(name: string, d: any): void {
  switch (name) {
    case 'themeChanged': {
      const before = state.themeParams
      state.themeParams = withDerived(d?.themeParams || state.themeParams)
      state.colorScheme = d?.colorScheme || brightness(state.themeParams.bg_color) || state.colorScheme
      cssVars()
      resyncKeyedColors(before)
      break
    }
    case 'viewportChanged':
      state.viewportHeight = Number(d?.height) || state.viewportHeight
      if (d?.isStateStable) state.viewportStableHeight = state.viewportHeight
      state.isExpanded = !!d?.isExpanded
      cssVars()
      break
    case 'safeAreaChanged':
      state.safeAreaInset = d || state.safeAreaInset
      cssVars()
      break
    case 'contentSafeAreaChanged':
      state.contentSafeAreaInset = d || state.contentSafeAreaInset
      cssVars()
      break
    case 'fullscreenChanged':
      state.isFullscreen = !!d?.isFullscreen
      break
    case 'fullscreenFailed':
      // 和 Telegram 同样的 error 字段;老宿主(2.0)发的没有,补成 UNSUPPORTED
      d = { ...(d || {}), error: d?.error || 'UNSUPPORTED' }
      if (d.error === 'ALREADY_FULLSCREEN') state.isFullscreen = true
      break
    case 'activated':
    case 'deactivated':
      state.isActive = name === 'activated'
      break
    case 'mainButtonClicked':
      MainButton._fire()
      break
    case 'secondaryButtonClicked':
      SecondaryButton._fire()
      break
    case 'backButtonClicked':
      BackButton._fire()
      break
    case 'settingsButtonClicked':
      SettingsButton._fire()
      break
    case 'clearLocalData':
      // 用户在宿主的「···→ 清除数据」里点的:web 端宿主碰不到跨域 iframe 的存储,由 SDK 在页面里清
      try { w.localStorage?.clear(); w.sessionStorage?.clear() } catch (_) { /* 无存储 */ }
      break
  }
  emit(name, d)
}

// ---------------------------------------------------------------- 按钮

/**
 * 底栏按钮。属性读写和 Telegram 的 BottomButton 一样:直接赋值(`MainButton.text = '下单'`)也会同步给宿主;
 * color / textColor 没设时读到的是跟主题走的默认色。
 */
class BottomButton {
  private _text: string
  private _color = ''
  private _textColor = ''
  private _visible = false
  private _active = true
  private _progress = false
  private _shine = false
  private _position: NonNullable<BottomButtonParams['position']> = 'left'
  private handlers: Listener[] = []
  private scheduled = false

  constructor(private method: 'mainButton' | 'secondaryButton', text: string) {
    this._text = text
  }

  /** 'main' / 'secondary'(Telegram 的 BottomButton.type) */
  get type(): 'main' | 'secondary' { return this.method === 'mainButton' ? 'main' : 'secondary' }
  get text(): string { return this._text }
  set text(v: string) { this.setParams({ text: v }) }
  get color(): string {
    if (this._color) return this._color
    return (this.method === 'mainButton' ? state.themeParams.button_color : effectiveColor('bottomBar')) || ''
  }
  set color(v: string) { this.setParams({ color: v }) }
  get textColor(): string {
    if (this._textColor) return this._textColor
    return (this.method === 'mainButton' ? state.themeParams.button_text_color : state.themeParams.button_color) || ''
  }
  set textColor(v: string) { this.setParams({ text_color: v }) }
  get isVisible(): boolean { return this._visible }
  set isVisible(v: boolean) { this.setParams({ is_visible: v }) }
  get isActive(): boolean { return this._active }
  set isActive(v: boolean) { this.setParams({ is_active: v }) }
  get isProgressVisible(): boolean { return this._progress }
  get hasShineEffect(): boolean { return this._shine }
  set hasShineEffect(v: boolean) { this.setParams({ has_shine_effect: v }) }
  get position(): NonNullable<BottomButtonParams['position']> { return this._position }
  set position(v: NonNullable<BottomButtonParams['position']>) { this.setParams({ position: v }) }

  /** @internal */
  _fire(): void {
    if (!this._active) return
    for (const fn of this.handlers.slice()) fn()
  }

  private _sync(): this {
    // 同一轮里连着改几个属性(setText + show),只发一次。颜色只发页面自己设的,没设 = 宿主按主题画
    if (!this.scheduled) {
      this.scheduled = true
      Promise.resolve().then(() => {
        this.scheduled = false
        call(this.method, {
          text: this._text, color: this._color, text_color: this._textColor,
          is_visible: this._visible, is_active: this._active,
          is_progress_visible: this._progress, has_shine_effect: this._shine, position: this._position,
        }).catch(() => undefined)
      })
    }
    return this
  }

  setText(text: string): this { return this.setParams({ text }) }
  show(): this { return this.setParams({ is_visible: true }) }
  hide(): this { return this.setParams({ is_visible: false }) }
  enable(): this { return this.setParams({ is_active: true }) }
  disable(): this { return this.setParams({ is_active: false }) }
  /** 显示加载中。和 Telegram 一样:不传 leaveActive 时按钮在加载中不可点 */
  showProgress(leaveActive?: boolean): this {
    this._active = !!leaveActive
    this._progress = true
    return this._sync()
  }
  /** 取消加载中,按钮回到可点(Telegram 同样如此) */
  hideProgress(): this {
    this._active = true
    this._progress = false
    return this._sync()
  }
  setParams(p: BottomButtonParams): this {
    if (p.text !== undefined) this._text = String(p.text).trim().slice(0, 64)
    if (p.color !== undefined) this._color = p.color === null || p.color === false ? '' : toHex(p.color) || this._color
    if (p.text_color !== undefined) {
      this._textColor = p.text_color === null || p.text_color === false ? '' : toHex(p.text_color) || this._textColor
    }
    if (p.is_visible !== undefined) this._visible = !!p.is_visible
    if (p.is_active !== undefined) this._active = !!p.is_active
    if (p.is_progress_visible !== undefined) this._progress = !!p.is_progress_visible
    if (p.has_shine_effect !== undefined) this._shine = !!p.has_shine_effect
    if (p.position && ['left', 'right', 'top', 'bottom'].indexOf(p.position) >= 0) this._position = p.position
    return this._sync()
  }
  onClick(fn: Listener): this { this.handlers.push(fn); return this }
  offClick(fn: Listener): this { this.handlers = this.handlers.filter((h) => h !== fn); return this }
}

class HeaderButton {
  private _visible = false
  private handlers: Listener[] = []
  constructor(private method: 'backButton' | 'settingsButton') {}
  get isVisible(): boolean { return this._visible }
  set isVisible(v: boolean) { if (v) this.show(); else this.hide() }
  /** @internal */
  _fire(): void { for (const fn of this.handlers.slice()) fn() }
  show(): this { this._visible = true; call(this.method, { is_visible: true }).catch(() => undefined); return this }
  hide(): this { this._visible = false; call(this.method, { is_visible: false }).catch(() => undefined); return this }
  onClick(fn: Listener): this { this.handlers.push(fn); return this }
  offClick(fn: Listener): this { this.handlers = this.handlers.filter((h) => h !== fn); return this }
}

const MainButton = new BottomButton('mainButton', '继续')
const SecondaryButton = new BottomButton('secondaryButton', '取消')
const BackButton = new HeaderButton('backButton')
const SettingsButton = new HeaderButton('settingsButton')

// ---------------------------------------------------------------- 回调兼容

function withCb<T>(p: Promise<T>, cb?: (...a: any[]) => void, errFirst = false): Promise<T> {
  if (typeof cb === 'function') {
    p.then((v) => (errFirst ? cb(null, v) : cb(v)), (e) => (errFirst ? cb(e) : undefined))
  }
  return p
}

// ---------------------------------------------------------------- 云存储

const CloudStorage = {
  /** 写一个键。带 ifRev 时版本不符回 4007(REV_CONFLICT);ifRev=0 表示「必须还不存在」 */
  setItem(key: string, value: string, opts?: { ifRev?: number } | ((e: any, r?: any) => void),
    cb?: (e: any, r?: { key: string; rev: number }) => void): Promise<{ key: string; rev: number }> {
    if (typeof opts === 'function') { cb = opts; opts = undefined }
    const ifRev = (opts as any)?.ifRev
    return withCb(call('CloudStorage.setItem',
      ifRev === undefined ? { key, value } : { key, value, if_rev: ifRev }), cb, true)
  },
  getItem(key: string, cb?: (e: any, v?: string | null) => void): Promise<string | null> {
    return withCb(CloudStorage.getItemsWithRev([key]).then((r) => r[key]?.value ?? null), cb, true)
  },
  getItems(keys: string[], cb?: (e: any, v?: Record<string, string | null>) => void):
    Promise<Record<string, string | null>> {
    return withCb(CloudStorage.getItemsWithRev(keys).then((r) => {
      const o: Record<string, string | null> = {}
      for (const k of keys) o[k] = r[k]?.value ?? null
      return o
    }), cb, true)
  },
  /** 带版本号读(做 ifRev 并发控制时用)。一次最多 100 个键 */
  getItemsWithRev(keys: string[]): Promise<Record<string, StoredItem | null>> {
    return call<{ items: Record<string, StoredItem | null> }>('CloudStorage.getItems', { keys })
      .then((r) => r.items || {})
  },
  removeItem(key: string, cb?: (e: any, ok?: boolean) => void): Promise<boolean> {
    return withCb(CloudStorage.removeItems([key]), cb, true)
  },
  removeItems(keys: string[], cb?: (e: any, ok?: boolean) => void): Promise<boolean> {
    return withCb(call('CloudStorage.removeItems', { keys }).then(() => true), cb, true)
  },
  /** 列键。prefix 可选;超过 limit 时用返回的 next_cursor 翻页 */
  getKeys(opts?: { prefix?: string; cursor?: string; limit?: number } | ((e: any, k?: string[]) => void),
    cb?: (e: any, k?: string[]) => void): Promise<string[]> {
    if (typeof opts === 'function') { cb = opts; opts = undefined }
    const o = (opts || {}) as { prefix?: string; cursor?: string; limit?: number }
    return withCb(CloudStorage.getKeysPage(o).then(async (page) => {
      let keys = page.keys
      let next = page.next_cursor
      while (next && !o.limit) {
        const more = await CloudStorage.getKeysPage({ ...o, cursor: next })
        keys = keys.concat(more.keys)
        next = more.next_cursor
      }
      return keys
    }), cb, true)
  },
  getKeysPage(o: { prefix?: string; cursor?: string; limit?: number } = {}):
    Promise<{ keys: string[]; next_cursor: string | null }> {
    return call('CloudStorage.getKeys', { prefix: o.prefix || '', cursor: o.cursor || '', limit: o.limit || 500 })
  },
}

// ---------------------------------------------------------------- 触感

const HapticFeedback = {
  impactOccurred(style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft' = 'light') {
    call('haptic', { type: 'impact', style }).catch(() => undefined)
    return HapticFeedback
  },
  notificationOccurred(type: 'error' | 'success' | 'warning' = 'success') {
    call('haptic', { type: 'notification', style: type }).catch(() => undefined)
    return HapticFeedback
  },
  selectionChanged() {
    call('haptic', { type: 'selection' }).catch(() => undefined)
    return HapticFeedback
  },
}

// ---------------------------------------------------------------- WebApp

function showPopup(params: PopupParams, cb?: (buttonId: string | null) => void): Promise<string | null> {
  const buttons = (params.buttons && params.buttons.length ? params.buttons : [{ type: 'close' }]) as PopupButton[]
  if (!params.message || buttons.length > 3) {
    return Promise.reject(new SzError(ERRORS.INVALID_PARAMS, 'message 必填,按钮最多 3 个'))
  }
  const p = call<{ button_id: string | null }>('showPopup', { ...params, buttons })
    .then((r) => (r && r.button_id != null ? String(r.button_id) : null))
  p.then((id) => emit('popupClosed', { button_id: id }), () => undefined)
  return withCb(p, cb)
}

/** initDataUnsafe 按原串缓存:同一份 initData 读多少次都是同一个对象(和 Telegram 一样) */
let unsafeOf = ''
let unsafeCache: InitDataUnsafe = {}
function unsafeData(): InitDataUnsafe {
  if (unsafeOf !== state.initData || !unsafeCache) {
    unsafeOf = state.initData
    unsafeCache = parseInitData(state.initData)
  }
  return unsafeCache
}

export const WebApp = {
  get version() { return state.version },
  sdkVersion: SDK_VERSION,
  get platform() { return state.platform },
  get colorScheme() { return state.colorScheme },
  get themeParams() { return state.themeParams },
  /** 原样交给你的后端验签。**不要**在前端信任它的内容 —— 用 initDataUnsafe 只做展示 */
  get initData() { return state.initData },
  get initDataUnsafe(): InitDataUnsafe { return unsafeData() },
  get inHost() { return mock || inHost },
  get isMock() { return mock },
  get isExpanded() { return state.isExpanded },
  get isFullscreen() { return state.isFullscreen },
  get isOrientationLocked() { return state.isOrientationLocked },
  get isActive() { return state.isActive },
  get viewportHeight() { return state.viewportHeight },
  get viewportStableHeight() { return state.viewportStableHeight },
  get safeAreaInset() { return state.safeAreaInset },
  get contentSafeAreaInset() { return state.contentSafeAreaInset },
  get isClosingConfirmationEnabled() { return state.isClosingConfirmationEnabled },
  /** 顶栏现在的颜色(页面设过的,否则主题的 header_bg_color) */
  get headerColor() { return effectiveColor('header') },
  get backgroundColor() { return effectiveColor('background') },
  /** 底栏(主按钮 / 次按钮那一条)现在的颜色 */
  get bottomBarColor() { return effectiveColor('bottomBar') },
  /** 宿主给这个应用开了哪些能力(basic 之外的要在开发者后台申请) */
  get capabilities() { return state.capabilities.slice() },
  startParam(): string { return launch.szWebAppStartParam || unsafeData().start_param || '' },
  isVersionAtLeast(v: string): boolean { return versionAtLeast(state.version, v) },

  ready(): Promise<void> { return call('ready').then(() => undefined) },
  expand(): Promise<void> { return call('expand').then(() => undefined) },
  close(): Promise<void> { return call('close').then(() => undefined) },
  /** #RRGGBB(也收 #RGB、rgb()),或者主题色的键 'bg_color' / 'secondary_bg_color' / 'header_bg_color' —— 写键的跟着亮暗走 */
  setHeaderColor(color: string): Promise<void> { return setColor('header', color) },
  /** 同 setHeaderColor;键可以是 'bg_color' / 'secondary_bg_color' */
  setBackgroundColor(color: string): Promise<void> { return setColor('background', color) },
  /** 底栏的底色;键可以是 'bg_color' / 'secondary_bg_color' / 'bottom_bar_bg_color'。宿主 2.1 起 */
  setBottomBarColor(color: string): Promise<void> { return setColor('bottomBar', color) },
  enableClosingConfirmation(): Promise<void> {
    state.isClosingConfirmationEnabled = true
    return call('setClosingConfirmation', { enabled: true }).then(() => undefined)
  },
  disableClosingConfirmation(): Promise<void> {
    state.isClosingConfirmationEnabled = false
    return call('setClosingConfirmation', { enabled: false }).then(() => undefined)
  },
  onEvent(name: EventName, fn: Listener): void { (listeners[name] = listeners[name] || []).push(fn) },
  offEvent(name: EventName, fn: Listener): void {
    listeners[name] = (listeners[name] || []).filter((h) => h !== fn)
  },
  showPopup,
  showAlert(message: string, cb?: () => void): Promise<void> {
    return withCb(showPopup({ message, buttons: [{ type: 'close' }] }).then(() => undefined), cb)
  },
  showConfirm(message: string, cb?: (ok: boolean) => void): Promise<boolean> {
    return withCb(showPopup({ message, buttons: [{ id: 'ok', type: 'ok' }, { type: 'cancel' }] })
      .then((id) => id === 'ok'), cb)
  },
  /** 在系统浏览器打开(宿主先弹「即将离开超级赞」) */
  openLink(url: string): Promise<void> {
    if (!/^https?:\/\//i.test(url)) return Promise.reject(new SzError(ERRORS.INVALID_PARAMS, '只能打开 http(s) 链接'))
    return call('openLink', { url }).then(() => undefined)
  },
  /** 系统分享面板。url 可省(默认分享这个小程序的直达链接) */
  share(p: { text: string; url?: string }): Promise<boolean> {
    return call<{ shared: boolean }>('share', p).then((r) => !!r?.shared)
  },
  /** 沉浸式全屏(宿主 2.1 起所有应用都能用)。结果看 fullscreenChanged / fullscreenFailed 事件 */
  requestFullscreen(): Promise<void> { return call('requestFullscreen').then(() => undefined) },
  exitFullscreen(): Promise<void> { return call('exitFullscreen').then(() => undefined) },
  /** 锁住**当前**的屏幕方向(和 Telegram 一样);isOrientationLocked 跟着变 */
  lockOrientation(): Promise<void> {
    return call('lockOrientation').then((ok) => { state.isOrientationLocked = ok !== false })
  },
  unlockOrientation(): Promise<void> {
    return call('unlockOrientation').then(() => { state.isOrientationLocked = false })
  },
  /**
   * 请求昵称和头像(要申请 profile 能力;首次宿主会弹确认,用户可在设置里撤回)。
   * 同意后当场拿到一份**新签发的** initData —— 把它交给你的后端验签,页面自己报的昵称不可信。
   */
  requestProfile(cb?: (e: any, r?: { initData: string; user?: WebAppUser }) => void):
    Promise<{ initData: string; user?: WebAppUser }> {
    return withCb(call<{ init_data: string }>('requestProfile').then((r) => {
      state.initData = r.init_data
      return { initData: r.init_data, user: parseInitData(r.init_data).user }
    }), cb, true)
  },
  MainButton,
  SecondaryButton,
  BackButton,
  SettingsButton,
  HapticFeedback,
  CloudStorage,
  ERRORS,
  SzError,
}

export type WebAppType = typeof WebApp

// ---------------------------------------------------------------- 本地调试(?sz_mock=1)

function mockHost(method: string, p: any): Promise<any> {
  const ls = w.localStorage
  const K = (k: string) => `sz_mock_kv:${k}`
  const read = (k: string): StoredItem | null => parseJson<StoredItem | null>(ls?.getItem(K(k)) || '', null)
  switch (method) {
    case 'showPopup': {
      const btns: PopupButton[] = p.buttons || []
      const ok = btns.find((b) => b.type !== 'cancel' && b.type !== 'close')
      if (btns.length === 1) { w.alert?.(p.message); return Promise.resolve({ button_id: btns[0].id ?? null }) }
      const yes = w.confirm ? w.confirm(p.message) : true
      return Promise.resolve({ button_id: yes ? (ok?.id ?? null) : null })
    }
    case 'openLink':
      w.open?.(p.url, '_blank', 'noopener')
      return Promise.resolve(true)
    case 'share':
      console.info('[sz_mock] share', p)
      return Promise.resolve({ shared: true })
    case 'CloudStorage.getItems': {
      const items: Record<string, StoredItem | null> = {}
      for (const k of p.keys || []) items[k] = read(k)
      return Promise.resolve({ items })
    }
    case 'CloudStorage.setItem': {
      if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(p.key || '')) return Promise.reject(new SzError(4004, '键格式不对'))
      const cur = read(p.key)
      if (p.if_rev !== undefined && (cur ? cur.rev : 0) !== p.if_rev) {
        return Promise.reject(new SzError(4007, '版本号不符'))
      }
      const rev = (cur ? cur.rev : 0) + 1
      ls?.setItem(K(p.key), JSON.stringify({ value: String(p.value), rev }))
      return Promise.resolve({ key: p.key, rev })
    }
    case 'CloudStorage.removeItems':
      for (const k of p.keys || []) ls?.removeItem(K(k))
      return Promise.resolve({ removed: (p.keys || []).length })
    case 'CloudStorage.getKeys': {
      const keys: string[] = []
      for (let i = 0; i < (ls?.length || 0); i++) {
        const k = ls.key(i)
        if (k && k.startsWith('sz_mock_kv:')) {
          const key = k.slice('sz_mock_kv:'.length)
          if (!p.prefix || key.startsWith(p.prefix)) keys.push(key)
        }
      }
      return Promise.resolve({ keys: keys.sort(), next_cursor: null })
    }
    case 'requestProfile':
      return Promise.resolve({ init_data: mockInitData({ nickname: '调试用户' }) })
    case 'requestFullscreen':
    case 'exitFullscreen':
      // 本地调试没有宿主:状态和事件照真宿主的样子走一遍,页面的全屏分支能调
      Promise.resolve().then(() => applyEvent('fullscreenChanged', { isFullscreen: method === 'requestFullscreen' }))
      return Promise.resolve(true)
    default:
      console.info('[sz_mock]', method, p)
      return Promise.resolve(true)
  }
}

function mockInitData(extra: Partial<WebAppUser> = {}): string {
  const user = JSON.stringify({ language_code: 'zh-CN', open_id: 'o_mockmockmockmockmockmockmo', ...extra })
  // mock=1 且 hash/signature 是占位:任何照文档验签的后端都会拒绝它
  return new URLSearchParams({
    app_id: 'szmock', auth_date: String(Math.floor(Date.now() / 1000)), launch_id: 'mock',
    mock: '1', sig_kid: 'mock', user, hash: '0'.repeat(64), signature: 'mock',
  }).toString()
}

if (mock && !state.initData) {
  state.initData = mockInitData()
  state.platform = 'web'
}
if (mock) state.version = PROTOCOL_VERSION

// ---------------------------------------------------------------- 启动

if (!mock && inHost) {
  const hello = () => post({ v: 2, type: 'hello', sdk: SDK_VERSION })
  hello()
  // web 端没有宿主时(页面被别的站点嵌着、或者直接在浏览器里打开),等不到 init 就算不在宿主里
  if (parentWin) {
    setTimeout(() => {
      if (!initialized) {
        inHost = false
        queue.splice(0).forEach((q) => q.fail())
      }
    }, HELLO_TIMEOUT)
  }
}

if (w.document?.addEventListener) {
  // CSP 拦截告诉宿主(模拟器侧栏会显示)。只报指令和被拦的 origin,不报整条地址
  w.document.addEventListener('securitypolicyviolation', (e: any) => {
    post({
      v: 2, type: 'notice', name: 'csp', token,
      data: { directive: e.effectiveDirective || e.violatedDirective,
        blocked: String(e.blockedURI || '').replace(/^(\w+:\/\/[^/?#]+).*$/, '$1') },
    })
  })
}

cssVars()

// ---------------------------------------------------------------- Telegram 兼容层(window.Telegram.WebApp)
//
// 给 Telegram Mini App 的代码用:前端只要把 telegram-web-app.js 的 script 地址换成 /_sdk/2/sz-webapp.js
// (托管页的 CSP 只放行同源脚本,telegram.org 那份本来就加载不了)。它是 SuperZ.WebApp 上面的一层门面
// (原型就是 SuperZ.WebApp、状态是同一份),只在和 Telegram 约定不同的地方盖一层:版本号按 Telegram 的
// Bot API 版本报、方法不返回 Promise 也不 reject、事件处理函数里的 this 是 Telegram.WebApp、
// 云存储读不到的键给空串、超级赞没有的接口给「不支持」的桩(按 Telegram 的回调 / 事件约定回失败,不抛异常)。
// 托管层**不**往页面里注入任何脚本 —— 线上字节必须和审核过、公示 SHA-256 的那一份一致。

/**
 * Telegram.WebApp.version 报的 Bot API 版本:按宿主协议折算,让「按 Telegram 版本号探测能力」的代码走对分支。
 *
 * - 宿主 2.1 起 → '8.0'。8.0 带来的全屏、安全区、锁方向、isActive,以及 7.10 的次按钮、底栏颜色,
 *   7.7 的竖向滑动开关、6.x 的弹窗 / 云存储 / 返回键 / 触感,超级赞都有;再往上的 9.0(DeviceStorage、SecureStorage)没有,
 *   报 9.x 就会让页面以为它们能用;
 * - 老宿主 2.0 → '7.10'。那时普通应用还不能全屏,报 8.0 页面会去调、调了失败。
 *
 * 6.x–8.0 里超级赞没有的那几项(扫码、剪贴板、定位、生物识别、传感器、表情状态、桌面快捷方式、收款……)
 * 任何版本号都挡不住探测,靠下面的桩按 Telegram 的「不支持 / 用户取消」约定回话。
 */
function telegramVersion(): string {
  return versionAtLeast(state.version, '2.1') ? '8.0' : '7.10'
}

const warned: Record<string, boolean> = {}
function unsupported(name: string): void {
  if (warned[name]) return
  warned[name] = true
  console.warn(`[SuperZ] Telegram.WebApp.${name}:超级赞里没有这项能力,按 Telegram 的「不支持」约定处理`)
}

/** 回调异步回(Telegram 的回调都是宿主稍后回话才触发);回调自己抛的错不吞,抛到外面 */
function later(fn: () => void): void {
  Promise.resolve().then(() => {
    try { fn() } catch (e) { setTimeout(() => { throw e }) }
  })
}

type Cb = ((...a: any[]) => void) | undefined | null
const callCb = (cb: Cb, ...a: any[]) => { if (typeof cb === 'function') cb(...a) }

/** 超级赞没有的传感器:start 回 false 并发 xxxFailed(UNSUPPORTED),和 Telegram 在不支持的设备上一样 */
function sensorStub(event: string, fields: Record<string, unknown>) {
  const s: any = {
    isStarted: false,
    ...fields,
    start(_params?: unknown, cb?: Cb) {
      unsupported(`${event}.start`)
      later(() => { callCb(cb, false); emit(`${event}Failed`, { error: 'UNSUPPORTED' }) })
      return s
    },
    stop(cb?: Cb) { later(() => callCb(cb, true)); return s },
  }
  return s
}

/** DeviceStorage / SecureStorage(Bot API 9.0):回调第一个参数给错误 'UNSUPPORTED' */
function deviceStorageStub(name: string, secure: boolean) {
  const fail = (op: string, cb: Cb) => {
    unsupported(`${name}.${op}`)
    later(() => callCb(cb, 'UNSUPPORTED', null))
  }
  const s: any = {
    setItem(_k: string, _v: string, cb?: Cb) { fail('setItem', cb); return s },
    getItem(_k: string, cb?: Cb) { fail('getItem', cb); return s },
    removeItem(_k: string, cb?: Cb) { fail('removeItem', cb); return s },
    clear(cb?: Cb) { fail('clear', cb); return s },
  }
  if (secure) s.restoreItem = (_k: string, cb?: Cb) => { fail('restoreItem', cb); return s }
  return s
}

/** 云存储的 Telegram 写法:只有回调、方法返回自己;读不到的键给空串(Telegram 就是这样) */
const TgCloudStorage: any = {
  setItem(key: string, value: string, cb?: Cb) {
    CloudStorage.setItem(key, value).then(() => callCb(cb, null, true), (e) => callCb(cb, e))
    return TgCloudStorage
  },
  getItem(key: string, cb?: Cb) {
    CloudStorage.getItemsWithRev([key]).then((r) => callCb(cb, null, r[key]?.value ?? ''), (e) => callCb(cb, e))
    return TgCloudStorage
  },
  getItems(keys: string[], cb?: Cb) {
    CloudStorage.getItemsWithRev(keys).then((r) => {
      const out: Record<string, string> = {}
      for (const k of keys) out[k] = r[k]?.value ?? ''
      callCb(cb, null, out)
    }, (e) => callCb(cb, e))
    return TgCloudStorage
  },
  removeItem(key: string, cb?: Cb) { return TgCloudStorage.removeItems([key], cb) },
  removeItems(keys: string[], cb?: Cb) {
    CloudStorage.removeItems(keys).then(() => callCb(cb, null, true), (e) => callCb(cb, e))
    return TgCloudStorage
  },
  getKeys(cb?: Cb) {
    CloudStorage.getKeys().then((k) => callCb(cb, null, k), (e) => callCb(cb, e))
    return TgCloudStorage
  },
}

const LocationManager: any = {
  isInited: false, isLocationAvailable: false, isAccessRequested: false, isAccessGranted: false,
  init(cb?: Cb) {
    const first = !LocationManager.isInited
    LocationManager.isInited = true
    later(() => { callCb(cb); if (first) emit('locationManagerUpdated') })
    return LocationManager
  },
  /** 没有定位:回调给 null(Telegram 在用户没授权时就是 null) */
  getLocation(cb?: Cb) { unsupported('LocationManager.getLocation'); later(() => callCb(cb, null)); return LocationManager },
  openSettings() { return LocationManager },
}

const BiometricManager: any = {
  isInited: false, isBiometricAvailable: false, biometricType: 'unknown', isAccessRequested: false,
  isAccessGranted: false, isBiometricTokenSaved: false, deviceId: '',
  init(cb?: Cb) {
    const first = !BiometricManager.isInited
    BiometricManager.isInited = true
    later(() => { callCb(cb); if (first) emit('biometricManagerUpdated') })
    return BiometricManager
  },
  requestAccess(_p?: unknown, cb?: Cb) {
    unsupported('BiometricManager.requestAccess')
    later(() => callCb(cb, false))
    return BiometricManager
  },
  authenticate(_p?: unknown, cb?: Cb) {
    unsupported('BiometricManager.authenticate')
    later(() => { callCb(cb, false, null); emit('biometricAuthRequested', { isAuthenticated: false }) })
    return BiometricManager
  },
  updateBiometricToken(_t?: string, cb?: Cb) {
    later(() => { callCb(cb, false); emit('biometricTokenUpdated', { isUpdated: false }) })
    return BiometricManager
  },
  openSettings() { return BiometricManager },
}

/** Telegram 那边 onEvent 的处理函数里 this 是 Telegram.WebApp:包一层,记住原函数好 offEvent */
const tgWrapped: Record<string, Array<[Listener, Listener]>> = {}

let verticalSwipes = true
let tgUnsafeOf: string | null = null
let tgUnsafe: any = {}

function fire(p: Promise<unknown>): void { p.catch(() => undefined) }

/**
 * window.Telegram.WebApp。原型是 SuperZ.WebApp:没盖的属性和方法(themeParams、MainButton、HapticFeedback、
 * share、requestProfile……)就是 SuperZ 的那一份,状态也是同一份。
 */
export const TelegramWebApp: any = Object.create(WebApp)

Object.defineProperties(TelegramWebApp, {
  version: { get: telegramVersion, enumerable: true },
  /** initDataUnsafe 加上 Telegram 的字段名:user.id 是 open_id(字符串,按应用隔离),first_name / photo_url 是昵称头像 */
  initDataUnsafe: {
    enumerable: true,
    get() {
      if (tgUnsafeOf !== state.initData) {
        tgUnsafeOf = state.initData
        const base: any = { ...unsafeData() }
        if (base.user) {
          const u = base.user
          base.user = { ...u, id: u.open_id, first_name: u.nickname ?? '' }
          if (u.avatar_url) base.user.photo_url = u.avatar_url
        }
        tgUnsafe = base
      }
      return tgUnsafe
    },
  },
  /** Telegram 的口径:安全区里面再让出的那一截(胶囊占的地方),和 safeAreaInset 相加才是总边距 */
  contentSafeAreaInset: { get: tgContentInset, enumerable: true },
  headerColor: { get: () => effectiveColor('header'), set: (v: string) => TelegramWebApp.setHeaderColor(v), enumerable: true },
  backgroundColor: {
    get: () => effectiveColor('background'), set: (v: string) => TelegramWebApp.setBackgroundColor(v), enumerable: true,
  },
  bottomBarColor: {
    get: () => effectiveColor('bottomBar'), set: (v: string) => TelegramWebApp.setBottomBarColor(v), enumerable: true,
  },
  isClosingConfirmationEnabled: {
    get: () => state.isClosingConfirmationEnabled,
    set: (v: boolean) => (v ? TelegramWebApp.enableClosingConfirmation() : TelegramWebApp.disableClosingConfirmation()),
    enumerable: true,
  },
  /** 超级赞的内容区本来就不会被竖着滑走,只记开关状态 */
  isVerticalSwipesEnabled: { get: () => verticalSwipes, set: (v: boolean) => { verticalSwipes = !!v }, enumerable: true },
  isOrientationLocked: {
    get: () => state.isOrientationLocked,
    set: (v: boolean) => (v ? TelegramWebApp.lockOrientation() : TelegramWebApp.unlockOrientation()),
    enumerable: true,
  },
})

Object.assign(TelegramWebApp, {
  isVersionAtLeast(v: string): boolean { return versionAtLeast(telegramVersion(), v) },
  onEvent(name: string, fn: Listener): void {
    if (typeof fn !== 'function') return
    const list = (tgWrapped[name] = tgWrapped[name] || [])
    if (list.some(([orig]) => orig === fn)) return // Telegram 同一个函数只挂一次
    const wrapped: Listener = (d) => fn.call(TelegramWebApp, d)
    list.push([fn, wrapped])
    WebApp.onEvent(name as EventName, wrapped)
  },
  offEvent(name: string, fn: Listener): void {
    const list = tgWrapped[name] || []
    const hit = list.find(([orig]) => orig === fn)
    if (!hit) return
    tgWrapped[name] = list.filter((x) => x !== hit)
    WebApp.offEvent(name as EventName, hit[1])
  },
  // ---- 和 SuperZ 一样的方法,只是按 Telegram 的约定:不返回 Promise、失败不 reject
  ready() { fire(WebApp.ready()) },
  expand() { fire(WebApp.expand()) },
  close() { fire(WebApp.close()) },
  setHeaderColor(c: string) { fire(WebApp.setHeaderColor(c)) },
  setBackgroundColor(c: string) { fire(WebApp.setBackgroundColor(c)) },
  setBottomBarColor(c: string) { fire(WebApp.setBottomBarColor(c)) },
  enableClosingConfirmation() { fire(WebApp.enableClosingConfirmation()) },
  disableClosingConfirmation() { fire(WebApp.disableClosingConfirmation()) },
  enableVerticalSwipes() { verticalSwipes = true },
  disableVerticalSwipes() { verticalSwipes = false },
  requestFullscreen() { fire(WebApp.requestFullscreen()) },
  exitFullscreen() { fire(WebApp.exitFullscreen()) },
  lockOrientation() { fire(WebApp.lockOrientation()) },
  unlockOrientation() { fire(WebApp.unlockOrientation()) },
  /** options(try_instant_view、try_browser)收下不用:超级赞一律先问「即将离开超级赞」再交系统浏览器 */
  openLink(url: string, _options?: unknown) { fire(WebApp.openLink(String(url))) },
  /** 弹不出来(没有能力、参数不对、不在宿主里)按「没点任何按钮就关了」回 null,和用户点空白关掉一样 */
  showPopup(params: PopupParams, cb?: Cb) {
    showPopup(params).then((id) => callCb(cb, id), () => callCb(cb, null))
  },
  showAlert(message: string, cb?: Cb) {
    showPopup({ message, buttons: [{ type: 'close' }] }).then(() => callCb(cb), () => callCb(cb))
  },
  showConfirm(message: string, cb?: Cb) {
    showPopup({ message, buttons: [{ id: 'ok', type: 'ok' }, { type: 'cancel' }] })
      .then((id) => callCb(cb, id === 'ok'), () => callCb(cb, false))
  },
  CloudStorage: TgCloudStorage,
  DeviceStorage: deviceStorageStub('DeviceStorage', false),
  SecureStorage: deviceStorageStub('SecureStorage', true),
  BiometricManager,
  LocationManager,
  Accelerometer: sensorStub('accelerometer', { x: null, y: null, z: null }),
  DeviceOrientation: sensorStub('deviceOrientation', { absolute: false, alpha: null, beta: null, gamma: null }),
  Gyroscope: sensorStub('gyroscope', { x: null, y: null, z: null }),
  // ---- 超级赞没有的:不抛、不报 undefined,按 Telegram 的回调 / 事件约定回「不支持」
  sendData(_data: string) { unsupported('sendData') },
  switchInlineQuery(_query?: string, _types?: string[]) { unsupported('switchInlineQuery') },
  openTelegramLink(_url: string, _options?: unknown) { unsupported('openTelegramLink') },
  /** 收款:本期不允许。回 'failed' 并发 invoiceClosed,付款流程走不下去 */
  openInvoice(url: string, cb?: Cb) {
    unsupported('openInvoice')
    later(() => { callCb(cb, 'failed'); emit('invoiceClosed', { url, status: 'failed' }) })
  },
  shareToStory(_mediaUrl: string, _params?: unknown) { unsupported('shareToStory') },
  shareMessage(_id: string, cb?: Cb) {
    unsupported('shareMessage')
    later(() => { callCb(cb, false); emit('shareMessageFailed', { error: 'UNSUPPORTED' }) })
  },
  setEmojiStatus(_id: string, params?: unknown, cb?: Cb) {
    if (typeof params === 'function') cb = params as Cb
    unsupported('setEmojiStatus')
    later(() => { callCb(cb, false); emit('emojiStatusFailed', { error: 'UNSUPPORTED' }) })
  },
  requestEmojiStatusAccess(cb?: Cb) {
    unsupported('requestEmojiStatusAccess')
    later(() => { callCb(cb, false); emit('emojiStatusAccessRequested', { status: 'cancelled' }) })
  },
  downloadFile(_params: unknown, cb?: Cb) {
    unsupported('downloadFile')
    later(() => { callCb(cb, false); emit('fileDownloadRequested', { status: 'cancelled' }) })
  },
  addToHomeScreen() { unsupported('addToHomeScreen') },
  checkHomeScreenStatus(cb?: Cb) {
    later(() => { callCb(cb, 'unsupported'); emit('homeScreenChecked', { status: 'unsupported' }) })
  },
  /** 扫码:按「用户把扫码框关了」回 —— 只发 scanQrPopupClosed,回调不会被调 */
  showScanQrPopup(_params?: unknown, _cb?: Cb) {
    unsupported('showScanQrPopup')
    later(() => emit('scanQrPopupClosed'))
  },
  closeScanQrPopup() { /* 没有扫码框可关 */ },
  readTextFromClipboard(cb?: Cb) {
    unsupported('readTextFromClipboard')
    later(() => { callCb(cb, null); emit('clipboardTextReceived', { data: null }) })
  },
  requestWriteAccess(cb?: Cb) {
    unsupported('requestWriteAccess')
    later(() => { callCb(cb, false); emit('writeAccessRequested', { status: 'cancelled' }) })
  },
  requestContact(cb?: Cb) {
    unsupported('requestContact')
    later(() => { callCb(cb, false, { status: 'cancelled' }); emit('contactRequested', { status: 'cancelled' }) })
  },
  requestChat(_reqId: string, cb?: Cb) {
    unsupported('requestChat')
    later(() => { callCb(cb, false); emit('requestedChatFailed', { error: 'UNSUPPORTED' }) })
  },
  invokeCustomMethod(_method: string, _params?: unknown, cb?: Cb) {
    unsupported('invokeCustomMethod')
    later(() => callCb(cb, 'UNSUPPORTED', null))
  },
  /** 收起软键盘:页面里当前的输入框失焦就行,不用宿主 */
  hideKeyboard() {
    try { w.document?.activeElement?.blur?.() } catch (_) { /* 没有焦点 */ }
  },
})

// ---------------------------------------------------------------- 全局 + v1 兼容

w.SuperZ = w.SuperZ || {}
w.SuperZ.WebApp = WebApp

// 只挂 Telegram.WebApp 这一个键:页面自己已有的 window.Telegram(和它下面已有的 WebApp)一概不覆盖
w.Telegram = w.Telegram || {}
if (!w.Telegram.WebApp) w.Telegram.WebApp = TelegramWebApp

if (!w.superz) {
  // 老页面(v1 桥)不用改:window.superz 映射到 v2
  w.superz = {
    version: 1,
    get inHost() { return WebApp.inHost },
    ready: () => WebApp.ready(),
    close: () => WebApp.close(),
    expand: () => WebApp.expand(),
    themeParams: () => Promise.resolve({ brightness: state.colorScheme, ...state.themeParams }),
    getInitData: () => call('legacy.getInitData'),
  }
}

export default WebApp
