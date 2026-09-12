// 离线优先 + 云存储对账。
//
// - 打开先读本机缓存秒开,再对账:getKeys('n:') + getItems(每批 ≤ 100);
// - 写入带 ifRev。冲突(4007,别的设备先改了)时取回服务器版本:两边文本一样就收下;
//   不一样就**两份都留** —— 服务器那份不动,本机那份另存成「(冲突副本)原标题」,永远不丢字;
// - 别的设备彻底删了、本机又改过:本机那份当新笔记重新存上去(同样是不丢字);
// - 本机缓存按 open_id 分开存:同一台设备换了账号,看不到上一个人的笔记。
//
// 存储接口只用四个方法,测试里换成假的(test/sync.test.ts)。
import { KEY_PREFIX, Note, conflictCopyText, decode, encode, expired, keyOf, newNote } from './notes'

export interface Remote {
  getKeys(prefix: string): Promise<string[]>
  getItemsWithRev(keys: string[]): Promise<Record<string, { value: string; rev: number } | null>>
  /** ifRev 不符时抛出 code === 4007 的错误 */
  setItem(key: string, value: string, ifRev: number): Promise<{ rev: number }>
  removeItems(keys: string[]): Promise<void>
}

export interface Persist {
  load(): string | null
  save(data: string): void
}

export interface Entry {
  note: Note
  /** 服务器上的版本号;0 表示还没存上去过 */
  rev: number
  /** 本机改过、还没同步 */
  dirty: boolean
  /** 彻底删除,等同步时从服务器上删掉 */
  removed?: boolean
}

export interface SyncResult { pulled: number; pushed: number; conflicts: string[] }

const BATCH = 100
const REV_CONFLICT = 4007

export class NoteStore {
  private entries = new Map<string, Entry>()
  private running: Promise<SyncResult> | null = null
  private again = false

  constructor(private remote: Remote, private persist: Persist, private now: () => number = Date.now) {}

  load(): void {
    this.entries.clear()
    try {
      const data = JSON.parse(this.persist.load() || '{}')
      for (const e of data.entries || []) {
        const note = decode(JSON.stringify(e.note))
        if (note) this.entries.set(note.id, { note, rev: Number(e.rev) || 0, dirty: !!e.dirty, removed: !!e.removed })
      }
    } catch (_) {
      this.entries.clear()
    }
  }

  private save(): void {
    this.persist.save(JSON.stringify({ v: 1, entries: [...this.entries.values()] }))
  }

  /** 所有没被彻底删除的笔记(含回收站里的) */
  all(): Note[] {
    return [...this.entries.values()].filter((e) => !e.removed).map((e) => e.note)
  }

  get(id: string): Note | undefined {
    const e = this.entries.get(id)
    return e && !e.removed ? e.note : undefined
  }

  isDirty(id: string): boolean {
    return !!this.entries.get(id)?.dirty
  }

  /** 还没同步的条数(空白的新笔记不算 —— 它不会被存上去) */
  dirtyCount(): number {
    let n = 0
    for (const e of this.entries.values()) if (e.dirty && (e.rev > 0 || e.removed || e.note.text)) n++
    return n
  }

  /** 本机用量(键 + 值的字节数),和服务端配额同一个口径 */
  usageBytes(): number {
    let n = 0
    for (const e of this.entries.values()) {
      if (!e.removed) n += keyOf(e.note.id).length + new TextEncoder().encode(encode(e.note)).length
    }
    return n
  }

  put(note: Note): void {
    const cur = this.entries.get(note.id)
    this.entries.set(note.id, { note, rev: cur?.rev || 0, dirty: true })
    this.save()
  }

  create(text = ''): Note {
    const n = newNote(text, this.now())
    this.put(n)
    return n
  }

  update(id: string, patch: Partial<Pick<Note, 'text' | 'pinned' | 'deleted_at'>>): Note | undefined {
    const cur = this.get(id)
    if (!cur) return undefined
    const next: Note = { ...cur, ...patch, updated_at: this.now() }
    if (patch.pinned !== undefined && patch.text === undefined && patch.deleted_at === undefined) {
      next.updated_at = cur.updated_at  // 置顶不算「改了内容」,不改列表里的时间
    }
    this.put(next)
    return next
  }

  /** 彻底删除:本机立刻消失,同步时删服务器上的 */
  purge(id: string): void {
    const e = this.entries.get(id)
    if (!e) return
    if (e.rev === 0) this.entries.delete(id)
    else this.entries.set(id, { ...e, removed: true, dirty: true })
    this.save()
  }

