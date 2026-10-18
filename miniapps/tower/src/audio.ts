// 音效与 BGM:全部用 WebAudio 现场合成(振荡器 + 包络 + 程序生成的白噪声),不加载任何音频文件。
// 浏览器规定没被用户点过不许出声:第一次 pointerdown / keydown 时 unlock() 建 AudioContext。
// 静音开关存在这台设备上(localStorage);切后台时 suspend() 会把 BGM 的调度也停掉。
import type { GameEvent, Theme } from './types'

const KEY = 'tower:sound'

export type Sfx =
  | 'tap' | 'build' | 'upgrade' | 'sell' | 'error' | 'summon'
  | 'pea' | 'frost' | 'pepper' | 'vine' | 'mushroom' | 'bow'
  | 'hit' | 'kill' | 'leak' | 'freeze' | 'poison' | 'burn' | 'split' | 'cloud'
  | 'coin' | 'wave' | 'waveClear' | 'boss' | 'win' | 'lose'

let ctx: AudioContext | null = null
let master: GainNode | null = null
let bgmGain: GainNode | null = null
let noiseBuf: AudioBuffer | null = null
let muted = readMuted()
let voices = 0
const lastAt = new Map<Sfx, number>()

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
  if (master) master.gain.value = on ? 0.6 : 0
  if (on) {
    unlock()
    if (bgmTheme) startTimer()
  } else {
    stopTimer()
  }
}

/** 用户点过页面之后调:建 AudioContext(静音时什么都不做) */
export function unlock(): void {
  if (muted) return
  const AC = window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!AC) return
  if (!ctx) {
    try {
      ctx = new AC()
      master = ctx.createGain()
      master.gain.value = 0.6
      master.connect(ctx.destination)
      bgmGain = ctx.createGain()
      bgmGain.gain.value = 0.55
      bgmGain.connect(master)
    } catch (_) {
      ctx = null
      master = null
      bgmGain = null
      return
    }
  }
  if (ctx.state === 'suspended') void ctx.resume().catch(() => undefined)
}

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
  to?: number
  /** 相对现在的延迟(秒) */
  delay?: number
  /** 绝对开始时间(秒);BGM 用 */
  at?: number
  attack?: number
  /** 发到 BGM 的总线上,音量再压一点 */
  bgm?: boolean
}

/** 一个带包络的振荡器(峰值音量不高,连发也不会削波) */
function tone(freq: number, dur: number, o: ToneOpts = {}): void {
  const c = ac()
  if (!c || !master || voices > 20) return
  const t = o.at ?? c.currentTime + (o.delay ?? 0)
  const osc = c.createOscillator()
  osc.type = o.type ?? 'triangle'
  osc.frequency.setValueAtTime(Math.max(20, freq), t)
  if (o.to) osc.frequency.exponentialRampToValueAtTime(Math.max(20, o.to), t + dur)
  const g = c.createGain()
  const v = Math.max(0.0002, o.vol ?? 0.12)
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(v, t + (o.attack ?? 0.008))
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  osc.connect(g)
  g.connect(o.bgm && bgmGain ? bgmGain : master)
  osc.start(t)
  osc.stop(t + dur + 0.03)
  if (!o.bgm) {
    voices++
    osc.onended = () => {
      voices--
      osc.disconnect()
      g.disconnect()
    }
  }
}

interface NoiseOpts {
  vol?: number
  freq?: number
  q?: number
  delay?: number
  at?: number
  type?: BiquadFilterType
  bgm?: boolean
}

