// 音效:WebAudio 放短音效。浏览器不许没点过就出声 —— 第一次点击或按键之后才建 AudioContext、才下载音效;
// 静音开关存在这台设备上(localStorage),关着的时候连音效文件都不下载。
import { SOUNDS, SoundName } from './art'

const KEY = 'critters:sound'

let ctx: AudioContext | null = null
let master: GainNode | null = null
const buffers = new Map<SoundName, AudioBuffer>()
let loading: Promise<void> | null = null
const lastAt = new Map<SoundName, number>()
let voices = 0
let muted = readMuted()

function readMuted(): boolean {
  try {
    return window.localStorage.getItem(KEY) === '0'
  } catch (_) {
    return false
  }
}

export function soundOn(): boolean {
  return !muted
}

export function setSound(on: boolean): void {
  muted = !on
  try {
    window.localStorage.setItem(KEY, on ? '1' : '0')
  } catch (_) { /* 存不了就只管这一次 */ }
  if (master) master.gain.value = on ? 1 : 0
  if (on) void unlock()
}

/** 在用户点过之后调:建上下文、下载音效(静音时什么都不做) */
export function unlock(): Promise<void> {
  if (muted) return Promise.resolve()
  const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!AC) return Promise.resolve()
  if (!ctx) {
    try {
      ctx = new AC()
      master = ctx.createGain()
      master.gain.value = 1
      master.connect(ctx.destination)
    } catch (_) {
      ctx = null
      return Promise.resolve()
    }
  }
  if (ctx.state === 'suspended') void ctx.resume().catch(() => undefined)
  if (!loading) {
    const c = ctx
    loading = Promise.all(SOUNDS.map(async (name) => {
      try {
        const res = await fetch(`sfx/${name}.m4a`)
        const data = await res.arrayBuffer()
        const buf = await new Promise<AudioBuffer>((resolve, reject) => {
          // Safari 老版本只认回调写法
          const p = c.decodeAudioData(data, resolve, reject)
          if (p && typeof p.then === 'function') p.then(resolve, reject)
        })
        buffers.set(name, buf)
      } catch (_) { /* 这一个没下载下来:它不响就是了 */ }
    })).then(() => undefined)
  }
  return loading
}

/** 放一个音效。同一个音效 gap 毫秒之内只响一次(几十只小兵同时挨打不会炸耳朵) */
export function play(name: SoundName, opts: { vol?: number; rate?: number; gap?: number } = {}): void {
  if (muted || !ctx || !master) return
  const buf = buffers.get(name)
  if (!buf) return
  const now = performance.now()
  const gap = opts.gap ?? 60
  if (now - (lastAt.get(name) || -1e9) < gap || voices > 14) return
  lastAt.set(name, now)
  try {
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.playbackRate.value = opts.rate ?? 1
    const g = ctx.createGain()
    g.gain.value = opts.vol ?? 0.7
    src.connect(g)
    g.connect(master)
    src.onended = () => {
      voices--
      src.disconnect()
      g.disconnect()
    }
    src.start()
    voices++
  } catch (_) { /* 声音出不来不影响玩 */ }
}

/** 切到后台时停掉,回来再恢复 */
export function suspend(): void {
  if (ctx && ctx.state === 'running') void ctx.suspend().catch(() => undefined)
}

export function resume(): void {
  if (ctx && ctx.state === 'suspended' && !muted) void ctx.resume().catch(() => undefined)
}
