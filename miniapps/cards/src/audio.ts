// 音效与 BGM:全部用 WebAudio 现场合成(振荡器 + 包络 + 程序生成的白噪声),不加载任何音频文件。
// 浏览器规定没被用户点过不许出声:第一次 pointerdown / keydown 时 unlock() 建 AudioContext。
// 静音开关存在这台设备上(localStorage),关掉时连 AudioContext 和 BGM 都不建。
//
// 音色分层:按钮 / 出牌(随从和法术不同音色)/ 攻击 / 受伤 / 治疗 / 圣盾碎 / 死亡 / 亡语 / 战吼 /
// 嘲讽落地 / 冲锋 / 抽牌 / 烧牌 / 疲劳 / 胜利 / 失败;三套卡组各一段很轻的循环 BGM。
import { card } from './data'
import type { ClassId } from './types'
import type { Ev } from './types'

const KEY = 'cards:sound'

export type SoundName =
  | 'tap' | 'play' | 'spell' | 'summon' | 'taunt' | 'charge' | 'battlecry' | 'rattle'
  | 'attack' | 'hit' | 'heal' | 'shield' | 'death' | 'draw' | 'burn' | 'fatigue'
  | 'turn' | 'victory' | 'defeat' | 'error' | 'buff'

let ctx: AudioContext | null = null
let master: GainNode | null = null
let muted = readMuted()
let noiseBuf: AudioBuffer | null = null
let voices = 0
const lastAt = new Map<SoundName, number>()

// ---------------------------------------------------------------- BGM(每套卡组一段很轻的循环)

interface BgmDef {
  root: number
  /** 五声音阶(半音偏移) */
  scale: number[]
  /** 一小节的音符索引序列 */
  pattern: number[]
  /** 一小节多少秒 */
  bar: number
  wave: OscillatorType
}

const BGM: Record<ClassId, BgmDef> = {
  forge: { root: 196, scale: [0, 3, 5, 7, 10], pattern: [0, 2, 4, 3, 2, 0, 3, 4], bar: 1.8, wave: 'triangle' },
  frost: { root: 174.6, scale: [0, 2, 3, 7, 8], pattern: [0, 2, 3, 4, 3, 2, 1, 0], bar: 2.2, wave: 'sine' },
  dusk: { root: 146.8, scale: [0, 3, 5, 6, 10], pattern: [0, 1, 3, 2, 4, 3, 1, 0], bar: 2.0, wave: 'sine' },
  neutral: { root: 164.8, scale: [0, 2, 4, 7, 9], pattern: [0, 1, 2, 3, 4, 3, 2, 1], bar: 2.4, wave: 'sine' },
}
let bgmCls: ClassId | null = null
let bgmGain: GainNode | null = null
let bgmTimer: number | null = null

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
  if (!on) bgmSilence()
  else {
    unlock()
    bgmResume()
  }
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

function ac(): AudioContext | null {
  if (muted) return null
  if (!ctx) unlock()
  if (!ctx || !master) return null
  if (ctx.state === 'suspended') void ctx.resume().catch(() => undefined)
  return ctx
}

// ---------------------------------------------------------------- 合成器

interface ToneOpts {
  type?: OscillatorType
  vol?: number
  to?: number
  delay?: number
  attack?: number
  /** 连到 BGM 总线的音量(不传就连主总线) */
  bus?: GainNode
}

