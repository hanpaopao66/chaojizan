// 记事本的界面。数据规则在 notes.ts,同步在 sync.ts —— 这里只管画和交互。
//
// 开发者文档「示例导读」逐段讲这个文件(docs/miniapp/examples.md)。几个值得抄的做法:
// - 主按钮是宿主原生画的(MainButton),返回键也是(BackButton)—— 页面不自己画顶栏;
// - 有没同步的改动就开「关闭确认」,同步完就关;
// - 所有用户写的字都用 textContent 放进页面,不拼 HTML。
import WebApp from '../../../packages/miniapp-sdk/src/index'
import {
  MAX_CHARS, Note, charCount, daysLeft, highlight, search, snippetOf, timeLabel, titleOf,
  tooLong, trashNotes,
} from './notes'
import { NoteStore, Remote } from './sync'
import './style.css'

const app = document.getElementById('app') as HTMLElement
const toastEl = document.getElementById('toast') as HTMLElement
const SAVE_DELAY = 800
const QUOTA = 5 * 1024 * 1024

// ---------------------------------------------------------------- 存储

const remote: Remote = {
  getKeys: (prefix) => WebApp.CloudStorage.getKeys({ prefix }),
  getItemsWithRev: (keys) => WebApp.CloudStorage.getItemsWithRev(keys),
  setItem: (key, value, ifRev) => WebApp.CloudStorage.setItem(key, value, { ifRev }),
  removeItems: (keys) => WebApp.CloudStorage.removeItems(keys).then(() => undefined),
}
// 本机缓存按 open_id 分开:同一台设备换了账号,看不到上一个人的笔记
const who = WebApp.initDataUnsafe.user?.open_id || 'anon'
const cacheKey = `notepad:v1:${who}`
const store = new NoteStore(remote, {
  load: () => { try { return localStorage.getItem(cacheKey) } catch (_) { return null } },
  save: (s) => { try { localStorage.setItem(cacheKey, s) } catch (_) { /* 满了也不影响云端 */ } },
})

type View = { name: 'list' } | { name: 'edit'; id: string } | { name: 'trash' } | { name: 'about' }
let view: View = { name: 'list' }
let query = ''
let online = navigator.onLine !== false
let syncError = ''
let saveTimer: ReturnType<typeof setTimeout> | undefined
let syncTimer: ReturnType<typeof setTimeout> | undefined

// ---------------------------------------------------------------- 小工具

function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, any> = {},
  ...children: Array<Node | string | null | undefined | false>): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag)
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue
    if (k === 'class') el.className = v
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v)
    else el.setAttribute(k, v === true ? '' : String(v))
  }
  for (const c of children) if (c != null && c !== false) el.append(c)
  return el
}

function marked(text: string, q: string): DocumentFragment {
  const f = document.createDocumentFragment()
  for (const part of highlight(text, q)) f.append(part.hit ? h('mark', {}, part.text) : part.text)
  return f
}

function toast(msg: string, ms = 2400): void {
  toastEl.textContent = msg
  toastEl.hidden = false
  clearTimeout((toast as any).t)
  ;(toast as any).t = setTimeout(() => { toastEl.hidden = true }, ms)
}

