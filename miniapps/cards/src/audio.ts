// 音效:全部用 WebAudio 现场合成(振荡器 + 包络 + 程序生成的白噪声),不加载任何音频文件。
// 浏览器规定没被用户点过不许出声:第一次 pointerdown / keydown 时 unlock() 建 AudioContext。
// 静音开关存在这台设备上(localStorage),关掉时连 AudioContext 都不建。
import type { Ev } from './types'

const KEY = 'cards:sound'

export type SoundName =
  | 'tap' | 'play' | 'summon' | 'attack' | 'hit' | 'heal' | 'shield' | 'death' | 'draw'
  | 'turn' | 'victory' | 'defeat' | 'error' | 'fatigue' | 'burn' | 'buff'

let ctx: AudioContext | null = null
let master: GainNode | null = null
let muted = readMuted()
let noiseBuf: AudioBuffer | null = null
let voices = 0
const lastAt = new Map<SoundName, number>()

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
  if (master) master.gain.value = on ? 0.55 : 0
  if (on) unlock()
}

/** 用户点过页面之后调:建 AudioContext(静音时什么都不做) */
export function unlock(): void {
  if (muted) return
  const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!AC) return
  if (!ctx) {
    try {
      ctx = new AC()
      master = ctx.createGain()
      master.gain.value = 0.55
      master.connect(ctx.destination)
    } catch (_) {
      ctx = null
      master = null
      return
    }
  }
  if (ctx.state === 'suspended') void ctx.resume().catch(() => undefined)
}

/** 拿上下文;静音、没解锁、浏览器不支持都返回 null(调用处不用判断) */
function ac(): AudioContext | null {
  if (muted) return null
  if (!ctx) unlock()
  if (!ctx || !master) return null
  if (ctx.state === 'suspended') void ctx.resume().catch(() => undefined)
  return ctx
}

interface ToneOpts {
  type?: OscillatorType
  vol?: number
  /** 频率滑到哪儿 */
  to?: number
  delay?: number
  attack?: number
}

/** 一个带包络的振荡器 */
function tone(freq: number, dur: number, o: ToneOpts = {}): void {
  const c = ac()
  if (!c || !master || voices > 18) return
  const t = c.currentTime + (o.delay ?? 0)
  const osc = c.createOscillator()
  osc.type = o.type ?? 'triangle'
  osc.frequency.setValueAtTime(Math.max(20, freq), t)
  if (o.to) osc.frequency.exponentialRampToValueAtTime(Math.max(20, o.to), t + dur)
  const g = c.createGain()
  const v = Math.max(0.0002, o.vol ?? 0.16)
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(v, t + (o.attack ?? 0.008))
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  osc.connect(g)
  g.connect(master)
  osc.start(t)
  osc.stop(t + dur + 0.03)
  voices++
  osc.onended = () => {
    voices--
    osc.disconnect()
    g.disconnect()
  }
}

interface NoiseOpts {
  vol?: number
  freq?: number
  q?: number
  delay?: number
  type?: BiquadFilterType
}

/** 程序生成的白噪声(只建一次),过一道滤波器做出打击 / 风声的感觉 */
function noise(dur: number, o: NoiseOpts = {}): void {
  const c = ac()
  if (!c || !master || voices > 18) return
  if (!noiseBuf) {
    const len = Math.floor(c.sampleRate * 0.5)
    noiseBuf = c.createBuffer(1, len, c.sampleRate)
    const data = noiseBuf.getChannelData(0)
    for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1
  }
  const t = c.currentTime + (o.delay ?? 0)
  const src = c.createBufferSource()
  src.buffer = noiseBuf
  const filter = c.createBiquadFilter()
  filter.type = o.type ?? 'bandpass'
  filter.frequency.setValueAtTime(o.freq ?? 900, t)
  filter.Q.value = o.q ?? 0.8
  const g = c.createGain()
  const v = Math.max(0.0002, o.vol ?? 0.14)
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(v, t + 0.006)
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  src.connect(filter)
  filter.connect(g)
  g.connect(master)
  src.start(t)
  src.stop(t + dur + 0.03)
  voices++
  src.onended = () => {
    voices--
    src.disconnect()
    filter.disconnect()
    g.disconnect()
  }
}

