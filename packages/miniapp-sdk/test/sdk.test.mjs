// SDK v2 的行为测试:假宿主 + node:vm 沙箱,覆盖每个方法的成功 / 失败 / 超时路径(#323)。
// 跑法:npm test(先构建,再跑 dist/sz-webapp.js 这份真正发布出去的产物)
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const CODE = readFileSync(new URL('../dist/sz-webapp.js', import.meta.url), 'utf8')
const INIT = 'app_id=sz0123456789abcdef&auth_date=1790000000&launch_id=L1&sig_kid=k1' +
  '&user=%7B%22language_code%22%3A%22zh-CN%22%2C%22open_id%22%3A%22o_abc%22%7D&start_param=p1&hash=h&signature=s'

function frag(extra = {}) {
  const p = new URLSearchParams({ szWebAppData: INIT, szWebAppVersion: '2.0', szWebAppPlatform: 'android',
    szWebAppThemeParams: JSON.stringify({ bg_color: '#1A1A1A', text_color: '#F0EEE6' }),
    szWebAppStartParam: 'p1', ...extra })
  return '#' + p.toString()
}

/** 造一个装好 SDK 的页面。mode: native(手机端注入通道)/ iframe(web 端)/ top(直接打开)/ mock。
 *  pre:SDK 加载之前页面上已经有的全局(比如页面自己的 window.Telegram) */
function page({ mode = 'native', hash = frag(), search = '', session = {}, pre = {} } = {}) {
  const sent = []
  const listeners = {}
  const cssVars = {}
  const store = { ...session }
  const timers = []
  const win = {
    location: { hash, search, pathname: '/v/1/index.html' },
    history: { state: null, replaceState(_s, _t, url) { win.location.hash = ''; win.replacedWith = url } },
    sessionStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v) } },
    localStorage: (() => {
      const m = new Map()
      return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)),
        removeItem: (k) => m.delete(k), key: (i) => [...m.keys()][i] ?? null, get length() { return m.size } }
    })(),
    document: { documentElement: { style: { setProperty: (k, v) => { cssVars[k] = v } } },
      addEventListener() {} },
    innerHeight: 700,
    addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn) },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length },
    clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].fn = null },
    URLSearchParams, Promise, JSON, console, Object, Math, Number, String, Array,
    alert: () => {}, confirm: () => true, open: () => {},
  }
  win.window = win
  Object.assign(win, pre)
  if (mode === 'native') {
    win.SuperzBridge = { postMessage: (s) => sent.push(JSON.parse(s)) }
    win.parent = win
  } else if (mode === 'iframe' || mode === 'mock-iframe') {
    win.parent = { postMessage: (m, origin) => sent.push({ ...m, _origin: origin }) }
  } else {
    win.parent = win
  }
  vm.createContext(win)
  vm.runInContext(CODE, win)
  const host = {
    win, sent, cssVars, store, timers,
    get app() { return win.SuperZ.WebApp },
    get tg() { return win.Telegram.WebApp },
    deliver(msg) {
      if (mode === 'native') win.__szReceive(JSON.stringify(msg))
      else for (const fn of listeners.message || []) fn({ source: win.parent, origin: 'https://host.example', data: { __sz: 2, ...msg } })
    },
    forge(msg) { for (const fn of listeners.message || []) fn({ source: {}, origin: 'https://evil.example', data: { __sz: 2, ...msg } }) },
    init(extra = {}) { host.deliver({ v: 2, type: 'init', token: 'T0K3N', capabilities: ['storage'], ...extra }) },
    calls() { return sent.filter((m) => m.type === 'call') },
    reply(id, data, ok = true, error) { host.deliver({ v: 2, type: 'reply', id, ok, data, error }) },
    fireTimers(minMs = 0) { for (const t of timers.splice(0)) if (t.fn && t.ms >= minMs) t.fn() },
  }
  return host
}

const tick = () => new Promise((r) => setImmediate(r))
/** 沙箱里造的对象原型是另一个 realm 的,比较前转成普通对象 */
const plain = (x) => JSON.parse(JSON.stringify(x))

test('读启动片段:initData、平台、主题、startParam;读完抹掉片段并存进 sessionStorage', () => {
  const h = page()
  const a = h.app
  assert.equal(a.initData, INIT)
  assert.equal(a.initDataUnsafe.user.open_id, 'o_abc')
  assert.equal(a.initDataUnsafe.auth_date, 1790000000)
  assert.equal(a.platform, 'android')
  assert.equal(a.colorScheme, 'dark', '深色背景推出 dark')
  assert.equal(a.startParam(), 'p1')
  assert.equal(h.win.location.hash, '', '片段要抹掉,复制地址不带身份包')
  assert.equal(h.win.replacedWith, '/v/1/index.html')
  assert.ok(JSON.parse(h.store.__szLaunch).szWebAppData)
  assert.equal(h.cssVars['--sz-theme-bg-color'], '#1A1A1A')
  assert.equal(h.cssVars['--sz-viewport-height'], '700px')
})

