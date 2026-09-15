import assert from 'node:assert/strict'
import { test } from 'node:test'
import { rand, randInt, shuffle } from '../src/rand'
import { CloudLike, LocalLike, SaveSlot, SlotOptions } from '../src/save'

// ---------------------------------------------------------------- 假的存储和时钟

class FakeCloud implements CloudLike {
  data: Record<string, string> = {}
  writes: Array<[string, string]> = []
  reads = 0
  /** 设了就让每次调用都失败,带这个错误码 */
  failCode: number | null = null

  async getItems(keys: string[]): Promise<Record<string, string | null>> {
    this.reads++
    if (this.failCode) throw { code: this.failCode }
    const o: Record<string, string | null> = {}
    for (const k of keys) o[k] = this.data[k] ?? null
    return o
  }

  async setItem(key: string, value: string): Promise<unknown> {
    if (this.failCode) throw { code: this.failCode }
    this.data[key] = value
    this.writes.push([key, value])
    return { key, rev: this.writes.length }
  }
}

class FakeLocal implements LocalLike {
  data: Record<string, string> = {}
  getItem(k: string): string | null { return this.data[k] ?? null }
  setItem(k: string, v: string): void { this.data[k] = v }
}

const settle = () => new Promise<void>((r) => setTimeout(r, 0))

function clock() {
  let t = 1_000_000
  let seq = 0
  const q: Array<{ id: number; at: number; fn: () => void }> = []
  return {
    now: () => t,
    timers: {
      set(fn: () => void, ms: number) { const id = ++seq; q.push({ id, at: t + ms, fn }); return id },
      clear(h: unknown) { const i = q.findIndex((x) => x.id === h); if (i >= 0) q.splice(i, 1) },
    },
    /** 往前走 ms 毫秒,到点的定时器按顺序跑 */
    async advance(ms: number) {
      const end = t + ms
      for (;;) {
        q.sort((a, b) => a.at - b.at)
        const next = q[0]
        if (!next || next.at > end) break
        q.shift()
        t = next.at
        next.fn()
        await settle()
      }
      t = end
      await settle()
    },
  }
}

interface S { n: number }
interface B { top: number; games: number }

function slot(cloud: FakeCloud, local: FakeLocal, c = clock(), extra: Partial<SlotOptions<S, B>> = {}) {
  const s = new SaveSlot<S, B>({
    cacheKey: 'demo:v1:o_me', cloud, local, now: c.now, timers: c.timers,
    loadState: (raw) => (raw && typeof (raw as S).n === 'number' ? { n: (raw as S).n } : null),
    saveState: (x) => ({ n: x.n }),
    loadBest: (raw) => (raw && typeof (raw as B).top === 'number' ? (raw as B) : null),
    mergeBest: (a, b) => ({ top: Math.max(a.top, b.top), games: Math.max(a.games, b.games) }),
    emptyBest: { top: 0, games: 0 },
    delay: 500, minGap: 2000, retry: 10000,
    ...extra,
  })
  return { s, c }
}

const cloudState = (cloud: FakeCloud) => JSON.parse(cloud.data.state)

// ---------------------------------------------------------------- 测试

test('本机缓存只认自己的键(换账号接不上);坏缓存当作没有', () => {
  const local = new FakeLocal()
  local.data['demo:v1:o_other'] = JSON.stringify({ state: { n: 9 }, best: { top: 9, games: 1 }, at: 5 })
  const { s } = slot(new FakeCloud(), local)
  assert.equal(s.restoreLocal(), false)
  assert.equal(s.state, null)
  local.data['demo:v1:o_me'] = '{坏的'
  assert.equal(s.restoreLocal(), false)
  local.data['demo:v1:o_me'] = JSON.stringify({ state: { n: 3 }, best: { top: 7, games: 2 }, at: 5 })
  assert.equal(s.restoreLocal(), true)
  assert.deepEqual(s.state, { n: 3 })
  assert.deepEqual(s.best, { top: 7, games: 2 })
})

test('换设备接着玩:云端的更新就用云端的', async () => {
  const cloud = new FakeCloud()
  cloud.data.state = JSON.stringify({ at: 200, state: { n: 42 } })
  cloud.data.best = JSON.stringify({ top: 50, games: 4 })
  const local = new FakeLocal()
  local.data['demo:v1:o_me'] = JSON.stringify({ state: { n: 1 }, best: { top: 10, games: 1 }, at: 100, seen: true })
  const { s, c } = slot(cloud, local)
  s.restoreLocal()
  assert.equal(await s.restoreCloud(), 'cloud')
  assert.deepEqual(s.state, { n: 42 })
  assert.deepEqual(s.best, { top: 50, games: 4 })
  assert.equal(JSON.parse(local.data['demo:v1:o_me']).state.n, 42, '云端的一局写回本机缓存')
  await c.advance(60_000)
  assert.equal(cloud.writes.length, 0, '什么都没改,不往云端写')
})

test('离线时玩过:本机的更新,打开时补写上去;最好成绩两边取并', async () => {
  const cloud = new FakeCloud()
  cloud.data.state = JSON.stringify({ at: 100, state: { n: 1 } })
  cloud.data.best = JSON.stringify({ top: 30, games: 5 })
  const local = new FakeLocal()
  local.data['demo:v1:o_me'] = JSON.stringify({ state: { n: 8 }, best: { top: 40, games: 2 }, at: 300, seen: true })
  const { s, c } = slot(cloud, local)
  s.restoreLocal()
  assert.equal(await s.restoreCloud(), 'local')
  assert.deepEqual(s.state, { n: 8 })
  assert.deepEqual(s.best, { top: 40, games: 5 })
  await c.advance(600)
  assert.deepEqual(cloudState(cloud), { at: 300, state: { n: 8 } })
  assert.deepEqual(JSON.parse(cloud.data.best), { top: 40, games: 5 })
})