/** 程序生成的白噪声(只建一次),过一道滤波器做出打击/风声 */
function noise(dur: number, o: NoiseOpts = {}): void {
  const c = ac()
  if (!c || !master || voices > 20) return
  if (!noiseBuf) {
    const len = Math.floor(c.sampleRate * 0.5)
    noiseBuf = c.createBuffer(1, len, c.sampleRate)
    const data = noiseBuf.getChannelData(0)
    for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1
  }
  const t = o.at ?? c.currentTime + (o.delay ?? 0)
  const src = c.createBufferSource()
  src.buffer = noiseBuf
  const filter = c.createBiquadFilter()
  filter.type = o.type ?? 'bandpass'
  filter.frequency.setValueAtTime(o.freq ?? 900, t)
  filter.Q.value = o.q ?? 0.8
  const g = c.createGain()
  const v = Math.max(0.0002, o.vol ?? 0.1)
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(v, t + 0.006)
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  src.connect(filter)
  filter.connect(g)
  g.connect(o.bgm && bgmGain ? bgmGain : master)
  src.start(t)
  src.stop(t + dur + 0.03)
  if (!o.bgm) {
    voices++
    src.onended = () => {
      voices--
      src.disconnect()
      filter.disconnect()
      g.disconnect()
    }
  }
}

/** 同类音效 45 毫秒内只响一次(一群虫同时被打中也不炸耳朵) */
function throttle(name: Sfx): boolean {
  const now = performance.now()
  if (now - (lastAt.get(name) ?? -1e9) < 45) return false
  lastAt.set(name, now)
  return true
}

export function play(name: Sfx, opts: { rate?: number; vol?: number } = {}): void {
  if (muted) return
  if (!ctx) unlock()
  if (!ctx || !master) return
  if (voices > 20 || !throttle(name)) return
  const rate = opts.rate ?? 1
  const vol = opts.vol ?? 1
  const v = (x: number): number => x * vol
  switch (name) {
    case 'tap':
      tone(760 * rate, 0.05, { type: 'sine', vol: v(0.08), to: 620 * rate })
      break
    case 'build':
      tone(320, 0.1, { vol: v(0.14), to: 520 })
      noise(0.08, { vol: v(0.06), freq: 1500 })
      break
    case 'upgrade':
      tone(523, 0.12, { type: 'sine', vol: v(0.12) })
      tone(784, 0.16, { type: 'sine', vol: v(0.1), delay: 0.08 })
      break
    case 'sell':
      tone(660, 0.08, { type: 'square', vol: v(0.07), to: 440 })
      break
    case 'error':
      tone(160, 0.08, { type: 'square', vol: v(0.08) })
      tone(140, 0.1, { type: 'square', vol: v(0.08), delay: 0.07 })
      break
    case 'summon':
      tone(392, 0.12, { type: 'triangle', vol: v(0.12), to: 523 })
      tone(523, 0.14, { type: 'triangle', vol: v(0.1), delay: 0.08 })
      break
    case 'pea':
      tone(520 * rate, 0.07, { type: 'triangle', vol: v(0.11), to: 340 * rate })
      noise(0.04, { vol: v(0.05), freq: 1700 })
      break
    case 'frost':
      tone(1180, 0.16, { type: 'sine', vol: v(0.09) })
      tone(1760, 0.12, { type: 'sine', vol: v(0.06), delay: 0.02 })
      break
    case 'pepper':
      tone(150, 0.1, { type: 'sawtooth', vol: v(0.1), to: 70 })
      noise(0.12, { vol: v(0.09), freq: 700, q: 0.6 })
      break
    case 'vine':
      tone(900 * rate, 0.07, { type: 'square', vol: v(0.06), to: 260 * rate })
      noise(0.05, { vol: v(0.05), freq: 2600, q: 1.2 })
      break
    case 'mushroom':
      tone(230, 0.12, { type: 'sine', vol: v(0.1), to: 170 })
      noise(0.1, { vol: v(0.05), freq: 500, type: 'lowpass' })
      break
    case 'bow':
      tone(280, 0.09, { type: 'triangle', vol: v(0.12), to: 160 })
      noise(0.06, { vol: v(0.06), freq: 1900 })
      break
    case 'hit':
      tone(180, 0.05, { type: 'square', vol: v(0.06), to: 90 })
      break
    case 'kill':
      tone(220, 0.1, { type: 'triangle', vol: v(0.09), to: 110 })
      noise(0.06, { vol: v(0.05), freq: 600, type: 'lowpass' })
      break
    case 'leak':
      tone(140, 0.22, { type: 'sine', vol: v(0.16), to: 70 })
      noise(0.16, { vol: v(0.08), freq: 300, type: 'lowpass' })
      break
    case 'freeze':
      tone(1500, 0.18, { type: 'sine', vol: v(0.07), to: 2100 })
      break
    case 'poison':
      tone(200, 0.12, { type: 'sawtooth', vol: v(0.05), to: 150 })
      break
    case 'burn':
      noise(0.14, { vol: v(0.06), freq: 900 })
      break
    case 'split':
      tone(360, 0.08, { type: 'square', vol: v(0.07), to: 520 })
      tone(300, 0.08, { type: 'square', vol: v(0.06), delay: 0.05, to: 460 })
      break
    case 'cloud':
      noise(0.3, { vol: v(0.06), freq: 420, type: 'lowpass' })
      break
    case 'coin':
      tone(988, 0.07, { type: 'sine', vol: v(0.07) })
      tone(1319, 0.1, { type: 'sine', vol: v(0.06), delay: 0.05 })
      break
    case 'wave':
      tone(392, 0.16, { type: 'triangle', vol: v(0.12) })
      tone(587, 0.2, { type: 'triangle', vol: v(0.1), delay: 0.12 })
      break
    case 'waveClear':
      for (const [i, f] of [523, 659, 784].entries()) {
        tone(f, 0.16, { type: 'sine', vol: v(0.09), delay: i * 0.07 })
      }
      break
    case 'boss':
      tone(98, 0.6, { type: 'sawtooth', vol: v(0.14), to: 62, attack: 0.04 })
      noise(0.4, { vol: v(0.07), freq: 200, type: 'lowpass' })
      break
    case 'win':
      for (const [i, f] of [523, 659, 784, 1046].entries()) {
        tone(f, 0.26, { type: 'triangle', vol: v(0.12), delay: i * 0.11 })
      }
      break
    case 'lose':
      for (const [i, f] of [392, 330, 262, 196].entries()) {
        tone(f, 0.3, { type: 'sawtooth', vol: v(0.09), delay: i * 0.13 })
      }
      break
  }
}

