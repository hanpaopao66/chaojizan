import assert from 'node:assert/strict'
import { test } from 'node:test'
import { decode, encode, keyOf, newNote } from '../src/notes'
import { NoteStore, Remote } from '../src/sync'

/** 假的云存储:和服务端同一套 rev 规则(ifRev 不符抛 4007,ifRev=0 = 必须不存在) */
function fakeRemote() {
  const data = new Map<string, { value: string; rev: number }>()
  let offline = false
  const remote: Remote & { data: typeof data; setOffline(v: boolean): void } = {
    data,
    setOffline(v) { offline = v },
    async getKeys(prefix) {
      if (offline) throw Object.assign(new Error('网络'), { code: 5001 })
      return [...data.keys()].filter((k) => k.startsWith(prefix)).sort()
    },
    async getItemsWithRev(keys) {
      if (offline) throw Object.assign(new Error('网络'), { code: 5001 })
      assert.ok(keys.length <= 100, '一次最多 100 个键')
      const o: Record<string, { value: string; rev: number } | null> = {}
      for (const k of keys) o[k] = data.get(k) ?? null
      return o
    },
    async setItem(key, value, ifRev) {
      if (offline) throw Object.assign(new Error('网络'), { code: 5001 })
      const cur = data.get(key)
      if ((cur ? cur.rev : 0) !== ifRev) throw Object.assign(new Error('rev'), { code: 4007 })
      const rev = (cur ? cur.rev : 0) + 1
      data.set(key, { value, rev })
      return { rev }
    },
    async removeItems(keys) { for (const k of keys) data.delete(k) },
  }
  return remote
}

function mem() {
  let s: string | null = null
  return { load: () => s, save: (v: string) => { s = v } }
}

let clock = 1_790_000_000_000
const now = () => ++clock

test('新建 → 同步上去;另一台设备同步下来', async () => {
  const remote = fakeRemote()
  const a = new NoteStore(remote, mem(), now)
  const n = a.create('第一条\n内容')
  assert.equal(a.dirtyCount(), 1)
  const r = await a.sync()
  assert.equal(r.pushed, 1)
  assert.equal(a.dirtyCount(), 0)
  assert.equal(decode(remote.data.get(keyOf(n.id))!.value)!.text, '第一条\n内容')
  const b = new NoteStore(remote, mem(), now)
  assert.equal((await b.sync()).pulled, 1)
  assert.equal(b.all()[0].text, '第一条\n内容')
})

test('离线改 → 本机先存着(刷新也在)→ 联网自动同步', async () => {
  const remote = fakeRemote()
  const disk = mem()
  const a = new NoteStore(remote, disk, now)
  remote.setOffline(true)
  const n = a.create('离线写的')
  await assert.rejects(a.sync())
  const reopened = new NoteStore(remote, disk, now)
  reopened.load()
  assert.equal(reopened.get(n.id)!.text, '离线写的', '本机缓存里有')
  assert.equal(reopened.dirtyCount(), 1)
  remote.setOffline(false)
  await reopened.sync()
  assert.equal(reopened.dirtyCount(), 0)
  assert.ok(remote.data.has(keyOf(n.id)))
})

test('两台设备同时改同一条 → 出现冲突副本,两边的字都在', async () => {
  const remote = fakeRemote()
  const a = new NoteStore(remote, mem(), now)
  const b = new NoteStore(remote, mem(), now)
  const n = a.create('购物\n鸡蛋')
  await a.sync()
  await b.sync()
  a.update(n.id, { text: '购物\n鸡蛋 牛奶' })
  b.update(n.id, { text: '购物\n鸡蛋 面包' })
  await a.sync()
  const r = await b.sync()
  assert.equal(r.conflicts.length, 1)
  await a.sync()
  const texts = a.all().map((x) => x.text).sort()
  assert.deepEqual(texts, ['(冲突副本)购物\n鸡蛋 面包', '购物\n鸡蛋 牛奶'])
  assert.deepEqual(b.all().map((x) => x.text).sort(), texts, '两台设备最后一致')
})

test('两边改成一样的字:不产生副本', async () => {
  const remote = fakeRemote()
  const a = new NoteStore(remote, mem(), now)
  const b = new NoteStore(remote, mem(), now)
  const n = a.create('x')
  await a.sync(); await b.sync()
  a.update(n.id, { text: 'same' })
  b.update(n.id, { text: 'same' })
  await a.sync()
  const r = await b.sync()
  assert.equal(r.conflicts.length, 0)
  assert.equal(b.all().length, 1)
})

test('别的设备彻底删了、本机没改:本机也消失;本机改过:当新笔记存回去', async () => {
  const remote = fakeRemote()
  const a = new NoteStore(remote, mem(), now)
  const b = new NoteStore(remote, mem(), now)
  const keep = a.create('b 会改的')
  const drop = a.create('没人改的')
  await a.sync(); await b.sync()
  a.purge(keep.id); a.purge(drop.id)
  await a.sync()
  b.update(keep.id, { text: 'b 改过了' })
  await b.sync()
  assert.equal(b.get(drop.id), undefined)
  assert.equal(b.get(keep.id)!.text, 'b 改过了')
  assert.equal(decode(remote.data.get(keyOf(keep.id))!.value)!.text, 'b 改过了')
})

test('回收站:软删除照常同步;30 天后彻底删除', async () => {
  const remote = fakeRemote()
  const s = new NoteStore(remote, mem(), now)
  const n = s.create('要删的')
  await s.sync()
  s.update(n.id, { deleted_at: clock - 31 * 86400000 })
  await s.sync()
  assert.ok(decode(remote.data.get(keyOf(n.id))!.value)!.deleted_at)
  assert.equal(s.purgeExpired(), 1)
  await s.sync()
  assert.equal(remote.data.has(keyOf(n.id)), false)
})

test('超过 100 条分批读', async () => {
  const remote = fakeRemote()
  for (let i = 0; i < 230; i++) {
    const n = newNote(`第 ${i} 条`, 1_700_000_000_000 + i, `id${String(i).padStart(10, '0')}`)
    remote.data.set(keyOf(n.id), { value: encode(n), rev: 1 })
  }
  remote.data.set('n:broken', { value: '坏数据', rev: 1 })
  const s = new NoteStore(remote, mem(), now)
  const r = await s.sync()
  assert.equal(r.pulled, 230, '坏数据跳过,不影响其余')
})

test('置顶不改更新时间', () => {
  const s = new NoteStore(fakeRemote(), mem(), now)
  const n = s.create('x')
  const p = s.update(n.id, { pinned: true })!
  assert.equal(p.updated_at, n.updated_at)
})