function kb(n: number): string {
  if (n === 0) return '0 KB'
  return n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`
}

async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
  } catch (_) {
    const ta = h('textarea', { style: 'position:fixed;opacity:0' }, text) as HTMLTextAreaElement
    document.body.append(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  }
  toast('已复制全文')
}

function applyFallbackTheme(): void {
  // 不在宿主里(本地 ?sz_mock=1 调试)时没有主题变量,跟着系统深浅色走
  const hasHostTheme = Object.keys(WebApp.themeParams).length > 0
  const dark = !hasHostTheme && matchMedia('(prefers-color-scheme: dark)').matches
  document.documentElement.classList.toggle('dark-fallback', dark)
}

// ---------------------------------------------------------------- 同步

function scheduleSync(delay = SAVE_DELAY): void {
  clearTimeout(syncTimer)
  syncTimer = setTimeout(runSync, delay)
}

async function runSync(): Promise<void> {
  try {
    const r = await store.sync()
    syncError = ''
    online = true
    if (r.conflicts.length) {
      toast('有笔记在另一台设备上也改过 —— 两份都留下了,标着「冲突副本」', 4000)
      WebApp.HapticFeedback.notificationOccurred('warning')
    }
  } catch (e: any) {
    if (e?.code === 4006) syncError = '云存储满了(5 MB):删掉一些笔记或清空回收站'
    else if (e?.code === 4009) syncError = '这个小程序已被暂停'
    else { online = false; syncError = '' }
  }
  closingGuard()
  // 列表页只刷新列表本身,不重建搜索框 —— 同步是后台的事,不能把正在打字的人的光标弄丢
  if (view.name === 'list' && refreshList) refreshList()
  else if (view.name === 'edit') renderStatus()
  else render()
}

/** 有没同步的改动就开关闭确认;同步完就关 */
function closingGuard(): void {
  const dirty = store.dirtyCount() > 0
  if (dirty !== WebApp.isClosingConfirmationEnabled) {
    ;(dirty ? WebApp.enableClosingConfirmation() : WebApp.disableClosingConfirmation()).catch(() => undefined)
  }
}

// ---------------------------------------------------------------- 视图切换

function go(next: View): void {
  if (view.name === 'edit') {
    flushEdit()
    // 新建了又一个字没写就离开:不留空笔记
    const cur = store.get(view.id)
    if (cur && !cur.text.trim()) store.purge(cur.id)
  }
  editing = null
  view = next
  window.scrollTo(0, 0)
  render()
}

function render(): void {
  app.textContent = ''
  refreshList = null
  if (view.name === 'list') renderList()
  else if (view.name === 'edit') renderEdit(view.id)
  else if (view.name === 'trash') renderTrash()
  else renderAbout()
  // 主按钮只在列表页出现;其余页面用宿主的返回键
  if (view.name === 'list') {
    WebApp.MainButton.setText('新建笔记').show().enable()
    WebApp.BackButton.hide()
  } else {
    WebApp.MainButton.hide()
    WebApp.BackButton.show()
  }
}

function newNoteAction(): void {
  const n = store.create('')
  go({ name: 'edit', id: n.id })
}

WebApp.MainButton.onClick(newNoteAction)
WebApp.BackButton.onClick(() => go({ name: 'list' }))
WebApp.SettingsButton.show().onClick(() => go({ name: 'about' }))

// ---------------------------------------------------------------- 列表

let refreshList: (() => void) | null = null

function renderList(): void {
  const clear = h('button', { class: 'clear', 'aria-label': '清空搜索', hidden: !query,
    onclick: () => { query = ''; input.value = ''; clear.hidden = true; renderListBody(); input.focus() } }, '清空')
  const input = h('input', {
    type: 'search', placeholder: '搜索笔记', value: query, 'aria-label': '搜索笔记', enterkeyhint: 'search',
    oninput: (e: Event) => {
      query = (e.target as HTMLInputElement).value
      clear.hidden = !query
      renderListBody()
    },
  })
  const banners = h('div', {})
  const bar = h('div', { class: 'bar' }, h('div', { class: 'search' }, input, clear), banners)
  const body = h('div', { id: 'list-body' })
  app.append(bar, body)
  refreshList = renderListBody
  renderListBody()

  function renderListBody(): void {
    banners.textContent = ''
    if (!online) banners.append(h('div', { class: 'banner' }, '离线:改动先存在本机,联网后自动同步'))
    if (syncError) banners.append(h('div', { class: 'banner warn' }, syncError))
    const trashed = trashNotes(store.all()).length
    const shown = search(store.all(), query)
    body.textContent = ''
    if (!shown.length) {
      body.append(h('div', { class: 'empty' },
        h('span', { class: 'big', 'aria-hidden': 'true' }, '记'),
        query ? `没有包含「${query}」的笔记` : '还没有笔记。点「新建笔记」,第一行就是标题。'))
    } else {
      const ul = h('ul', { class: 'list' })
      const now = Date.now()
      for (const n of shown) ul.append(h('li', {}, noteRow(n, now)))
      body.append(ul)
    }
    const used = store.usageBytes()
    body.append(h('div', { class: 'foot' },
      h('span', {}, `已用 ${kb(used)} / 5 MB`),
      h('button', { onclick: () => go({ name: 'trash' }) }, `回收站${trashed ? `(${trashed})` : ''}`),
      h('button', { onclick: () => go({ name: 'about' }) }, '关于'),
    ))
    if (used > QUOTA * 0.9) toast(`云存储快满了:已用 ${kb(used)} / 5 MB`)
    // 本地调试时没有宿主画主按钮,页面自己补一个
    if (WebApp.isMock) body.append(h('button', { class: 'fab', onclick: newNoteAction }, '新建笔记'))
  }
}

function noteRow(n: Note, now: number): HTMLElement {
  const entryDirty = store.isDirty(n.id)
  let pressTimer: ReturnType<typeof setTimeout> | undefined
  const btn = h('button', {
    class: 'note', type: 'button',
    onclick: () => go({ name: 'edit', id: n.id }),
    oncontextmenu: (e: Event) => { e.preventDefault(); actions(n) },
    ontouchstart: () => { pressTimer = setTimeout(() => actions(n), 520) },
    ontouchend: () => clearTimeout(pressTimer),
    ontouchmove: () => clearTimeout(pressTimer),
  },
  h('span', { class: 'title' }, n.pinned ? h('span', { class: 'pin' }, '置顶') : null, marked(titleOf(n), query)),
  h('span', { class: 'time' }, timeLabel(n.updated_at, now), entryDirty ? h('span', { class: 'unsynced' }, '未同步') : null),
  h('span', { class: 'snippet' }, marked(snippetOf(n), query)),
  )
  return btn
}

function actions(n: Note): void {
  WebApp.HapticFeedback.selectionChanged()
  const close = () => { mask.remove(); sheet.remove() }
  const mask = h('div', { class: 'sheet-mask', onclick: close })
  const sheet = h('div', { class: 'sheet', role: 'dialog', 'aria-label': '笔记操作' },
    h('div', { class: 'cap' }, titleOf(n)),
    h('button', { onclick: () => { close(); store.update(n.id, { pinned: !n.pinned }); scheduleSync(); render() } },
      n.pinned ? '取消置顶' : '置顶'),
    h('button', { onclick: () => { close(); share(n) } }, '分享'),
    h('button', { onclick: () => { close(); copy(n.text) } }, '复制全文'),
    h('button', { class: 'danger', onclick: () => { close(); softDelete(n) } }, '删除'),
    h('button', { onclick: close }, '取消'),
  )
  document.body.append(mask, sheet)
}

function share(n: Note): void {
  WebApp.share({ text: n.text.slice(0, 2000) }).catch((e) => {
    if (e?.code === 4008) copy(n.text)
  })
}

function softDelete(n: Note): void {
  store.update(n.id, { deleted_at: Date.now() })
  scheduleSync()
  toast('已移到回收站,30 天内可以恢复')
  if (view.name === 'edit') go({ name: 'list' })
  else render()
}

// ---------------------------------------------------------------- 编辑

let editing: { id: string; area: HTMLTextAreaElement; status: HTMLElement; saved: string } | null = null

function renderEdit(id: string): void {
  const n = store.get(id)
  if (!n) { view = { name: 'list' }; render(); return }
  const area = h('textarea', {
    'aria-label': '笔记内容,第一行是标题', placeholder: '第一行是标题', spellcheck: 'false',
  }) as HTMLTextAreaElement
  area.value = n.text
  const status = h('div', { class: 'status' })
  const pinBtn = h('button', { class: n.pinned ? 'on' : '', onclick: () => {
    const cur = store.get(id)
    if (!cur) return
    store.update(id, { pinned: !cur.pinned })
    pinBtn.classList.toggle('on', !cur.pinned)
    pinBtn.textContent = cur.pinned ? '置顶' : '已置顶'
    WebApp.HapticFeedback.selectionChanged()
    scheduleSync()
  } }, n.pinned ? '已置顶' : '置顶')
  const tools = h('div', { class: 'tools' },
    WebApp.isMock || !WebApp.inHost ? h('button', { class: 'back', onclick: () => go({ name: 'list' }) }, '‹ 笔记') : h('span', { class: 'back' }),
    pinBtn,
    h('button', { onclick: () => { flushEdit(); const cur = store.get(id); if (cur) share(cur) } }, '分享'),
    h('button', { onclick: () => copy(area.value) }, '复制'),
    h('button', { class: 'danger', onclick: () => { flushEdit(); const cur = store.get(id); if (cur) softDelete(cur) } }, '删除'),
  )
  app.append(h('div', { class: 'editor' }, tools, area, status))
  editing = { id, area, status, saved: n.text }
  area.addEventListener('input', () => {
    clearTimeout(saveTimer)
    saveTimer = setTimeout(flushEdit, SAVE_DELAY)
    renderStatus()
  })
  renderStatus()
  if (!n.text) setTimeout(() => area.focus(), 50)
}

/** 停笔 800ms 存一次;离开编辑页、切到后台时再存一次 */
function flushEdit(): void {
  clearTimeout(saveTimer)
  if (!editing) return
  const text = editing.area.value
  if (text === editing.saved) return
  const err = tooLong(text)
  if (err) { toast(err, 3200); renderStatus(); return }
  store.update(editing.id, { text })
  editing.saved = text
  closingGuard()
  scheduleSync()
  renderStatus()
}

function renderStatus(): void {
  if (!editing || view.name !== 'edit') return
  const text = editing.area.value
  const count = charCount(text)
  const state = !text.trim() ? '空白笔记不会保存'
    : text !== editing.saved ? '正在输入…'
    : !online ? '已存在本机,联网后同步'
      : store.isDirty(editing.id) ? '同步中…' : '已保存'
  editing.status.textContent = ''
  editing.status.append(
    h('span', {}, state),
    h('span', { class: count > MAX_CHARS ? 'over' : '' }, `${count.toLocaleString()} / ${MAX_CHARS.toLocaleString()} 字`),
  )
}

// ---------------------------------------------------------------- 回收站

function renderTrash(): void {
  const items = trashNotes(store.all())
  const list = h('div', {})
  for (const n of items) {
    list.append(h('div', { class: 'trash-item' },
      h('span', {}, h('span', { class: 't' }, titleOf(n)), h('span', { class: 'left' }, `${daysLeft(n)} 天后彻底删除`)),
      h('button', { onclick: () => { store.update(n.id, { deleted_at: null }); scheduleSync(); toast('已恢复'); render() } }, '恢复'),
      h('button', { class: 'danger', onclick: async () => {
        if (await confirmAsk('彻底删除这条笔记?删了就找不回来了')) { store.purge(n.id); scheduleSync(); render() }
      } }, '彻底删除'),
    ))
  }
  app.append(h('div', { class: 'page' },
    WebApp.isMock || !WebApp.inHost ? h('button', { class: 'back', onclick: () => go({ name: 'list' }) }, '‹ 笔记') : null,
    h('h1', {}, '回收站'),
    h('p', { class: 'muted' }, '删除的笔记在这里保留 30 天,过期自动彻底删除。'),
    items.length ? list : h('p', { class: 'muted' }, '回收站是空的。'),
    items.length ? h('p', {}, h('button', { class: 'linkish', onclick: async () => {
      if (await confirmAsk(`彻底删除回收站里的 ${items.length} 条笔记?`)) {
        items.forEach((n) => store.purge(n.id)); scheduleSync(); render()
      }
    } }, '清空回收站')) : null,
  ))
}

async function confirmAsk(msg: string): Promise<boolean> {
  try { return await WebApp.showConfirm(msg) } catch (_) { return window.confirm(msg) }
}

// ---------------------------------------------------------------- 关于

function renderAbout(): void {
  app.append(h('div', { class: 'page' },
    WebApp.isMock || !WebApp.inHost ? h('button', { class: 'back', onclick: () => go({ name: 'list' }) }, '‹ 笔记') : null,
    h('h1', {}, '关于记事本'),
    h('p', {}, '超级赞官方小程序。代码在开源仓 miniapps/notepad,也是开发者文档里的参考实现。'),
    h('h2', { style: 'font-size:1rem;margin-top:1.5rem' }, '你的笔记存在哪'),
    h('ul', {},
      h('li', {}, '存在超级赞云存储里,按「应用 + 你的账号」隔离。别的小程序读不到。'),
      h('li', {}, '开发者(这里是官方)不能从服务端读你的笔记:只有你在记事本里打开时才读写。'),
      h('li', {}, '平台管理员在技术上能访问数据库。笔记没有端到端加密。'),
      h('li', {}, '本机也存一份缓存,所以没网也能打开、能写,联网后自动同步。'),
      h('li', {}, '你可以在「我的 → 设置 → 小程序授权与数据」里导出或清空全部笔记;注销账号时一并删除。'),
    ),
    h('h2', { style: 'font-size:1rem;margin-top:1.5rem' }, '多台设备同时改'),
    h('p', {}, '两台设备同时改了同一条,不会互相覆盖:另一台的版本原样保留,这台的另存为「(冲突副本)」,你自己挑。'),
    h('p', { class: 'muted' }, `单条上限 ${MAX_CHARS.toLocaleString()} 字;云存储总共 5 MB、最多约一千条。`),
  ))
}

// ---------------------------------------------------------------- 启动

applyFallbackTheme()
WebApp.onEvent('themeChanged', applyFallbackTheme)
store.load()
store.purgeExpired()
render()
WebApp.ready().catch(() => undefined)
runSync()

window.addEventListener('online', () => { online = true; runSync() })
window.addEventListener('offline', () => { online = false; if (view.name !== 'edit') render(); else renderStatus() })
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') flushEdit()
  else runSync()
})
setInterval(() => { if (document.visibilityState === 'visible' && online) runSync() }, 60000)