test('页面在 WebView 里刷新:片段没了,从 sessionStorage 读回来', () => {
  const first = page()
  const h = page({ hash: '', session: first.store })
  assert.equal(h.app.initData, INIT)
})

test('握手:先发 hello;init 到之前的调用排队,init 带来令牌后发出,每条都带令牌', async () => {
  const h = page()
  assert.equal(h.sent[0].type, 'hello')
  const p = h.app.expand()
  assert.equal(h.calls().length, 0, 'init 之前不发')
  h.init()
  const c = h.calls()[0]
  assert.equal(c.method, 'expand')
  assert.equal(c.token, 'T0K3N')
  h.reply(c.id, true)
  await p
})

test('reply 失败带错误码,SzError.code 可判断', async () => {
  const h = page()
  h.init()
  const p = h.app.CloudStorage.setItem('k', 'v', { ifRev: 3 })
  const c = h.calls()[0]
  assert.deepEqual(plain(c.params), { key: 'k', value: 'v', if_rev: 3 })
  h.reply(c.id, null, false, { code: 4007, message: '版本号不符' })
  await assert.rejects(p, (e) => e.code === 4007 && e.name === 'SzError')
})

test('超时:宿主不应答回 5000', async () => {
  const h = page()
  h.init()
  const p = h.app.ready()
  h.fireTimers(30000)
  await assert.rejects(p, (e) => e.code === 5000)
})

test('Telegram 风格回调也能用', async () => {
  const h = page()
  h.init()
  let got
  h.app.CloudStorage.getItem('a', (err, v) => { got = [err, v] })
  const c = h.calls()[0]
  assert.equal(c.method, 'CloudStorage.getItems')
  h.reply(c.id, { items: { a: { value: '1', rev: 2 } } })
  await tick(); await tick()
  assert.deepEqual(plain(got), [null, '1'])
})

test('CloudStorage.getKeys 自动翻页', async () => {
  const h = page()
  h.init()
  const p = h.app.CloudStorage.getKeys({ prefix: 'n:' })
  h.reply(h.calls()[0].id, { keys: ['n:1'], next_cursor: 'n:1' })
  await tick()
  assert.equal(h.calls()[1].params.cursor, 'n:1')
  h.reply(h.calls()[1].id, { keys: ['n:2'], next_cursor: null })
  assert.deepEqual(plain(await p), ['n:1', 'n:2'])
})

test('showPopup 最多 3 个按钮;showConfirm 按 id 判断;popupClosed 事件', async () => {
  const h = page()
  h.init()
  await assert.rejects(h.app.showPopup({ message: 'x', buttons: [{}, {}, {}, {}] }), (e) => e.code === 4004)
  let closed
  h.app.onEvent('popupClosed', (d) => { closed = d })
  const p = h.app.showConfirm('删除?')
  const c = h.calls()[0]
  assert.equal(c.method, 'showPopup')
  assert.equal(c.params.buttons.length, 2)
  h.reply(c.id, { button_id: 'ok' })
  assert.equal(await p, true)
  await tick()
  assert.deepEqual(plain(closed), { button_id: 'ok' })
})

test('MainButton:同一轮连着改只发一次;点击事件在进度中不触发', async () => {
  const h = page()
  h.init()
  let clicks = 0
  h.app.MainButton.setText('新建笔记').show().onClick(() => { clicks++ })
  await tick()
  const cs = h.calls().filter((c) => c.method === 'mainButton')
  assert.equal(cs.length, 1)
  assert.equal(cs[0].params.text, '新建笔记')
  assert.equal(cs[0].params.is_visible, true)
  h.deliver({ v: 2, type: 'event', name: 'mainButtonClicked' })
  assert.equal(clicks, 1)
  h.app.MainButton.showProgress()
  h.deliver({ v: 2, type: 'event', name: 'mainButtonClicked' })
  assert.equal(clicks, 1)
})

test('BackButton / SettingsButton / 触感 / 关闭确认 / 颜色 都发出对应的方法', async () => {
  const h = page()
  h.init()
  h.app.BackButton.show()
  h.app.SettingsButton.hide()
  h.app.HapticFeedback.impactOccurred('medium').notificationOccurred('warning').selectionChanged()
  h.app.enableClosingConfirmation()
  h.app.setHeaderColor('#000000')
  const m = plain(h.calls().map((c) => [c.method, c.params]))
  assert.deepEqual(m.slice(0, 6), [
    ['backButton', { is_visible: true }], ['settingsButton', { is_visible: false }],
    ['haptic', { type: 'impact', style: 'medium' }], ['haptic', { type: 'notification', style: 'warning' }],
    ['haptic', { type: 'selection' }], ['setClosingConfirmation', { enabled: true }]])
  assert.equal(h.app.isClosingConfirmationEnabled, true)
})

