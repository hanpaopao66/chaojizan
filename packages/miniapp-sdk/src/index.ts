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
 *   页面 → 宿主:hello(握手)、call(调用)、notice(CSP 违规等,宿主可以不理);
 *   宿主 → 页面:init(带会话令牌与初始状态)、reply、event;
 * - **会话令牌**:宿主每次加载生成、只发给主框架。不带或带错令牌的调用一律被宿主丢弃 ——
 *   原生 JS 通道对页面里所有 frame 都可见,光看主框架 URL 挡不住 iframe 冒充;
 * - 传输:手机端是原生注入的 SuperzBridge 通道(宿主经 window.__szReceive 回话),
 *   web 端是跨域 iframe + postMessage(只认 event.source === window.parent)。
 *
 * 所有方法返回 Promise;同时兼容 Telegram 风格的回调参数。不在宿主里时 inHost=false,调用回 4008。
 * 本地调试加 `?sz_mock=1`:弹窗用浏览器原生、云存储落 localStorage、initData 带 mock=1
 * 且**签名必然无效** —— 开发者后端照常验签就会拒绝,没人能拿 mock 冒充真用户。
 */

export const SDK_VERSION = '2.0.0'

// ---------------------------------------------------------------- 类型

export type ColorScheme = 'light' | 'dark'
export type Platform = 'android' | 'ios' | 'web' | 'unknown'

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
  color?: string
  text_color?: string
  is_visible?: boolean
  is_active?: boolean
  is_progress_visible?: boolean
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
  'ready', 'expand', 'close', 'setHeaderColor', 'setBackgroundColor', 'setClosingConfirmation',
  'mainButton', 'secondaryButton', 'backButton', 'settingsButton', 'haptic', 'showPopup',
  'openLink', 'share', 'CloudStorage.getItems', 'CloudStorage.setItem', 'CloudStorage.removeItems',
  'CloudStorage.getKeys', 'requestFullscreen', 'exitFullscreen', 'lockOrientation',
  'unlockOrientation', 'requestProfile', 'legacy.getInitData',
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

const state = {
  version: launch.szWebAppVersion || '2.0',
  platform: (launch.szWebAppPlatform || (native ? 'unknown' : 'web')) as Platform,
  themeParams: parseJson<ThemeParams>(launch.szWebAppThemeParams, {}),
  colorScheme: 'light' as ColorScheme,
  viewportHeight: w.innerHeight || 0,
  viewportStableHeight: w.innerHeight || 0,
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 } as SafeAreaInset,
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 } as SafeAreaInset,
  isExpanded: false,
  isFullscreen: false,
  isActive: true,
  isClosingConfirmationEnabled: false,
  headerColor: '',
  backgroundColor: '',
  capabilities: [] as string[],
  initData: launch.szWebAppData || '',
}
state.colorScheme = brightness(state.themeParams.bg_color) || 'light'

function cssVars(): void {
  const root = w.document?.documentElement
  if (!root?.style) return
  const set = (k: string, v: string) => root.style.setProperty(k, v)
  for (const [k, v] of Object.entries(state.themeParams)) {
    if (typeof v === 'string') set(`--sz-theme-${k.replace(/_/g, '-')}`, v)
  }
  set('--sz-viewport-height', `${state.viewportHeight}px`)
  set('--sz-viewport-stable-height', `${state.viewportStableHeight}px`)
  for (const side of ['top', 'bottom', 'left', 'right'] as const) {
    set(`--sz-safe-area-inset-${side}`, `${state.safeAreaInset[side] || 0}px`)
    set(`--sz-content-safe-area-inset-${side}`, `${state.contentSafeAreaInset[side] || 0}px`)
  }
  root.style.colorScheme = state.colorScheme
}