test('节流:连着改只写最新的;两次写至少隔 minGap(每分钟 120 次的配额)', async () => {
  const cloud = new FakeCloud()
  const { s, c } = slot(cloud, new FakeLocal())
  for (let i = 1; i <= 5; i++) {
    s.change({ n: i })
    await c.advance(100)
  }
  // 第一次改动后 500ms 写,写的是那一刻最新的
  assert.equal(cloud.writes.length, 1)
  assert.equal(cloudState(cloud).state.n, 5)
  // 模拟实时游戏:每 100ms 变一次,连续 10 秒
  for (let i = 6; i <= 105; i++) {
    s.change({ n: i })
    await c.advance(100)
  }
  const stateWrites = cloud.writes.filter(([k]) => k === 'state').length
  assert.ok(stateWrites >= 5 && stateWrites <= 6, `10 秒里写了 ${stateWrites} 次,应该每 2 秒一次`)
  await c.advance(5000)
  assert.equal(cloudState(cloud).state.n, 105, '停手之后最后一次改动也写上去了')
})

test('本机缓存每次改动都写(关掉时最多丢最后一下云端写)', () => {
  const local = new FakeLocal()
  const { s } = slot(new FakeCloud(), local)
  s.change({ n: 7 })
  assert.equal(JSON.parse(local.data['demo:v1:o_me']).state.n, 7)
})

test('flush 立刻写;没改过就不写;最好成绩没变不写', async () => {
  const cloud = new FakeCloud()
  const { s, c } = slot(cloud, new FakeLocal())
  await s.flush()
  assert.equal(cloud.writes.length, 0)
  s.change({ n: 1 })
  s.setBest({ top: 1, games: 1 })
  await s.flush()
  assert.deepEqual(cloud.writes.map(([k]) => k).sort(), ['best', 'state'])
  s.setBest({ top: 1, games: 1 })
  await s.flush()
  await c.advance(5000)
  assert.equal(cloud.writes.length, 2)
})

test('写失败(限流、断网)会重试,改动不丢', async () => {
  const cloud = new FakeCloud()
  const { s, c } = slot(cloud, new FakeLocal())
  cloud.failCode = 4005
  s.change({ n: 3 })
  await c.advance(600)
  assert.equal(cloud.writes.length, 0)
  assert.equal(s.dirty, true)
  cloud.failCode = null
  await c.advance(10_000)
  assert.equal(cloudState(cloud).state.n, 3)
  assert.equal(s.dirty, false)
})

test('不在超级赞里打开(4008):只存本机,不反复去试', async () => {
  const cloud = new FakeCloud()
  cloud.failCode = 4008
  const local = new FakeLocal()
  const { s, c } = slot(cloud, local)
  assert.equal(await s.restoreCloud(), 'offline')
  s.change({ n: 2 })
  await c.advance(60_000)
  assert.equal(cloud.writes.length, 0)
  assert.equal(cloud.reads, 1)
  assert.equal(JSON.parse(local.data['demo:v1:o_me']).state.n, 2)
})

test('用户在设置里清空了云存储:对过账的设备本机也清掉,不偷偷传回去', async () => {
  const cloud = new FakeCloud()
  const local = new FakeLocal()
  const a = slot(cloud, local)
  a.s.change({ n: 5 })
  a.s.setBest({ top: 5, games: 1 })
  await a.s.flush()
  assert.ok(cloud.data.state)
  cloud.data = {} // 清空
  const b = slot(cloud, local)
  b.s.restoreLocal()
  assert.equal(await b.s.restoreCloud(), 'cleared')
  assert.equal(b.s.state, null)
  assert.deepEqual(b.s.best, { top: 0, games: 0 })
  await b.c.advance(60_000)
  assert.deepEqual(cloud.data, {})
})

test('从没连上过云端的离线存档:云端空着就补写上去(不当成「清空」)', async () => {
  const cloud = new FakeCloud()
  const local = new FakeLocal()
  local.data['demo:v1:o_me'] = JSON.stringify({ state: { n: 4 }, best: { top: 4, games: 1 }, at: 50, seen: false })
  const { s, c } = slot(cloud, local)
  s.restoreLocal()
  assert.equal(await s.restoreCloud(), 'local')
  await c.advance(600)
  assert.equal(cloudState(cloud).state.n, 4)
  assert.equal(JSON.parse(local.data['demo:v1:o_me']).seen, true, '写成功之后记下「对过账」')
})

test('云端的坏存档当作没有,不崩', async () => {
  const cloud = new FakeCloud()
  cloud.data.state = '{"at":999,"state":{"n":"不是数字"}}'
  cloud.data.best = 'garbage'
  const { s } = slot(cloud, new FakeLocal())
  assert.equal(await s.restoreCloud(), 'local')
  assert.equal(s.state, null)
  assert.deepEqual(s.best, { top: 0, games: 0 })
})

test('随机数:同一个种子同一串结果;洗牌不改原数组、元素不多不少', () => {
  const seq = (seed: number) => {
    const out: number[] = []
    let s = seed
    for (let i = 0; i < 5; i++) { let v: number; [v, s] = randInt(s, 100); out.push(v) }
    return out.join(',')
  }
  assert.equal(seq(7), seq(7))
  assert.notEqual(seq(7), seq(8))
  const src = [1, 2, 3, 4, 5, 6, 7]
  const [a] = shuffle(src, 3)
  assert.deepEqual(src, [1, 2, 3, 4, 5, 6, 7])
  assert.deepEqual(a.slice().sort(), src)
  const [x] = rand(1)
  assert.ok(x >= 0 && x < 1)
})