test('事件:主题、视口、安全区更新状态和 CSS 变量', () => {
  const h = page()
  h.init({ viewport: { height: 600, stableHeight: 600 }, safeArea: { top: 24, bottom: 16, left: 0, right: 0 } })
  assert.equal(h.cssVars['--sz-safe-area-inset-top'], '24px')
  let seen = 0
  h.app.onEvent('themeChanged', () => { seen++ })
  h.deliver({ v: 2, type: 'event', name: 'themeChanged', data: { themeParams: { bg_color: '#F0EEE6' } } })
  assert.equal(h.app.colorScheme, 'light')
  assert.equal(h.cssVars['--sz-theme-bg-color'], '#F0EEE6')
  h.deliver({ v: 2, type: 'event', name: 'viewportChanged', data: { height: 500, isStateStable: true } })
  assert.equal(h.app.viewportStableHeight, 500)
  assert.equal(h.cssVars['--sz-viewport-stable-height'], '500px')
  assert.equal(seen, 1)
})

test('requestProfile 拿到新签发的 initData 并替换', async () => {
  const h = page()
  h.init()
  const p = h.app.requestProfile()
  const c = h.calls()[0]
  const fresh = INIT.replace('o_abc%22%7D', 'o_abc%22%2C%22nickname%22%3A%22%E5%B0%8F%E7%8E%8B%22%7D')
  h.reply(c.id, { init_data: fresh })
  const r = await p
  assert.equal(r.user.nickname, '小王')
  assert.equal(h.app.initData, fresh)
})

test('web 端:只认父窗口发来的消息;别的来源伪造的 init / reply 一律丢弃', async () => {
  const h = page({ mode: 'iframe' })
  assert.equal(h.sent[0].type, 'hello')
  assert.equal(h.sent[0]._origin, '*', 'hello 时还不知道宿主 origin')
  h.forge({ v: 2, type: 'init', token: 'EVIL' })
  const p = h.app.close()
  assert.equal(h.calls().length, 0, '伪造的 init 不算数')
  h.init()
  const c = h.calls()[0]
  assert.equal(c.token, 'T0K3N')
  assert.equal(c._origin, 'https://host.example', 'init 之后发给确定的宿主 origin')
  h.forge({ v: 2, type: 'reply', id: c.id, ok: false, error: { code: 5000 } })
  h.reply(c.id, true)
  await p
})

test('web 端没有宿主:3 秒等不到 init 就是不在宿主里,调用回 4008', async () => {
  const h = page({ mode: 'iframe' })
  const p = h.app.ready()
  h.fireTimers(3000)
  await assert.rejects(p, (e) => e.code === 4008)
  assert.equal(h.app.inHost, false)
})

test('直接在浏览器里打开:inHost=false,调用立即 4008', async () => {
  const h = page({ mode: 'top', hash: '' })
  assert.equal(h.app.inHost, false)
  await assert.rejects(h.app.openLink('https://a.example'), (e) => e.code === 4008)
})

test('?sz_mock=1:云存储落 localStorage、带 rev;initData 带 mock=1 且签名是占位', async () => {
  const h = page({ mode: 'top', hash: '', search: '?sz_mock=1' })
  const a = h.app
  assert.equal(a.inHost, true)
  assert.match(a.initData, /mock=1/)
  assert.match(a.initData, /hash=0{64}/)
  assert.deepEqual(plain(await a.CloudStorage.setItem('n:1', 'x', { ifRev: 0 })), { key: 'n:1', rev: 1 })
  await assert.rejects(a.CloudStorage.setItem('n:1', 'y', { ifRev: 0 }), (e) => e.code === 4007)
  assert.equal(await a.CloudStorage.getItem('n:1'), 'x')
  assert.deepEqual(plain(await a.CloudStorage.getKeys({ prefix: 'n:' })), ['n:1'])
})

test('v1 兼容:window.superz 还在,映射到 v2', async () => {
  const h = page()
  h.init()
  assert.equal(h.win.superz.version, 1)
  const p = h.win.superz.getInitData()
  const c = h.calls()[0]
  assert.equal(c.method, 'legacy.getInitData')
  h.reply(c.id, { payload: {}, sign: 'x' })
  assert.deepEqual(plain(await p), { payload: {}, sign: 'x' })
})

test('isVersionAtLeast 做宿主能力协商', () => {
  const h = page()
  assert.equal(h.app.isVersionAtLeast('2.0'), true)
  assert.equal(h.app.isVersionAtLeast('2.1'), false)
  h.init({ version: '2.1' })
  assert.equal(h.app.isVersionAtLeast('2.1'), true)
})

test('宿主的 ping 回 pong(带同一个 nonce、不带令牌);别的 frame 发来的 ping 不理', () => {
  const h = page({ mode: 'iframe' })
  h.init()
  h.deliver({ v: 2, type: 'ping', nonce: 'n1' })
  const pong = h.sent.filter((m) => m.type === 'pong')
  assert.equal(pong.length, 1)
  assert.equal(pong[0].nonce, 'n1')
  assert.equal(pong[0].token, undefined)
  h.forge({ v: 2, type: 'ping', nonce: 'n2' })
  assert.equal(h.sent.filter((m) => m.type === 'pong').length, 1)
})

