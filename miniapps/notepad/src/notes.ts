// 记事本的纯函数:数据形状、标题摘要、时间文案、排序、搜索高亮、上限。
// 和界面、存储都无关 —— test/notes.test.ts 直接测它们。

export const KEY_PREFIX = 'n:'
export const MAX_CHARS = 20000
/** 云存储单个值上限 65,536 字节;留一点给 JSON 外壳 */
export const MAX_VALUE_BYTES = 65000
export const TRASH_DAYS = 30
const DAY = 86400000

export interface Note {
  v: 1
  id: string
  text: string
  pinned: boolean
  created_at: number
  updated_at: number
  /** 进回收站的时间;null 表示没删 */
  deleted_at: number | null
}

/** id 客户端生成、按时间可排序:毫秒时间戳的 36 进制(定长 9 位)+ 4 位随机 */
export function newId(now: number = Date.now(), rand: () => number = Math.random): string {
  const t = now.toString(36).padStart(9, '0')
  let r = ''
  for (let i = 0; i < 4; i++) r += Math.floor(rand() * 36).toString(36)
  return t + r
}

export function keyOf(id: string): string {
  return KEY_PREFIX + id
}

export function newNote(text = '', now: number = Date.now(), id: string = newId(now)): Note {
  return { v: 1, id, text, pinned: false, created_at: now, updated_at: now, deleted_at: null }
}

export function encode(n: Note): string {
  return JSON.stringify({ v: 1, id: n.id, text: n.text, pinned: n.pinned, created_at: n.created_at,
    updated_at: n.updated_at, deleted_at: n.deleted_at })
}

/** 读云存储里的值。认不出的(别的版本、坏数据)返回 null,调用方跳过 —— 绝不因为一条坏数据整页打不开 */
export function decode(raw: string | null | undefined): Note | null {
  if (!raw) return null
  try {
    const o = JSON.parse(raw)
    if (!o || o.v !== 1 || typeof o.id !== 'string' || typeof o.text !== 'string') return null
    return {
      v: 1, id: o.id, text: o.text, pinned: !!o.pinned,
      created_at: Number(o.created_at) || 0, updated_at: Number(o.updated_at) || 0,
      deleted_at: o.deleted_at == null ? null : Number(o.deleted_at),
    }
  } catch (_) {
    return null
  }
}

export function byteLength(s: string): number {
  let n = 0
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i)
    if (c < 0x80) n += 1
    else if (c < 0x800) n += 2
    else if (c >= 0xd800 && c <= 0xdbff) { n += 4; i++ }
    else n += 3
  }
  return n
}

/** 能不能存:字数和字节两道线。返回提示文案,能存返回 null */
export function tooLong(text: string): string | null {
  const chars = [...text].length
  if (chars > MAX_CHARS) return `单条最多 ${MAX_CHARS.toLocaleString()} 字,现在 ${chars.toLocaleString()} 字`
  if (byteLength(encode(newNote(text))) > MAX_VALUE_BYTES) return '这一条太大了,拆成两条再存'
  return null
}

/** 首行即标题 */
export function titleOf(n: Pick<Note, 'text'>): string {
  const line = n.text.split('\n').find((l) => l.trim()) || ''
  return line.trim().slice(0, 60) || '无标题'
}

/** 摘要:标题之后的正文,压成一行 */
export function snippetOf(n: Pick<Note, 'text'>, max = 80): string {
  const lines = n.text.split('\n')
  const first = lines.findIndex((l) => l.trim())
  return lines.slice(first + 1).join(' ').replace(/\s+/g, ' ').trim().slice(0, max)
}

/** 今天 HH:mm / 昨天 / M月D日 / YYYY年M月D日 */
export function timeLabel(ts: number, now: number = Date.now()): string {
  const d = new Date(ts)
  const today = new Date(now)
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  const pad = (x: number) => String(x).padStart(2, '0')
  if (ts >= start) return `今天 ${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (ts >= start - DAY) return '昨天'
  if (d.getFullYear() === today.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日`
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

/** 列表顺序:置顶在前,其余按更新时间倒序;同一时刻按 id 倒序(稳定) */
export function sortNotes(notes: Note[]): Note[] {
  return notes.filter((n) => n.deleted_at == null).sort((a, b) =>
    (Number(b.pinned) - Number(a.pinned)) || (b.updated_at - a.updated_at) || (a.id < b.id ? 1 : -1))
}

/** 回收站:删得晚的在前;过了保留期的不列(启动时顺手清掉) */
export function trashNotes(notes: Note[], now: number = Date.now()): Note[] {
  return notes.filter((n) => n.deleted_at != null && !expired(n, now))
    .sort((a, b) => (b.deleted_at as number) - (a.deleted_at as number))
}

export function expired(n: Note, now: number = Date.now()): boolean {
  return n.deleted_at != null && now - n.deleted_at > TRASH_DAYS * DAY
}

export function daysLeft(n: Note, now: number = Date.now()): number {
  if (n.deleted_at == null) return TRASH_DAYS
  return Math.max(0, Math.ceil((n.deleted_at + TRASH_DAYS * DAY - now) / DAY))
}

/** 本地全文搜索(不区分大小写)。返回命中的笔记,顺序同列表 */
export function search(notes: Note[], q: string): Note[] {
  const needle = q.trim().toLowerCase()
  if (!needle) return sortNotes(notes)
  return sortNotes(notes).filter((n) => n.text.toLowerCase().includes(needle))
}

/** 把文本按关键词切成段,供界面把命中的段包进 <mark>(界面自己转义,这里不拼 HTML) */
export function highlight(text: string, q: string): Array<{ text: string; hit: boolean }> {
  const needle = q.trim().toLowerCase()
  if (!needle) return [{ text, hit: false }]
  const out: Array<{ text: string; hit: boolean }> = []
  const lower = text.toLowerCase()
  let i = 0
  while (i < text.length) {
    const j = lower.indexOf(needle, i)
    if (j < 0) { out.push({ text: text.slice(i), hit: false }); break }
    if (j > i) out.push({ text: text.slice(i, j), hit: false })
    out.push({ text: text.slice(j, j + needle.length), hit: true })
    i = j + needle.length
  }
  return out
}

/** 冲突副本的正文:标题前面加「(冲突副本)」,正文原样 —— 永远不丢字 */
export function conflictCopyText(text: string): string {
  const lines = text.split('\n')
  const first = lines.findIndex((l) => l.trim())
  if (first < 0) return '(冲突副本)'
  lines[first] = '(冲突副本)' + lines[first].trim()
  return lines.join('\n')
}

export function charCount(text: string): number {
  return [...text].length
}