// ---------------------------------------------------------------- BGM

interface Music {
  /** 每 8 个十六分音符换一个和弦 */
  chords: number[][]
  /** 十六分音符时长(秒) */
  step: number
  /** 低音相对和弦根音 */
  bass: number
}

const MUSIC: Record<Theme, Music> = {
  garden: {
    step: 0.22,
    chords: [
      [261.63, 329.63, 392.0],
      [293.66, 349.23, 440.0],
      [246.94, 293.66, 392.0],
      [220.0, 261.63, 329.63],
    ],
    bass: 0.5,
  },
  orchard: {
    step: 0.25,
    chords: [
      [233.08, 293.66, 349.23],
      [261.63, 329.63, 392.0],
      [207.65, 261.63, 311.13],
      [196.0, 246.94, 293.66],
    ],
    bass: 0.5,
  },
  nest: {
    step: 0.26,
    chords: [
      [220.0, 277.18, 329.63],
      [196.0, 246.94, 293.66],
      [174.61, 220.0, 261.63],
      [164.81, 207.65, 246.94],
    ],
    bass: 0.5,
  },
}

let bgmTheme: Theme | null = null
let bgmTimer: number | null = null
let bgmStep = 0
let nextAt = 0

function scheduleStep(_c: AudioContext, t: number, theme: Theme): void {
  const m = MUSIC[theme]
  const chord = m.chords[Math.floor(bgmStep / 8) % m.chords.length]
  const n = bgmStep % 8
  // 分解和弦:每两个十六分音符一个音,高八度,很轻
  if (n % 2 === 0) {
    const freq = chord[(n / 2) % chord.length] * 2
    tone(freq, 0.16, { type: 'sine', vol: 0.035, at: t, bgm: true })
  }
  // 低音:每小节第一拍
  if (n === 0) tone(chord[0] * m.bass, 0.5, { type: 'triangle', vol: 0.05, at: t, bgm: true })
  if (n === 4) tone(chord[0] * m.bass * 1.5, 0.3, { type: 'triangle', vol: 0.03, at: t, bgm: true })
  // 打击:轻噪声,别吵
  if (n === 0 || n === 4) noise(0.05, { freq: 3000, vol: 0.012, at: t, bgm: true, type: 'highpass' })
  if (n === 6) noise(0.08, { freq: 900, vol: 0.01, at: t, bgm: true })
}