// ---------------------------------------------------------------- Telegram 兼容层(2.1.0)

/** 宿主 2.1 下发的 16 个主题色:Telegram 的 15 个 + 超级赞的 line_color */
const THEME16 = {
  bg_color: '#F0EEE6', secondary_bg_color: '#FBFAF6', text_color: '#141413', hint_color: '#6B6862',
  link_color: '#2C5F87', button_color: '#C15F3C', button_text_color: '#FBFAF6', accent_text_color: '#C15F3C',
  destructive_text_color: '#D03030', header_bg_color: '#F0EEE6', bottom_bar_bg_color: '#FBFAF6',
  section_bg_color: '#FBFAF6', section_header_text_color: '#6B6862', section_separator_color: '#E2DED2',
  subtitle_text_color: '#6B6862', line_color: '#E2DED2',
}
const TG_KEYS = ['bg_color', 'text_color', 'hint_color', 'link_color', 'button_color', 'button_text_color',
  'secondary_bg_color', 'header_bg_color', 'bottom_bar_bg_color', 'accent_text_color', 'section_bg_color',
  'section_header_text_color', 'section_separator_color', 'subtitle_text_color', 'destructive_text_color']

test('window.Telegram.WebApp 挂上了,原型就是 SuperZ.WebApp、状态同一份', () => {
  const h = page()
  assert.ok(h.tg, 'Telegram.WebApp 要在')
  assert.equal(Object.getPrototypeOf(h.tg), h.app)
  assert.equal(h.tg.themeParams, h.app.themeParams)
  assert.equal(h.tg.initData, INIT)
  assert.equal(h.tg.MainButton, h.app.MainButton)
  assert.equal(h.tg.platform, 'android')
})

test('页面自己已有的 window.Telegram 和 Telegram.WebApp 不覆盖', () => {
  const login = { auth() {} }
  const h = page({ pre: { Telegram: { Login: login } } })
  assert.equal(h.win.Telegram.Login, login, 'Telegram 下别的键原样留着')
  assert.ok(h.win.Telegram.WebApp)
  const mine = { mine: true }
  const h2 = page({ pre: { Telegram: { WebApp: mine } } })
  assert.equal(h2.win.Telegram.WebApp, mine, '页面自己放的 Telegram.WebApp 不动')
  assert.ok(h2.app, 'SuperZ.WebApp 照常')
})

test('版本号:宿主 2.1 报 Bot API 8.0,老宿主 2.0 报 7.10;SuperZ 那边仍是宿主协议版本', () => {
  const h = page({ hash: frag({ szWebAppVersion: '2.1' }) })
  assert.equal(h.tg.version, '8.0', '启动片段里就是 2.1:页面同步探测也走对分支')
  assert.equal(h.tg.isVersionAtLeast('8.0'), true)
  assert.equal(h.tg.isVersionAtLeast('7.10'), true)
  assert.equal(h.tg.isVersionAtLeast('6.9'), true)
  assert.equal(h.tg.isVersionAtLeast('9.0'), false, 'DeviceStorage / SecureStorage 那一版没有')
  assert.equal(h.app.version, '2.1')
  assert.equal(h.app.isVersionAtLeast('2.1'), true)
  assert.equal(h.app.isVersionAtLeast('8.0'), false, 'SuperZ 的版本号不受 Telegram 那边影响')

  const old = page()
  assert.equal(old.tg.version, '7.10', '老宿主普通应用不能全屏,报 8.0 页面会去调')
  assert.equal(old.tg.isVersionAtLeast('8.0'), false)
  old.init({ version: '2.1' })
  assert.equal(old.tg.version, '8.0', 'init 带来的宿主版本为准')
})

test('themeParams 是 Telegram 的 15 个键 + line_color;CSS 变量 --sz-* 和 --tg-* 两套名字都有', () => {
  const h = page({ hash: frag({ szWebAppThemeParams: JSON.stringify(THEME16) }) })
  for (const k of TG_KEYS) {
    assert.ok(h.tg.themeParams[k], `themeParams.${k}`)
    const v = `-${k.replace(/_/g, '-')}`
    assert.equal(h.cssVars[`--tg-theme${v}`], THEME16[k], `--tg-theme${v}`)
    assert.equal(h.cssVars[`--sz-theme${v}`], THEME16[k], `--sz-theme${v}`)
  }
  assert.equal(Object.keys(h.app.themeParams).length, 16)
  assert.equal(h.app.themeParams.line_color, '#E2DED2', 'line_color 是超级赞多出来的,保留')
  assert.equal(h.cssVars['--tg-color-scheme'], 'light')
  assert.equal(h.cssVars['--tg-viewport-height'], '700px')
  assert.equal(h.cssVars['--tg-viewport-stable-height'], '700px')
})