  /** 回收站里过了 30 天的,彻底删掉 */
  purgeExpired(): number {
    let n = 0
    for (const e of [...this.entries.values()]) {
      if (!e.removed && expired(e.note, this.now())) { this.purge(e.note.id); n++ }
    }
    return n
  }

  /** 对账。并发调用合并成一次,期间又有人要同步就再跑一轮 */
  sync(): Promise<SyncResult> {
    if (this.running) {
      this.again = true
      return this.running
    }
    this.running = this.syncOnce().finally(() => {
      this.running = null
      if (this.again) {
        this.again = false
        this.sync().catch(() => undefined)
      }
    })
    return this.running
  }

  private conflict(e: Entry, server: Note | null, serverRev: number, out: SyncResult): void {
    if (server && server.text === e.note.text) {
      // 内容一样,只是版本号落后:收下服务器的,保留本机的置顶状态
      const pinnedDiffers = server.pinned !== e.note.pinned
      e.note = { ...server, pinned: e.note.pinned }
      e.rev = serverRev
      e.dirty = pinnedDiffers
      return
    }
    const copy = newNote(conflictCopyText(e.note.text), this.now())
    copy.pinned = e.note.pinned
    this.entries.set(copy.id, { note: copy, rev: 0, dirty: true })
    out.conflicts.push(copy.id)
    if (server) {
      e.note = server
      e.rev = serverRev
      e.dirty = false
    } else {
      this.entries.delete(e.note.id)
    }
  }

  private async syncOnce(): Promise<SyncResult> {
    const out: SyncResult = { pulled: 0, pushed: 0, conflicts: [] }
    const keys = (await this.remote.getKeys(KEY_PREFIX)).filter((k) => k.startsWith(KEY_PREFIX))
    const server: Record<string, { value: string; rev: number } | null> = {}
    for (let i = 0; i < keys.length; i += BATCH) {
      Object.assign(server, await this.remote.getItemsWithRev(keys.slice(i, i + BATCH)))
    }
    const seen = new Set<string>()
    for (const [key, item] of Object.entries(server)) {
      if (!item) continue
      const note = decode(item.value)
      const id = key.slice(KEY_PREFIX.length)
      if (!note || note.id !== id) continue
      seen.add(id)
      const e = this.entries.get(id)
      if (!e) {
        this.entries.set(id, { note, rev: item.rev, dirty: false })
        out.pulled++
      } else if (e.removed) {
        continue
      } else if (!e.dirty) {
        if (item.rev !== e.rev) {
          e.note = note
          e.rev = item.rev
          out.pulled++
        }
      } else if (item.rev !== e.rev) {
        this.conflict(e, note, item.rev, out)
      }
    }
    for (const [id, e] of [...this.entries]) {
      if (seen.has(id) || e.rev === 0) continue
      if (e.removed || !e.dirty) {
        this.entries.delete(id)  // 别的设备彻底删了
      } else {
        e.rev = 0                // 别处删了、本机又改过:当新笔记存回去
      }
    }
    for (const e of [...this.entries.values()]) {
      if (!e.dirty) continue
      // 刚新建、一个字还没写的不往上存(离开编辑页时会被丢掉)
      if (e.rev === 0 && !e.removed && !e.note.text) continue
      const key = keyOf(e.note.id)
      if (e.removed) {
        await this.remote.removeItems([key])
        this.entries.delete(e.note.id)
        out.pushed++
        continue
      }
      try {
        const r = await this.remote.setItem(key, encode(e.note), e.rev)
        e.rev = r.rev
        e.dirty = false
        out.pushed++
      } catch (err: any) {
        if (err?.code !== REV_CONFLICT) throw err
        const fresh = (await this.remote.getItemsWithRev([key]))[key]
        this.conflict(e, fresh ? decode(fresh.value) : null, fresh ? fresh.rev : 0, out)
        if (e.dirty && this.entries.get(e.note.id) === e) {
          const r = await this.remote.setItem(key, encode(e.note), e.rev)
          e.rev = r.rev
          e.dirty = false
          out.pushed++
        }
      }
      this.save()
    }
    // 冲突副本是在循环里新加的,补推一遍
    for (const id of out.conflicts) {
      const e = this.entries.get(id)
      if (e && e.dirty) {
        const r = await this.remote.setItem(keyOf(id), encode(e.note), 0)
        e.rev = r.rev
        e.dirty = false
        out.pushed++
      }
    }
    this.save()
    return out
  }
}
