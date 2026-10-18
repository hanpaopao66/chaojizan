// 官方游戏共用的合成音效/触感:零素材、WebAudio 现场合成、首次交互解锁、静音持久化、并发上限。
//
//   installSfxUnlock()      // 入口处调一次:第一次 pointerdown/keydown 时解锁 AudioContext
//   playSfx('tap')          // 各游戏在关键交互处调;静音/未解锁/不支持时静默返回,永不抛
//   toggleSfxMuted()        // 静音开关:状态存本机(设备级,不跟云存档走)
//   haptic('light')         // 宿主触感(不在宿主里就静默)
//
// 为什么放在 shared:六个老应用之前没有任何音效,新游戏各自写一份音频代码就会五套实现、
// 五套音量口径。音色预设集中在这里,改一处所有游戏一起变。
// 选音原则:短(<350ms)、音量低、峰值不削波、同类 30ms 内不叠(连点不炸音)。
import WebApp from '../../../packages/miniapp-sdk/src/index'

export const CUES = ['tap', 'pick', 'move', 'place', 'merge', 'start', 'ok', 'error',
  'tick', 'toast', 'win', 'lose'] as const
export type Cue = typeof CUES[number]

export type HapticKind = 'light' | 'medium' | 'heavy' | 'success' | 'warning' | 'error'

interface Tone {
  /** 起始频率(Hz) */
  f: number
  /** 结束频率(Hz),不给就保持 */
  to?: number
  /** 时长(秒) */
  d: number
  type: OscillatorType
  /** 相对主音量的增益(0..1) */
  g: number
  /** 相对 cue 开始的延迟(秒) */
  at?: number
  /** 是否混一小段带通白噪声(打击感) */
  noise?: number
}

/** 每个 cue 是 1–4 个音的短序列:游戏里按下按钮/合并/落子都能对上直觉 */
const PRESETS: Record<Cue, Tone[]> = {
  tap: [{ f: 660, d: 0.05, type: 'square', g: 0.10 }],
  pick: [{ f: 880, d: 0.06, type: 'triangle', g: 0.12 }],
  move: [{ f: 440, d: 0.04, type: 'sine', g: 0.08 }],
  place: [{ f: 330, to: 440, d: 0.08, type: 'triangle', g: 0.14, noise: 0.05 }],
  merge: [{ f: 520, to: 780, d: 0.12, type: 'square', g: 0.12 },
    { f: 1040, d: 0.06, type: 'sine', g: 0.06, at: 0.07 }],
  start: [{ f: 440, d: 0.08, type: 'triangle', g: 0.10 },
    { f: 660, d: 0.08, type: 'triangle', g: 0.10, at: 0.07 },
    { f: 880, d: 0.12, type: 'triangle', g: 0.10, at: 0.14 }],
  ok: [{ f: 660, to: 990, d: 0.12, type: 'sine', g: 0.12 }],
  error: [{ f: 180, to: 120, d: 0.18, type: 'sawtooth', g: 0.10 }],
  tick: [{ f: 1200, d: 0.03, type: 'square', g: 0.05 }],
  toast: [{ f: 880, to: 1174, d: 0.10, type: 'sine', g: 0.10 }],
  win: [{ f: 523, d: 0.10, type: 'square', g: 0.10 },
    { f: 659, d: 0.10, type: 'square', g: 0.10, at: 0.09 },
    { f: 784, d: 0.10, type: 'square', g: 0.10, at: 0.18 },
    { f: 1047, d: 0.20, type: 'square', g: 0.10, at: 0.27 }],
  lose: [{ f: 392, to: 196, d: 0.35, type: 'sawtooth', g: 0.10 }],
}

/** 注意:Node 单测里没有 AudioContext,下面所有函数都必须能静默降级 */
const MUTE_KEY = 'superz:sfx:muted'
const MAX_ACTIVE = 8
const SAME_CUE_GAP = 0.03

let ctx: AudioContext | null = null
let master: GainNode | null = null
let active = 0
let muted = readMuted()
let lastAt: Partial<Record<Cue, number>> = {}
let unlockInstalled = false

function readMuted(): boolean {
  try {
    return typeof window !== 'undefined' && window.localStorage.getItem(MUTE_KEY) === '1'
  } catch {
    return false
  }
}

function persistMuted(value: boolean): void {
  try {
    if (typeof window !== 'undefined') window.localStorage.setItem(MUTE_KEY, value ? '1' : '0')
  } catch {
    /* 存储不可用就只在本次会话生效 */
  }
}