test('老宿主只给 10 个主题色:缺的 6 个 Telegram 键按新宿主的取法补上', () => {
  const ten = { bg_color: '#1B1A17', secondary_bg_color: '#24231F', text_color: '#F2F0E8', hint_color: '#A8A49A',
    link_color: '#7FB2D9', button_color: '#E08A6B', button_text_color: '#1B1A17', accent_text_color: '#E08A6B',
    destructive_text_color: '#E06B6B', line_color: '#37342D' }
  const h = page({ hash: frag({ szWebAppThemeParams: JSON.stringify(ten) }) })
  const t = h.tg.themeParams
  assert.equal(t.header_bg_color, ten.bg_color)
  assert.equal(t.bottom_bar_bg_color, ten.secondary_bg_color)
  assert.equal(t.section_bg_color, ten.secondary_bg_color)
  assert.equal(t.section_header_text_color, ten.hint_color)
  assert.equal(t.section_separator_color, ten.line_color)
  assert.equal(t.subtitle_text_color, ten.hint_color)
  assert.equal(h.cssVars['--tg-theme-section-separator-color'], ten.line_color)
  h.deliver({ v: 2, type: 'event', name: 'themeChanged', data: { themeParams: THEME16 } })
  assert.equal(h.tg.themeParams.header_bg_color, THEME16.header_bg_color, '宿主给了就用宿主的')
})

test('安全区:--tg-safe-area-inset-* 照抄;--tg-content-safe-area-inset-* 是安全区里再让出的那一截(Telegram 口径)', () => {
  const h = page()
  h.init({ safeArea: { top: 24, bottom: 16, left: 0, right: 0 },
    contentSafeArea: { top: 72, bottom: 0, left: 0, right: 0 } })
  assert.equal(h.cssVars['--tg-safe-area-inset-top'], '24px')
  assert.equal(h.cssVars['--tg-safe-area-inset-bottom'], '16px')
  assert.equal(h.cssVars['--sz-content-safe-area-inset-top'], '72px', '超级赞的口径:从屏幕边算起的总边距')
  assert.equal(h.cssVars['--tg-content-safe-area-inset-top'], '48px', 'Telegram 的口径:和安全区相加才是总边距')
  assert.equal(h.cssVars['--tg-content-safe-area-inset-bottom'], '0px', '不会出负数')
  assert.deepEqual(plain(h.tg.contentSafeAreaInset), { top: 48, bottom: 0, left: 0, right: 0 })
  assert.deepEqual(plain(h.app.contentSafeAreaInset), { top: 72, bottom: 0, left: 0, right: 0 })
  assert.deepEqual(plain(h.tg.safeAreaInset), { top: 24, bottom: 16, left: 0, right: 0 })
})

test('initDataUnsafe:user.id 是 open_id(字符串);requestProfile 之后 first_name / photo_url 是昵称头像', async () => {
  const h = page()
  h.init()
  const u = h.tg.initDataUnsafe.user
  assert.equal(u.id, 'o_abc')
  assert.equal(typeof u.id, 'string', '和 Telegram 的数字 id 不一样')
  assert.equal(u.first_name, '', '没授权昵称时给空串,不是 undefined')
  assert.equal(u.photo_url, undefined)
  assert.equal(h.tg.initDataUnsafe.start_param, 'p1')
  assert.equal(h.app.initDataUnsafe.user.id, undefined, 'SuperZ.WebApp 的对象模型不变')
  assert.equal(h.tg.initDataUnsafe, h.tg.initDataUnsafe, '同一份 initData 读到同一个对象')
  const p = h.tg.requestProfile()
  const fresh = INIT.replace('o_abc%22%7D',
    'o_abc%22%2C%22nickname%22%3A%22%E5%B0%8F%E7%8E%8B%22%2C%22avatar_url%22%3A%22https%3A%2F%2Fa.example%2F1.jpg%22%7D')
  h.reply(h.calls()[0].id, { init_data: fresh })
  await p
  const u2 = h.tg.initDataUnsafe.user
  assert.equal(u2.first_name, '小王')
  assert.equal(u2.photo_url, 'https://a.example/1.jpg')
  assert.equal(u2.id, 'o_abc')
})

test('onEvent:处理函数里 this 是 Telegram.WebApp;同一个函数只挂一次;offEvent 摘得掉', () => {
  const h = page()
  h.init()
  const seen = []
  function onTheme() { seen.push(this) }
  h.tg.onEvent('themeChanged', onTheme)
  h.tg.onEvent('themeChanged', onTheme)
  h.deliver({ v: 2, type: 'event', name: 'themeChanged', data: { themeParams: THEME16 } })
  assert.equal(seen.length, 1, 'Telegram 同一个处理函数只挂一次')
  assert.equal(seen[0], h.tg)
  h.tg.offEvent('themeChanged', onTheme)
  h.deliver({ v: 2, type: 'event', name: 'themeChanged', data: { themeParams: THEME16 } })
  assert.equal(seen.length, 1)
})

