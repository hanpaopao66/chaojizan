// 小游戏存档:本机缓存秒开 + 超级赞云存储(关了再开、换设备接着玩)。和界面无关,测试里换成假的存储。
//
// - 云端两个键:state(当前这一局)和 best(最好成绩、局数)。云存储本来就按(应用, 用户)隔离,键名不用带前缀;
// - 本机缓存的键带 open_id(`snake:v1:<open_id>`):同一台设备换了账号,接不上上一个人的;
// - 这一局按「最后一次改动的时间」谁新用谁;最好成绩两边取并(mergeBest);
// - 往云端写有节流:改动后 delay 毫秒写,两次写至少隔 minGap 毫秒 —— 云存储每个用户每分钟 120 次,
//   实时游戏每一帧都在变,不节流几秒钟就用完了;
// - 没改过的不写:这台设备只是打开看了一眼,关掉时不会拿旧的一局盖掉别的设备上新的;
// - 云端空了而这台设备和云端对过账:是用户在「小程序授权与数据」里清空过,本机也跟着清掉,不偷偷传回去。

export interface CloudLike {
  getItems(keys: string[]): Promise<Record<string, string | null>>
  setItem(key: string, value: string): Promise<unknown>
}

export interface LocalLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export interface Timers {
  set(fn: () => void, ms: number): unknown
  clear(handle: unknown): void
}

export interface SlotOptions<S, B> {
  /** 本机缓存的键,要带上 open_id */
  cacheKey: string
  cloud: CloudLike
  local?: LocalLike | null
  /** 存档里的一局 → 状态;坏的、版本不对的返回 null(当作没有存档) */
  loadState(raw: unknown): S | null
  saveState(s: S): unknown
  loadBest(raw: unknown): B | null
  /** 两份最好成绩合成一份(各项取最好的) */
  mergeBest(a: B, b: B): B
  emptyBest: B
  now?: () => number
  timers?: Timers
  /** 改动后多久往云端写(毫秒),默认 500 */
  delay?: number
  /** 两次往云端写至少隔多久,默认 2000 */
  minGap?: number
  /** 写失败后多久重试,默认 10000 */
  retry?: number
}

/** restoreCloud 的结果:用了云端的 / 留着本机的 / 云端被清空了(本机也清了)/ 连不上 */
export type Restored = 'cloud' | 'local' | 'cleared' | 'offline'

const STATE = 'state'
const BEST = 'best'
const NOT_IN_HOST = 4008