function audioContextCtor(): typeof AudioContext | null {
  const w = typeof window !== 'undefined' ? window : undefined
  if (!w) return null
  const Ctor = w.AudioContext || (w as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  return Ctor || null
}

/** 创建/恢复 AudioContext。必须在用户手势里调用(浏览器自动播放策略)。永不抛。 */
export function unlockSfx(): void {
  if (muted) return
  try {
    if (!ctx) {
      const Ctor = audioContextCtor()
      if (!Ctor) return
      ctx = new Ctor()
      const comp = ctx.createDynamicsCompressor()
      comp.threshold.value = -18
      comp.ratio.value = 6
      master = ctx.createGain()
      master.gain.value = 0.35
      master.connect(comp)
      comp.connect(ctx.destination)
    }
    if (ctx.state === 'suspended') void ctx.resume()
  } catch {
    ctx = null
    master = null
  }
}

/** 入口调一次:第一次 pointerdown/keydown 时解锁(只挂一次) */
export function installSfxUnlock(): void {
  if (unlockInstalled || typeof window === 'undefined') return
  unlockInstalled = true
  const once = (): void => { unlockSfx() }
  window.addEventListener('pointerdown', once, { once: true, capture: true })
  window.addEventListener('keydown', once, { once: true, capture: true })
}

export function sfxMuted(): boolean {
  return muted
}

/** 设置静音;返回设置后的状态。静音时不建 AudioContext。 */
export function setSfxMuted(value: boolean): boolean {
  muted = value
  persistMuted(value)
  if (muted) {
    try { void ctx?.suspend() } catch { /* 忽略 */ }
  } else {
    unlockSfx()
  }
  return muted
}

export function toggleSfxMuted(): boolean {
  return setSfxMuted(!muted)
}

function playTone(t: Tone, when: number): void {
  const c = ctx
  const out = master
  if (!c || !out) return
  const start = when + (t.at || 0)
  const end = start + Math.max(0.01, t.d)
  const osc = c.createOscillator()
  const gain = c.createGain()
  osc.type = t.type
  osc.frequency.setValueAtTime(Math.max(30, t.f), start)
  if (t.to) osc.frequency.exponentialRampToValueAtTime(Math.max(30, t.to), end)
  // 5ms 起音防爆音,尾部指数衰减
  gain.gain.setValueAtTime(0.0001, start)
  gain.gain.linearRampToValueAtTime(Math.max(0.0002, t.g), start + 0.005)
  gain.gain.exponentialRampToValueAtTime(0.0001, end)
  osc.connect(gain)
  gain.connect(out)
  osc.start(start)
  osc.stop(end + 0.02)
  active++
  osc.onended = () => { active = Math.max(0, active - 1) }
  if (t.noise) {
    try {
      const len = Math.max(1, Math.round(c.sampleRate * 0.05))
      const buf = c.createBuffer(1, len, c.sampleRate)
      const data = buf.getChannelData(0)
      for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / len)
      const src = c.createBufferSource()
      src.buffer = buf
      const bp = c.createBiquadFilter()
      bp.type = 'bandpass'
      bp.frequency.value = 1800
      const ng = c.createGain()
      ng.gain.value = t.noise
      src.connect(bp)
      bp.connect(ng)
      ng.connect(out)
      src.start(start)
    } catch {
      /* 噪声只是装饰,失败不影响主音 */
    }
  }
}

/** 播放一个音效。静音/未解锁/不支持/太密集时静默返回,永不抛。 */
export function playSfx(cue: Cue, opts: { gain?: number } = {}): void {
  if (muted || !ctx || !master || active >= MAX_ACTIVE) return
  const now = typeof ctx.currentTime === 'number' ? ctx.currentTime : 0
  const last = lastAt[cue]
  if (last !== undefined && now - last < SAME_CUE_GAP) return
  lastAt[cue] = now
  const volume = Math.max(0, Math.min(1, opts.gain ?? 1))
  const when = ctx.currentTime + 0.005
  try {
    for (const t of PRESETS[cue]) playTone({ ...t, g: t.g * volume }, when)
  } catch {
    /* 播放失败不影响游戏 */
  }
}

const HAPTIC: Record<HapticKind, [method: 'impactOccurred' | 'notificationOccurred', arg: string]> = {
  light: ['impactOccurred', 'light'],
  medium: ['impactOccurred', 'medium'],
  heavy: ['impactOccurred', 'heavy'],
  success: ['notificationOccurred', 'success'],
  warning: ['notificationOccurred', 'warning'],
  error: ['notificationOccurred', 'error'],
}

/** 宿主触感。不在宿主里/不支持时静默。 */
export function haptic(kind: HapticKind): void {
  try {
    const api = WebApp.HapticFeedback as unknown as Record<string, (arg?: string) => unknown>
    const [method, arg] = HAPTIC[kind]
    const fn = api[method]
    if (typeof fn === 'function') void fn.call(api, arg)
  } catch {
    /* 不在宿主里 */
  }
}

/** 给单测用的只读预设(音色表本身不导出可变引用,防止被游戏运行时改坏) */
export function presetOf(cue: Cue): ReadonlyArray<Readonly<Tone>> {
  return PRESETS[cue]
}

/** 暴露给单测/调试:当前活跃音源数与是否已解锁 */
export function sfxDebug(): { active: number; unlocked: boolean; muted: boolean } {
  return { active, unlocked: !!ctx, muted }
}