function applyInit(m: any): void {
  if (m.version) state.version = String(m.version)
  if (m.platform) state.platform = m.platform
  if (m.themeParams) state.themeParams = m.themeParams
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
    case 'themeChanged':
      state.themeParams = d?.themeParams || state.themeParams
      state.colorScheme = d?.colorScheme || brightness(state.themeParams.bg_color) || state.colorScheme
      cssVars()
      break
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

class BottomButton {
  text: string
  color = ''
  textColor = ''
  isVisible = false
  isActive = true
  isProgressVisible = false
  position: BottomButtonParams['position'] = 'left'
  private handlers: Listener[] = []
  private scheduled = false

  constructor(private method: 'mainButton' | 'secondaryButton', text: string) {
    this.text = text
  }

  /** @internal */
  _fire(): void {
    if (!this.isActive || this.isProgressVisible) return
    for (const fn of this.handlers.slice()) fn()
  }

  private _sync(): this {
    // 同一轮里连着改几个属性(setText + show),只发一次
    if (!this.scheduled) {
      this.scheduled = true
      Promise.resolve().then(() => {
        this.scheduled = false
        call(this.method, {
          text: this.text, color: this.color, text_color: this.textColor,
          is_visible: this.isVisible, is_active: this.isActive,
          is_progress_visible: this.isProgressVisible, position: this.position,
        }).catch(() => undefined)
      })
    }
    return this
  }

  setText(text: string): this { this.text = String(text).slice(0, 64); return this._sync() }
  show(): this { this.isVisible = true; return this._sync() }
  hide(): this { this.isVisible = false; return this._sync() }
  enable(): this { this.isActive = true; return this._sync() }
  disable(): this { this.isActive = false; return this._sync() }
  showProgress(_leaveActive?: boolean): this { this.isProgressVisible = true; return this._sync() }
  hideProgress(): this { this.isProgressVisible = false; return this._sync() }
  setParams(p: BottomButtonParams): this {
    if (p.text !== undefined) this.text = String(p.text).slice(0, 64)
    if (p.color !== undefined) this.color = p.color
    if (p.text_color !== undefined) this.textColor = p.text_color
    if (p.is_visible !== undefined) this.isVisible = !!p.is_visible
    if (p.is_active !== undefined) this.isActive = !!p.is_active
    if (p.is_progress_visible !== undefined) this.isProgressVisible = !!p.is_progress_visible
    if (p.position !== undefined) this.position = p.position
    return this._sync()
  }
  onClick(fn: Listener): this { this.handlers.push(fn); return this }
  offClick(fn: Listener): this { this.handlers = this.handlers.filter((h) => h !== fn); return this }
}

class HeaderButton {
  isVisible = false
  private handlers: Listener[] = []
  constructor(private method: 'backButton' | 'settingsButton') {}
  /** @internal */
  _fire(): void { for (const fn of this.handlers.slice()) fn() }
  show(): this { this.isVisible = true; call(this.method, { is_visible: true }).catch(() => undefined); return this }
  hide(): this { this.isVisible = false; call(this.method, { is_visible: false }).catch(() => undefined); return this }
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

export const WebApp = {
  get version() { return state.version },
  sdkVersion: SDK_VERSION,
  get platform() { return state.platform },
  get colorScheme() { return state.colorScheme },
  get themeParams() { return state.themeParams },
  /** 原样交给你的后端验签。**不要**在前端信任它的内容 —— 用 initDataUnsafe 只做展示 */
  get initData() { return state.initData },
  get initDataUnsafe(): InitDataUnsafe { return parseInitData(state.initData) },
  get inHost() { return mock || inHost },
  get isMock() { return mock },
  get isExpanded() { return state.isExpanded },
  get isFullscreen() { return state.isFullscreen },
  get isActive() { return state.isActive },
  get viewportHeight() { return state.viewportHeight },
  get viewportStableHeight() { return state.viewportStableHeight },
  get safeAreaInset() { return state.safeAreaInset },
  get contentSafeAreaInset() { return state.contentSafeAreaInset },
  get isClosingConfirmationEnabled() { return state.isClosingConfirmationEnabled },
  get headerColor() { return state.headerColor },
  get backgroundColor() { return state.backgroundColor },
  /** 宿主给这个应用开了哪些能力(basic 之外的要在开发者后台申请) */
  get capabilities() { return state.capabilities.slice() },
  startParam(): string { return launch.szWebAppStartParam || parseInitData(state.initData).start_param || '' },
  isVersionAtLeast(v: string): boolean { return versionAtLeast(state.version, v) },

  ready(): Promise<void> { return call('ready').then(() => undefined) },
  expand(): Promise<void> { return call('expand').then(() => undefined) },
  close(): Promise<void> { return call('close').then(() => undefined) },
  setHeaderColor(color: string): Promise<void> {
    state.headerColor = color
    return call('setHeaderColor', { color }).then(() => undefined)
  },
  setBackgroundColor(color: string): Promise<void> {
    state.backgroundColor = color
    return call('setBackgroundColor', { color }).then(() => undefined)
  },
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
  requestFullscreen(): Promise<void> { return call('requestFullscreen').then(() => undefined) },
  exitFullscreen(): Promise<void> { return call('exitFullscreen').then(() => undefined) },
  lockOrientation(): Promise<void> { return call('lockOrientation').then(() => undefined) },
  unlockOrientation(): Promise<void> { return call('unlockOrientation').then(() => undefined) },
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

// ---------------------------------------------------------------- 全局 + v1 兼容

w.SuperZ = w.SuperZ || {}
w.SuperZ.WebApp = WebApp

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