function parse(raw: string | null | undefined): any {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch (_) {
    return null
  }
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export class SaveSlot<S, B> {
  state: S | null = null
  best: B
  /** state 最后一次改动的时间(毫秒) */
  at = 0
  /** 这台设备和云端对过账(读到过或写成功过) */
  private seen = false
  private stateDirty = false
  private bestDirty = false
  private timer: unknown = null
  private lastWrite = -Infinity
  /** 不在超级赞里打开:只存本机 */
  private off = false
  private readonly now: () => number
  private readonly timers: Timers

  constructor(private readonly o: SlotOptions<S, B>) {
    this.best = o.emptyBest
    this.now = o.now || (() => Date.now())
    this.timers = o.timers || { set: (fn, ms) => setTimeout(fn, ms), clear: (h) => clearTimeout(h as number) }
  }

  /** 还有没写到云端的改动 */
  get dirty(): boolean {
    return this.stateDirty || this.bestDirty
  }

  /** ① 本机缓存,同步读、秒开。返回有没有读到一局 */
  restoreLocal(): boolean {
    const o = this.o
    let cached: any = null
    try {
      cached = parse(o.local?.getItem(o.cacheKey))
    } catch (_) {
      cached = null
    }
    if (!cached || typeof cached !== 'object') return false
    this.seen = !!cached.seen
    const b = o.loadBest(cached.best)
    if (b) this.best = o.mergeBest(this.best, b)
    const s = cached.state == null ? null : o.loadState(cached.state)
    if (s) {
      this.state = s
      this.at = Number(cached.at) || 0
    }
    return !!s
  }

  /** ② 云端:别的设备上接着玩过(更新)就换成云端的;本机更新(离线时玩过)就补写上去 */
  async restoreCloud(): Promise<Restored> {
    const o = this.o
    let r: Record<string, string | null>
    try {
      r = await o.cloud.getItems([STATE, BEST])
    } catch (e) {
      if ((e as { code?: number } | null)?.code === NOT_IN_HOST) this.off = true
      return 'offline'
    }
    const rawState = r[STATE] ?? null
    const rawBest = r[BEST] ?? null
    if (rawState === null && rawBest === null && this.seen) {
      this.state = null
      this.at = 0
      this.best = o.emptyBest
      this.seen = false
      this.stateDirty = false
      this.bestDirty = false
      this.writeLocal()
      return 'cleared'
    }
    if (rawState !== null || rawBest !== null) this.seen = true

    const cloudBest = o.loadBest(parse(rawBest))
    if (cloudBest) {
      const merged = o.mergeBest(this.best, cloudBest)
      if (!same(merged, cloudBest)) this.bestDirty = true
      this.best = merged
    } else if (!same(this.best, o.emptyBest)) {
      this.bestDirty = true
    }

    const wrap = parse(rawState)
    const cloudAt = Number(wrap?.at) || 0
    const cloudState = wrap && typeof wrap === 'object' ? o.loadState(wrap.state) : null
    let used: Restored = 'local'
    if (cloudState && cloudAt > this.at) {
      this.state = cloudState
      this.at = cloudAt
      used = 'cloud'
    } else if (this.state && this.at > cloudAt) {
      this.stateDirty = true
    }
    this.writeLocal()
    if (this.dirty) this.schedule()
    return used
  }

  /** 记一次改动。每一步、每一帧都可以调:本机立刻写,云端按节流写 */
  change(s: S): void {
    this.state = s
    this.at = this.now()
    this.stateDirty = true
    this.writeLocal()
    this.schedule()
  }

  /** 更新最好成绩(没变就什么都不做) */
  setBest(b: B): void {
    if (same(b, this.best)) return
    this.best = b
    this.bestDirty = true
    this.writeLocal()
    this.schedule()
  }

  /** 立刻往云端写(暂停、一局结束、切到后台时)。没改过就不写 */
  async flush(): Promise<void> {
    if (this.timer !== null) {
      this.timers.clear(this.timer)
      this.timer = null
    }
    if (this.off || !this.dirty) return
    const writes: Array<[string, string]> = []
    if (this.stateDirty && this.state) {
      writes.push([STATE, JSON.stringify({ at: this.at, state: this.o.saveState(this.state) })])
    }
    if (this.bestDirty) writes.push([BEST, JSON.stringify(this.best)])
    this.stateDirty = false
    this.bestDirty = false
    this.lastWrite = this.now()
    const errors = await Promise.all(writes.map(([k, v]) =>
      this.o.cloud.setItem(k, v).then(() => null, (e: unknown) => e ?? new Error('写失败'))))
    let failed = false
    errors.forEach((e, i) => {
      if (!e) return
      failed = true
      if ((e as { code?: number }).code === NOT_IN_HOST) this.off = true
      if (writes[i][0] === STATE) this.stateDirty = true
      else this.bestDirty = true
    })
    if (errors.some((e) => !e) && !this.seen) {
      this.seen = true
      this.writeLocal()
    }
    if (failed && !this.off) this.schedule(this.o.retry ?? 10000)
  }

  private schedule(wait?: number): void {
    if (this.off || this.timer !== null) return
    const ms = wait ?? Math.max(this.o.delay ?? 500, this.lastWrite + (this.o.minGap ?? 2000) - this.now())
    this.timer = this.timers.set(() => {
      this.timer = null
      void this.flush()
    }, ms)
  }

  private writeLocal(): void {
    const o = this.o
    try {
      o.local?.setItem(o.cacheKey, JSON.stringify({
        state: this.state ? o.saveState(this.state) : null, best: this.best, at: this.at, seen: this.seen,
      }))
    } catch (_) { /* 本机存储满了或者用不了:只靠云端 */ }
  }
}