function tick(): void {
  const c = ac()
  if (!c || !bgmTheme) return
  while (nextAt < c.currentTime + 0.4) {
    scheduleStep(c, nextAt, bgmTheme)
    nextAt += MUSIC[bgmTheme].step
    bgmStep++
  }
}

function startTimer(): void {
  if (bgmTimer !== null || !bgmTheme || muted) return
  const c = ac()
  if (!c) return
  nextAt = Math.max(nextAt, c.currentTime + 0.1)
  bgmTimer = window.setInterval(tick, 120)
}

function stopTimer(): void {
  if (bgmTimer !== null) {
    window.clearInterval(bgmTimer)
    bgmTimer = null
  }
}

/** 进关时换 BGM;传 null 停 */
export function bgm(theme: Theme | null): void {
  if (theme === bgmTheme && (theme === null || bgmTimer !== null || muted)) return
  stopTimer()
  bgmTheme = theme
  bgmStep = 0
  if (theme && !muted) startTimer()
}

/** 切到后台时停掉 BGM 调度并挂起上下文 */
export function suspend(): void {
  stopTimer()
  if (ctx && ctx.state === 'running') void ctx.suspend().catch(() => undefined)
}

/** 回到前台恢复 */
export function resume(): void {
  if (!ctx) return
  if (ctx.state === 'suspended' && !muted) {
    void ctx.resume().catch(() => undefined)
    if (bgmTheme) startTimer()
  }
}

/** 引擎事件 → 音效(界面只调这一个)" */
export function sfxForEvent(e: GameEvent): void {
  switch (e.e) {
    case 'shot':
      if (e.kind === 'pea') play('pea')
      else if (e.kind === 'frost') play('frost')
      else if (e.kind === 'pepper') play('pepper')
      else if (e.kind === 'vine') play('vine')
      else if (e.kind === 'mushroom') play('mushroom')
      else if (e.kind === 'bow') play('bow')
      break
    case 'chain':
      play('vine')
      break
    case 'boom':
      play('pepper')
      break
    case 'hit':
      play('hit')
      break
    case 'kill':
      play('kill')
      break
    case 'leak':
      play('leak')
      break
    case 'freeze':
      play('freeze')
      break
    case 'poison':
      play('poison')
      break
    case 'burn':
      play('burn')
      break
    case 'split':
      play('split')
      break
    case 'cloud':
      play('cloud')
      break
    case 'wave':
      play('wave')
      break
    case 'waveClear':
      play('waveClear')
      break
    case 'boss':
      play('boss')
      break
    case 'build':
      play('build')
      break
    case 'upgrade':
      play('upgrade')
      break
    case 'sell':
      play('sell')
      break
    case 'win':
      play('win')
      break
    case 'lose':
      play('lose')
      break
    case 'gold':
      // 波次奖励和卖塔金币的提示音已经由 waveClear/sell 出了,这里不再叠
      break
  }
}

/** 一批事件的音效(同帧多次同类会被 throttle 合并) */
export function sfxForEvents(events: readonly GameEvent[]): void {
  for (const e of events) sfxForEvent(e)
}