function tone(freq: number, dur: number, o: ToneOpts = {}): void {
  const c = ac()
  if (!c || !master || voices > 20) return
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
  g.connect(o.bus ?? master)
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

function noise(dur: number, o: NoiseOpts = {}): void {
  const c = ac()
  if (!c || !master || voices > 20) return
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

/** 同一类音效短时间内只响一次(群体伤害一下打好几只也不炸耳朵) */
function throttle(name: SoundName): boolean {
  const now = performance.now()
  if (now - (lastAt.get(name) ?? -1e9) < 55) return false
  lastAt.set(name, now)
  return true
}

// ---------------------------------------------------------------- 短音效

export function play(name: SoundName): void {
  if (muted) return
  if (!ctx) unlock()
  if (!ctx || !master) return
  if (voices > 20 || !throttle(name)) return
  switch (name) {
    case 'tap':
      tone(760, 0.06, { type: 'sine', vol: 0.1, to: 640 })
      break
    case 'play':
      tone(320, 0.12, { vol: 0.16, to: 520 })
      noise(0.1, { vol: 0.06, freq: 1400 })
      break
    case 'spell':
      tone(620, 0.18, { type: 'sine', vol: 0.11, to: 930 })
      tone(1240, 0.14, { type: 'sine', vol: 0.05, delay: 0.05 })
      break
    case 'summon':
      tone(420, 0.13, { vol: 0.12, to: 640 })
      tone(840, 0.1, { type: 'sine', vol: 0.06, delay: 0.05 })
      break
    case 'taunt':
      tone(120, 0.16, { type: 'square', vol: 0.11, to: 90 })
      noise(0.14, { vol: 0.12, freq: 260, type: 'lowpass' })
      break
    case 'charge':
      noise(0.18, { vol: 0.1, freq: 1800, q: 0.6 })
      tone(260, 0.16, { type: 'sawtooth', vol: 0.08, to: 620 })
      break
    case 'battlecry':
      tone(520, 0.12, { type: 'triangle', vol: 0.1 })
      tone(780, 0.16, { type: 'triangle', vol: 0.1, delay: 0.08 })
      break
    case 'rattle':
      tone(160, 0.3, { type: 'sawtooth', vol: 0.08, to: 70 })
      noise(0.26, { vol: 0.07, freq: 900, q: 0.5 })
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
      noise(0.16, { vol: 0.08, freq: 2600, q: 1.2 })
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
      for (const [i, f] of [523, 659, 784, 1046].entries()) tone(f, 0.26, { delay: i * 0.11, vol: 0.14 })
      break
    case 'defeat':
      for (const [i, f] of [392, 330, 262, 196].entries()) tone(f, 0.3, { delay: i * 0.13, vol: 0.12, type: 'sawtooth' })
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

// ---------------------------------------------------------------- BGM

function bgmBar(def: BgmDef, gain: GainNode): void {
  const c = ac()
  if (!c) return
  const beat = def.bar / def.pattern.length
  for (let i = 0; i < def.pattern.length; i++) {
    const step = def.scale[def.pattern[i] % def.scale.length]
    const octave = i % 4 === 0 ? 2 : i % 2 === 0 ? 1.5 : 1
    const freq = def.root * Math.pow(2, step / 12) * (i === 4 ? 1.5 : 1) * octave
    tone(freq, beat * 1.6, { type: def.wave, vol: 0.16, delay: i * beat, attack: 0.03, bus: gain })
  }
  // 低音打底:每小节一下
  tone(def.root * 0.5, def.bar * 0.9, { type: 'sine', vol: 0.22, attack: 0.08, bus: gain })
}

function scheduleBgm(): void {
  if (!bgmCls || muted || !ctx || !bgmGain) return
  const def = BGM[bgmCls]
  bgmBar(def, bgmGain)
  bgmTimer = window.setTimeout(scheduleBgm, def.bar * 1000)
}

function bgmSilence(): void {
  if (bgmTimer !== null) window.clearTimeout(bgmTimer)
  bgmTimer = null
}

/** 开一段按阵营的 BGM(同一时间只有一段) */
export function bgmStart(cls: ClassId): void {
  if (bgmCls === cls && bgmTimer !== null) return
  bgmStop()
  if (muted) return
  const c = ac()
  if (!c || !master) return
  bgmCls = cls
  bgmGain = c.createGain()
  bgmGain.gain.value = 0.11
  bgmGain.connect(master)
  scheduleBgm()
}

export function bgmStop(): void {
  bgmSilence()
  bgmCls = null
  if (bgmGain) {
    try { bgmGain.disconnect() } catch (_) { /* 已经断开 */ }
    bgmGain = null
  }
}

/** 暂停:BGM 先停;恢复时接着放同一套 */
export function bgmPause(): void {
  bgmSilence()
}

export function bgmResume(): void {
  if (!bgmCls || muted || bgmTimer !== null) return
  scheduleBgm()
}

/** 切到后台时停掉(短音效和 BGM 都停),回来再恢复 */
export function suspend(): void {
  bgmPause()
  if (ctx && ctx.state === 'running') void ctx.suspend().catch(() => undefined)
}

export function resume(): void {
  if (ctx && ctx.state === 'suspended' && !muted) void ctx.resume().catch(() => undefined)
  bgmResume()
}

/** 引擎事件 → 音效(界面只调这一个;按卡牌关键字分流不同音色) */
export function sfxEvent(e: Ev): void {
  switch (e.e) {
    case 'play': {
      const def = card(e.card)
      play(def.type === 'spell' ? 'spell' : 'play')
      if (def.battlecry) play('battlecry')
      if (def.taunt) play('taunt')
      if (def.charge) play('charge')
      break
    }
    case 'summon': {
      const def = card(e.card)
      play(def.taunt ? 'taunt' : 'summon')
      break
    }
    case 'attack': play('attack'); break
    case 'damage': if (e.amount > 0) play('hit'); break
    case 'shield': play('shield'); break
    case 'death':
      play(card(e.card).deathrattle ? 'rattle' : 'death')
      break
    case 'heal': play('heal'); break
    case 'buff': play('buff'); break
    case 'draw': play('draw'); break
    case 'fatigue': play('fatigue'); break
    case 'burn': play('burn'); break
    case 'turn': play('turn'); break
    case 'over': play(e.winner === 0 ? 'victory' : e.winner === -1 ? 'turn' : 'defeat'); break
  }
}