test('方法按 Telegram 的约定:不返回 Promise、失败不 reject(页面的错误上报不会被刷)', async () => {
  const h = page()
  h.init()
  const unhandled = []
  const onUnhandled = (e) => unhandled.push(e)
  process.on('unhandledRejection', onUnhandled)
  try {
    assert.equal(h.tg.openLink('https://a.example', { try_instant_view: true }), undefined)
    assert.equal(h.tg.ready(), undefined)
    assert.equal(h.tg.requestFullscreen(), undefined)
    for (const c of h.calls()) h.reply(c.id, null, false, { code: 4002, message: '用户取消了' })
    for (let i = 0; i < 5; i++) await tick()
  } finally {
    process.off('unhandledRejection', onUnhandled)
  }
  assert.deepEqual(h.calls().map((c) => c.method), ['openLink', 'ready', 'requestFullscreen'])
  assert.equal(unhandled.length, 0, `不该有没接住的 rejection:${unhandled}`)
})

test('弹窗:Telegram 的回调写法;弹不出来按「没点按钮就关了」回', async () => {
  const h = page()
  h.init()
  let got
  h.tg.showPopup({ message: '删除?', buttons: [{ id: 'del', type: 'destructive', text: '删除' }, { type: 'cancel' }] },
    (id) => { got = id })
  h.reply(h.calls()[0].id, { button_id: 'del' })
  await tick(); await tick()
  assert.equal(got, 'del')
  let ok
  h.tg.showConfirm('确定?', (v) => { ok = v })
  h.reply(h.calls()[1].id, null, false, { code: 4001, message: '没有 popup 能力' })
  await tick(); await tick()
  assert.equal(ok, false)
  let alerted = false
  h.tg.showAlert('x', () => { alerted = true })
  h.reply(h.calls()[2].id, { button_id: '' })
  await tick(); await tick()
  assert.equal(alerted, true)
})

test('云存储:Telegram 的写法 —— 只有回调,读不到的键给空串,方法返回自己', async () => {
  const h = page()
  h.init()
  const got = []
  const ret = h.tg.CloudStorage.getItem('nope', (err, v) => got.push([err, v]))
  assert.equal(ret, h.tg.CloudStorage, '可以链式')
  h.reply(h.calls()[0].id, { items: { nope: null } })
  await tick(); await tick()
  assert.deepEqual(got[0], [null, ''])
  h.tg.CloudStorage.setItem('k', 'v', (err, ok) => got.push([err, ok]))
  await tick()
  h.reply(h.calls()[1].id, { key: 'k', rev: 1 })
  await tick(); await tick()
  assert.deepEqual(got[1], [null, true])
  h.tg.CloudStorage.getItems(['a', 'b'], (err, vs) => got.push([err, vs]))
  h.reply(h.calls()[2].id, { items: { a: { value: '1', rev: 3 }, b: null } })
  await tick(); await tick()
  assert.deepEqual(plain(got[2]), [null, { a: '1', b: '' }])
  h.tg.CloudStorage.removeItem('k', (err) => got.push(['rm', err]))
  h.reply(h.calls()[3].id, null, false, { code: 4005, message: '太频繁' })
  await tick(); await tick()
  assert.equal(got[3][1].code, 4005, '失败时回调第一个参数是错误')
})

