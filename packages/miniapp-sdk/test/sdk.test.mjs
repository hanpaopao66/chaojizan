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

/** 造一个装好 SDK 的页面。mode: native(手机端注入通道)/ iframe(web 端)/ top(直接打开)/ mock */
function page({ mode = 'native', hash = frag(), search = '', session = {} } = {}) {
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