/** 同一类音效 55 毫秒内只响一次(群体伤害一下打好几只也不炸耳朵) */
function throttle(name: SoundName): boolean {
  const now = performance.now()
  if (now - (lastAt.get(name) ?? -1e9) < 55) return false
  lastAt.set(name, now)
  return true
}

export function play(name: SoundName): void {
  if (muted) return
  if (!ctx) unlock()
  if (!ctx || !master) return
  if (voices > 18 || !throttle(name)) return
  switch (name) {
    case 'tap':
      tone(760, 0.06, { type: 'sine', vol: 0.1, to: 640 })
      break
    case 'play':
      tone(300, 0.12, { vol: 0.16, to: 520 })
      noise(0.1, { vol: 0.07, freq: 1600 })
      break
    case 'summon':
      tone(420, 0.13, { vol: 0.12, to: 640 })
      tone(840, 0.1, { type: 'sine', vol: 0.06, delay: 0.05 })
      break
    case 'attack':
      noise(0.15, { vol: 0.2, freq: 620, q: 0.6, type: 'lowpass' })
      tone(150, 0.15, { type: 'sawtooth', vol: 0.12, to: 80 })
      break
    case 'hit':
      tone(190, 0.09, { type: 'square', vol: 0.1, to: 90 })
      noise(0.08, { vol: 0.1, freq: 300, type: 'lowpass' })
      break
    case 'heal':
      tone(523, 0.14, { type: 'sine', vol: 0.12 })
      tone(659, 0.16, { type: 'sine', vol: 0.12, delay: 0.09 })
      tone(784, 0.2, { type: 'sine', vol: 0.1, delay: 0.18 })
      break
    case 'shield':
      tone(1200, 0.2, { type: 'sine', vol: 0.11 })
      tone(1800, 0.14, { type: 'sine', vol: 0.07, delay: 0.02 })
      break
    case 'death':
      tone(220, 0.28, { type: 'sawtooth', vol: 0.12, to: 60 })
      noise(0.2, { vol: 0.08, freq: 400, type: 'lowpass' })
      break
    case 'draw':
      noise(0.05, { vol: 0.07, freq: 2600, q: 1.2 })
      break
    case 'turn':
      tone(523, 0.16, { type: 'sine', vol: 0.12 })
      tone(784, 0.22, { type: 'sine', vol: 0.1, delay: 0.1 })
      break
    case 'victory':
      for (const [i, f] of [523, 659, 784, 1046].entries()) {
        tone(f, 0.26, { delay: i * 0.11, vol: 0.14 })
      }
      break
    case 'defeat':
      for (const [i, f] of [392, 330, 262, 196].entries()) {
        tone(f, 0.3, { delay: i * 0.13, vol: 0.12, type: 'sawtooth' })
      }
      break
    case 'error':
      tone(160, 0.09, { type: 'square', vol: 0.1 })
      tone(140, 0.12, { type: 'square', vol: 0.1, delay: 0.08 })
      break
    case 'fatigue':
      tone(90, 0.32, { type: 'sine', vol: 0.18, to: 50 })
      noise(0.25, { vol: 0.08, freq: 200, type: 'lowpass' })
      break
    case 'burn':
      noise(0.22, { vol: 0.1, freq: 1300, q: 0.5 })
      tone(180, 0.18, { type: 'sawtooth', vol: 0.06, to: 110 })
      break
    case 'buff':
      tone(660, 0.12, { vol: 0.1, to: 990 })
      break
  }
}

/** 切到后台时停掉,回来再恢复 */
export function suspend(): void {
  if (ctx && ctx.state === 'running') void ctx.suspend().catch(() => undefined)
}

export function resume(): void {
  if (ctx && ctx.state === 'suspended' && !muted) void ctx.resume().catch(() => undefined)
}

/** 引擎事件 → 音效(界面只调这一个,免得每个动作都写一遍声音) */
export function sfxForEvent(e: Ev): void {
  switch (e.e) {
    case 'play': play('play'); break
    case 'summon': play('summon'); break
    case 'attack': play('attack'); break
    case 'damage': if (e.amount > 0) play('hit'); break
    case 'shield': play('shield'); break
    case 'death': play('death'); break
    case 'heal': play('heal'); break
    case 'buff': play('buff'); break
    case 'draw': play('draw'); break
    case 'fatigue': play('fatigue'); break
    case 'burn': play('burn'); break
    case 'turn': play('turn'); break
    case 'over': play(e.winner === 0 ? 'victory' : 'defeat'); break
  }
}