test('超级赞没有的接口都有桩:不抛、不发桥调用,按 Telegram 的回调 / 事件约定回「不支持」', async () => {
  const h = page()
  h.init()
  const warns = []
  const origWarn = console.warn
  console.warn = (m) => warns.push(String(m))
  const cb = {}
  const ev = {}
  for (const name of ['invoiceClosed', 'emojiStatusFailed', 'emojiStatusAccessRequested', 'shareMessageFailed',
    'fileDownloadRequested', 'homeScreenChecked', 'scanQrPopupClosed', 'clipboardTextReceived', 'writeAccessRequested',
    'contactRequested', 'requestedChatFailed', 'locationManagerUpdated', 'biometricManagerUpdated',
    'biometricAuthRequested', 'accelerometerFailed', 'deviceOrientationFailed', 'gyroscopeFailed']) {
    h.tg.onEvent(name, function (d) { ev[name] = { d, self: this } })
  }
  const tg = h.tg
  try {
    for (const fn of ['sendData', 'switchInlineQuery', 'openTelegramLink', 'shareToStory', 'addToHomeScreen',
      'closeScanQrPopup', 'hideKeyboard']) {
      assert.equal(typeof tg[fn], 'function', fn)
      assert.doesNotThrow(() => tg[fn]('x'), fn)
    }
    tg.openInvoice('https://t.me/$abc', (s) => { cb.invoice = s })
    tg.setEmojiStatus('123', (ok) => { cb.emoji = ok })
    tg.requestEmojiStatusAccess((ok) => { cb.emojiAccess = ok })
    tg.shareMessage('m1', (ok) => { cb.shareMessage = ok })
    tg.downloadFile({ url: 'https://a.example/f.pdf', file_name: 'f.pdf' }, (ok) => { cb.download = ok })
    tg.checkHomeScreenStatus((s) => { cb.home = s })
    tg.showScanQrPopup({ text: '扫一扫' }, () => { cb.qr = 'called' })
    tg.readTextFromClipboard((t) => { cb.clipboard = t })
    tg.requestWriteAccess((ok) => { cb.write = ok })
    tg.requestContact((ok, r) => { cb.contact = [ok, r] })
    tg.requestChat('r1', (ok) => { cb.chat = ok })
    tg.invokeCustomMethod('m', {}, (err, r) => { cb.custom = [err, r] })
    tg.LocationManager.init(() => { cb.locInit = tg.LocationManager.isLocationAvailable })
    tg.LocationManager.getLocation((d) => { cb.loc = d })
    tg.BiometricManager.init(() => { cb.bioInit = tg.BiometricManager.isBiometricAvailable })
    tg.BiometricManager.requestAccess({ reason: 'x' }, (ok) => { cb.bioAccess = ok })
    tg.BiometricManager.authenticate({ reason: 'x' }, (ok, token) => { cb.bioAuth = [ok, token] })
    tg.Accelerometer.start({ refresh_rate: 100 }, (ok) => { cb.acc = ok })
    tg.DeviceOrientation.start({}, (ok) => { cb.ori = ok })
    tg.Gyroscope.start({}, (ok) => { cb.gyro = ok })
    tg.Accelerometer.stop((ok) => { cb.accStop = ok })
    tg.DeviceStorage.getItem('k', (err, v) => { cb.device = [err, v] })
    tg.SecureStorage.restoreItem('k', (err, v) => { cb.secure = [err, v] })
    tg.disableVerticalSwipes()
    assert.equal(tg.isVerticalSwipesEnabled, false)
    tg.isVerticalSwipesEnabled = true
    assert.equal(tg.isVerticalSwipesEnabled, true)
    for (let i = 0; i < 4; i++) await tick()
  } finally {
    console.warn = origWarn
  }
  assert.equal(h.calls().length, 0, '桩不走桥:宿主那边的方法表里没有这些')
  assert.deepEqual(plain(cb), {
    invoice: 'failed', emoji: false, emojiAccess: false, shareMessage: false, download: false, home: 'unsupported',
    clipboard: null, write: false, contact: [false, { status: 'cancelled' }], chat: false, custom: ['UNSUPPORTED', null],
    locInit: false, loc: null, bioInit: false, bioAccess: false, bioAuth: [false, null],
    acc: false, ori: false, gyro: false, accStop: true, device: ['UNSUPPORTED', null], secure: ['UNSUPPORTED', null],
  })
  assert.equal(cb.qr, undefined, '扫码按「用户关了扫码框」回:回调不会被调')
  assert.deepEqual(plain(ev.invoiceClosed.d), { url: 'https://t.me/$abc', status: 'failed' })
  assert.deepEqual(plain(ev.emojiStatusFailed.d), { error: 'UNSUPPORTED' })
  assert.deepEqual(plain(ev.homeScreenChecked.d), { status: 'unsupported' })
  assert.deepEqual(plain(ev.writeAccessRequested.d), { status: 'cancelled' })
  assert.deepEqual(plain(ev.accelerometerFailed.d), { error: 'UNSUPPORTED' })
  assert.ok(ev.scanQrPopupClosed, 'scanQrPopupClosed')
  assert.equal(ev.clipboardTextReceived.self, h.tg, '事件里的 this 也是 Telegram.WebApp')
  assert.ok(warns.some((m) => m.includes('openTelegramLink')), '开发者在控制台看得到哪项不支持')
  assert.equal(warns.filter((m) => m.includes('openTelegramLink')).length, 1)
})

test('颜色:收 Telegram 的写法(#RGB、rgb()、主题色键);写键的跟着换主题重发', async () => {
  const h = page({ hash: frag({ szWebAppThemeParams: JSON.stringify(THEME16) }) })
  h.init()
  h.tg.setHeaderColor('secondary_bg_color')
  h.tg.setBackgroundColor('#abc')
  h.tg.setBottomBarColor('rgb(16, 32, 48)')
  h.tg.setHeaderColor('not-a-color')
  await tick()
  assert.deepEqual(plain(h.calls().map((c) => [c.method, c.params.color])), [
    ['setHeaderColor', '#FBFAF6'], ['setBackgroundColor', '#AABBCC'], ['setBottomBarColor', '#102030']])
  assert.equal(h.tg.headerColor, '#FBFAF6')
  assert.equal(h.tg.bottomBarColor, '#102030')
  await assert.rejects(h.app.setHeaderColor('red'), (e) => e.code === 4004)
  h.deliver({ v: 2, type: 'event', name: 'themeChanged', data: { themeParams: { ...THEME16, secondary_bg_color: '#24231F' } } })
  const last = h.calls().at(-1)
  assert.deepEqual(plain([last.method, last.params]), ['setHeaderColor', { color: '#24231F' }], '顶栏跟着深色走')
  h.tg.headerColor = '#000000'
  assert.equal(h.calls().at(-1).params.color, '#000000', '属性赋值也同步(Telegram 的写法)')
})

test('颜色没设过时读到的是主题默认色', () => {
  const h = page({ hash: frag({ szWebAppThemeParams: JSON.stringify(THEME16) }) })
  assert.equal(h.tg.headerColor, THEME16.header_bg_color)
  assert.equal(h.tg.backgroundColor, THEME16.bg_color)
  assert.equal(h.tg.bottomBarColor, THEME16.bottom_bar_bg_color)
  assert.equal(h.tg.MainButton.color, THEME16.button_color)
  assert.equal(h.tg.MainButton.textColor, THEME16.button_text_color)
  assert.equal(h.tg.SecondaryButton.color, THEME16.bottom_bar_bg_color)
  assert.equal(h.tg.SecondaryButton.textColor, THEME16.button_color)
  assert.equal(h.tg.MainButton.type, 'main')
  assert.equal(h.tg.SecondaryButton.type, 'secondary')
})

test('底栏按钮:属性赋值同步给宿主;颜色只发页面自己设的;showProgress 按 Telegram 的 leaveActive', async () => {
  const h = page()
  h.init()
  let clicks = 0
  const mb = h.tg.MainButton
  mb.onClick(() => { clicks++ })
  mb.text = '下单'
  mb.isVisible = true
  await tick()
  const c1 = h.calls().filter((c) => c.method === 'mainButton')
  assert.equal(c1.length, 1)
  assert.equal(c1[0].params.text, '下单')
  assert.equal(c1[0].params.is_visible, true)
  assert.equal(c1[0].params.color, '', '没设颜色 = 宿主按主题画,不把主题色写死进去')
  mb.showProgress()
  assert.equal(mb.isActive, false)
  h.deliver({ v: 2, type: 'event', name: 'mainButtonClicked' })
  assert.equal(clicks, 0, '加载中不响应')
  mb.hideProgress()
  assert.equal(mb.isActive, true)
  h.deliver({ v: 2, type: 'event', name: 'mainButtonClicked' })
  assert.equal(clicks, 1)
  mb.showProgress(true)
  assert.equal(mb.isActive, true, 'leaveActive=true 时加载中也算可点')
  mb.setParams({ color: '#0a0', has_shine_effect: true })
  await tick()
  const last = h.calls().filter((c) => c.method === 'mainButton').at(-1)
  assert.equal(last.params.color, '#00AA00')
  assert.equal(last.params.has_shine_effect, true)
  h.tg.BackButton.isVisible = true
  assert.deepEqual(plain(h.calls().at(-1).params), { is_visible: true })
})

test('全屏:fullscreenFailed 带 Telegram 的 error 字段;ALREADY_FULLSCREEN 时 isFullscreen 为 true', () => {
  const h = page()
  h.init()
  const got = []
  h.tg.onEvent('fullscreenFailed', (d) => got.push(d))
  h.deliver({ v: 2, type: 'event', name: 'fullscreenFailed', data: { isFullscreen: false } })
  assert.equal(got[0].error, 'UNSUPPORTED', '老宿主不带 error,补成 UNSUPPORTED')
  h.deliver({ v: 2, type: 'event', name: 'fullscreenFailed', data: { error: 'ALREADY_FULLSCREEN', isFullscreen: true } })
  assert.equal(got[1].error, 'ALREADY_FULLSCREEN')
  assert.equal(h.tg.isFullscreen, true)
  h.deliver({ v: 2, type: 'event', name: 'fullscreenChanged', data: { isFullscreen: false } })
  assert.equal(h.app.isFullscreen, false)
})

test('锁方向:isOrientationLocked 跟着宿主的应答走', async () => {
  const h = page()
  h.init()
  const p = h.app.lockOrientation()
  h.reply(h.calls()[0].id, true)
  await p
  assert.equal(h.tg.isOrientationLocked, true)
  const q = h.app.unlockOrientation()
  h.reply(h.calls()[1].id, true)
  await q
  assert.equal(h.tg.isOrientationLocked, false)
})

test('?sz_mock=1:Telegram.WebApp 报 8.0;全屏的状态和事件照真宿主走', async () => {
  const h = page({ mode: 'top', hash: '', search: '?sz_mock=1' })
  assert.equal(h.tg.version, '8.0')
  let changed = 0
  h.tg.onEvent('fullscreenChanged', function () { changed += this.isFullscreen ? 1 : 0 })
  h.tg.requestFullscreen()
  for (let i = 0; i < 4; i++) await tick()
  assert.equal(h.tg.isFullscreen, true)
  assert.equal(changed, 1)
})

test('setBottomBarColor 是宿主 2.1 的新方法:在 BRIDGE_METHODS 里;打包用的 ESM 也导出 Telegram 门面', async () => {
  const mod = await import(new URL('../dist/sz-webapp.mjs', import.meta.url))
  assert.ok(mod.BRIDGE_METHODS.includes('setBottomBarColor'))
  assert.equal(mod.SDK_VERSION, '2.1.0')
  assert.ok(mod.TelegramWebApp)
  assert.equal(typeof mod.TelegramWebApp.openTelegramLink, 'function')
})
