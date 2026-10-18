// 音效:全部用 WebAudio 现场合成,没有音频文件。
//
// 分三层母线:音效(SFX)/ 脚步(STEP)/ 环境声(AMBIENT),统一过 master → 水下低通 → 输出。
// - 挖 / 破 / 放按材质换音色(草、沙、石、木、树叶、玻璃、砖);
// - 脚步按脚下材质换音色,水里是水声;
// - 环境声:白天鸟鸣、夜里虫鸣、一直有很轻的风(合成噪声 + 滤波),音量压得很低;
// - 水下:整条母线过低通,听起来发闷;
// - 同时发声的声部有上限(连点挖矿不会叠成一团爆音);静音开关只存本机 localStorage;
// - 浏览器要求用户先交互才能出声:第一次点按/按键时调 unlockAudio()。
import { AUDIO, type Material, type SoundName, type SoundOptions } from './data'

const MUTE_KEY = 'sandbox:muted'

let audio: AudioContext | null = null
let master: GainNode | null = null
let sfxBus: GainNode | null = null
let stepBus: GainNode | null = null
let ambientBus: GainNode | null = null
let muffle: BiquadFilterNode | null = null
let noise: AudioBuffer | null = null
let wind: AudioBufferSourceNode | null = null
let windGain: GainNode | null = null
let muted = false
let voices = 0
let ambientTimer: number | null = null
let ambienceDay = 0.6
let ambienceActive = false
let underwater = false

try {
  muted = window.localStorage.getItem(MUTE_KEY) === '1'
} catch (_) {
  muted = false
}

export function isMuted(): boolean {
  return muted
}

export function setMuted(next: boolean): void {
  muted = next
  try {
    window.localStorage.setItem(MUTE_KEY, next ? '1' : '0')
  } catch (_) {
    /* 本机存储用不了:这次会话里记住就行 */
  }
  if (master && audio) master.gain.setTargetAtTime(next ? 0 : AUDIO.MASTER, audio.currentTime, 0.03)
}

/** 建 AudioContext 并启动风声(用户第一次交互时调) */
export function unlockAudio(): void {
  try {
    if (!audio) {
      const Ctor = window.AudioContext
        || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!Ctor) return
      audio = new Ctor()
      master = audio.createGain()
      master.gain.value = muted ? 0 : AUDIO.MASTER
      muffle = audio.createBiquadFilter()
      muffle.type = 'lowpass'
      muffle.frequency.value = AUDIO.NORMAL_CUTOFF
      master.connect(muffle)
      muffle.connect(audio.destination)
      sfxBus = audio.createGain()
      sfxBus.gain.value = AUDIO.SFX
      sfxBus.connect(master)
      stepBus = audio.createGain()
      stepBus.gain.value = AUDIO.STEP
      stepBus.connect(master)
      ambientBus = audio.createGain()
      ambientBus.gain.value = AUDIO.AMBIENT
      ambientBus.connect(master)
      // 1 秒白噪声,所有「沙沙」「砰」的音效都从这块里剪
      const len = Math.floor(audio.sampleRate * 1)
      noise = audio.createBuffer(1, len, audio.sampleRate)
      const data = noise.getChannelData(0)
      for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1
      startWind()
    }
    if (audio.state === 'suspended') void audio.resume()
    if (ambienceActive) scheduleAmbient()
  } catch (_) {
    audio = null
    master = null
  }
}

export function suspendAudio(): void {
  stopAmbient()
  try {
    if (audio && audio.state === 'running') void audio.suspend()
  } catch (_) {
    /* 忽略 */
  }
}

export function resumeAudio(): void {
  try {
    if (audio && audio.state === 'suspended') void audio.resume()
    if (ambienceActive) scheduleAmbient()
  } catch (_) {
    /* 忽略 */
  }
}

/** 水下:整条母线切到低通,环境声更小 */
export function setUnderwater(on: boolean): void {
  if (underwater === on) return
  underwater = on
  if (!audio || !muffle || !ambientBus) return
  muffle.frequency.setTargetAtTime(on ? AUDIO.UNDERWATER_CUTOFF : AUDIO.NORMAL_CUTOFF, audio.currentTime, 0.08)
  ambientBus.gain.setTargetAtTime(on ? AUDIO.AMBIENT * 0.35 : AUDIO.AMBIENT, audio.currentTime, 0.1)
}

// ---------------------------------------------------------------- 发声工具

function acquireVoice(): boolean {
  if (voices >= AUDIO.MAX_VOICES) return false
  voices++
  return true
}

function releaseVoice(): void {
  if (voices > 0) voices--
}

function busFor(name: SoundName): GainNode | null {
  return name === 'step' ? stepBus : sfxBus
}

function tone(bus: GainNode | null, freq: number, dur: number, type: OscillatorType, vol: number, slideTo?: number): void {
  if (!audio || !bus || !acquireVoice()) return
  const t = audio.currentTime
  const osc = audio.createOscillator()
  const gain = audio.createGain()
  osc.type = type
  osc.frequency.setValueAtTime(freq, t)
  if (slideTo !== undefined) osc.frequency.exponentialRampToValueAtTime(Math.max(20, slideTo), t + dur)
  gain.gain.setValueAtTime(0.0001, t)
  gain.gain.exponentialRampToValueAtTime(Math.max(0.0002, vol), t + 0.008)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  osc.connect(gain)
  gain.connect(bus)
  osc.onended = releaseVoice
  osc.start(t)
  osc.stop(t + dur + 0.02)
}

function burst(bus: GainNode | null, dur: number, freq: number, q: number, vol: number, playbackRate = 1): void {
  if (!audio || !bus || !noise || !acquireVoice()) return
  const t = audio.currentTime
  const src = audio.createBufferSource()
  src.buffer = noise
  src.playbackRate.value = playbackRate
  const filter = audio.createBiquadFilter()
  filter.type = 'bandpass'
  filter.frequency.value = freq
  filter.Q.value = q
  const gain = audio.createGain()
  gain.gain.setValueAtTime(vol, t)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  src.connect(filter)
  filter.connect(gain)
  gain.connect(bus)
  src.onended = releaseVoice
  src.start(t, Math.random() * 0.4)
  src.stop(t + dur + 0.02)
}

// ---------------------------------------------------------------- 材质音色

interface MaterialVoice {
  freq: number
  q: number
  dur: number
  vol: number
  /** 可选的低频撞击(木、石、砖更有分量) */
  thump?: number
}

function materialVoice(material: Material | undefined, kind: 'mine' | 'break' | 'place' | 'step'): MaterialVoice {
  const m = material ?? 'stone'
  if (kind === 'mine') {
    switch (m) {
      case 'grass': return { freq: 800, q: 0.9, dur: 0.045, vol: 0.1 }
      case 'dirt': return { freq: 650, q: 0.9, dur: 0.05, vol: 0.11 }
      case 'sand': return { freq: 1000, q: 0.8, dur: 0.04, vol: 0.09 }
      case 'wood': return { freq: 420, q: 1.3, dur: 0.06, vol: 0.12, thump: 180 }
      case 'leaves': return { freq: 1500, q: 0.7, dur: 0.035, vol: 0.08 }
      case 'glass': return { freq: 2400, q: 1.6, dur: 0.04, vol: 0.09 }
      case 'brick': return { freq: 900, q: 1.2, dur: 0.055, vol: 0.11, thump: 140 }
      default: return { freq: 620, q: 1.1, dur: 0.05, vol: 0.12, thump: 160 }
    }
  }
  if (kind === 'break') {
    switch (m) {
      case 'grass': return { freq: 600, q: 0.7, dur: 0.13, vol: 0.2 }
      case 'dirt': return { freq: 520, q: 0.7, dur: 0.14, vol: 0.22, thump: 110 }
      case 'sand': return { freq: 900, q: 0.6, dur: 0.16, vol: 0.18 }
      case 'wood': return { freq: 380, q: 1.2, dur: 0.16, vol: 0.24, thump: 130 }
      case 'leaves': return { freq: 1300, q: 0.6, dur: 0.12, vol: 0.16 }
      case 'glass': return { freq: 2600, q: 1.4, dur: 0.2, vol: 0.22 }
      case 'brick': return { freq: 800, q: 1.1, dur: 0.18, vol: 0.22, thump: 120 }
      default: return { freq: 560, q: 0.9, dur: 0.16, vol: 0.22, thump: 120 }
    }
  }
  if (kind === 'place') {
    switch (m) {
      case 'grass': return { freq: 700, q: 0.9, dur: 0.06, vol: 0.13, thump: 150 }
      case 'sand': return { freq: 850, q: 0.8, dur: 0.06, vol: 0.11 }
      case 'wood': return { freq: 360, q: 1.3, dur: 0.07, vol: 0.14, thump: 160 }
      case 'glass': return { freq: 2000, q: 1.6, dur: 0.05, vol: 0.1 }
      case 'brick': return { freq: 750, q: 1.2, dur: 0.07, vol: 0.14, thump: 130 }
      default: return { freq: 600, q: 1.1, dur: 0.07, vol: 0.13, thump: 150 }
    }
  }
  // 脚步:比挖放轻
  switch (m) {
    case 'grass': return { freq: 480, q: 0.6, dur: 0.07, vol: 0.28 }
    case 'sand': return { freq: 760, q: 0.5, dur: 0.09, vol: 0.26 }
    case 'stone': return { freq: 300, q: 1.0, dur: 0.06, vol: 0.3, thump: 90 }
    case 'wood': return { freq: 330, q: 1.2, dur: 0.07, vol: 0.28, thump: 120 }
    case 'leaves': return { freq: 1100, q: 0.5, dur: 0.05, vol: 0.2 }
    case 'glass': return { freq: 1600, q: 1.4, dur: 0.05, vol: 0.2 }
    case 'brick': return { freq: 380, q: 1.0, dur: 0.06, vol: 0.28, thump: 100 }
    case 'water': return { freq: 1200, q: 0.5, dur: 0.12, vol: 0.25 }
    default: return { freq: 400, q: 0.8, dur: 0.07, vol: 0.28 }
  }
}

function playMaterial(name: SoundName, opts?: SoundOptions): void {
  const bus = busFor(name)
  const kind = name === 'step' ? 'step' : name === 'break' ? 'break' : name === 'place' ? 'place' : 'mine'
  const v = materialVoice(opts?.material, kind)
  const vol = v.vol * (opts?.vol ?? 1)
  const rate = name === 'step' ? 0.9 + Math.random() * 0.25 : 1
  burst(bus, v.dur, v.freq, v.q, vol, rate)
  if (v.thump && name !== 'step') tone(bus, v.thump, v.dur * 1.4, 'sine', vol * 0.5, v.thump * 0.6)
}

/** 播一个音效;静音/未解锁时什么都不做 */
export function sound(name: SoundName, opts?: SoundOptions): void {
  if (muted || !audio) return
  switch (name) {
    case 'mine':
    case 'break':
    case 'place':
    case 'step':
      playMaterial(name, opts)
      return
    case 'jump':
      tone(sfxBus, 300, 0.14, 'sine', 0.11 * (opts?.vol ?? 1), 470)
      return
    case 'land':
      burst(sfxBus, 0.09, 240, 0.8, 0.15 * (opts?.vol ?? 1), 0.6)
      tone(sfxBus, 95, 0.09, 'sine', 0.1 * (opts?.vol ?? 1), 60)
      return
    case 'click':
      tone(sfxBus, 660, 0.05, 'sine', 0.07 * (opts?.vol ?? 1), 880)
      return
    case 'deny':
      tone(sfxBus, 190, 0.12, 'square', 0.06 * (opts?.vol ?? 1), 150)
      return
    case 'splash':
      burst(sfxBus, 0.22, 1100, 0.6, 0.14 * (opts?.vol ?? 1), 0.55)
      return
    case 'respawn':
      tone(sfxBus, 330, 0.18, 'sine', 0.1 * (opts?.vol ?? 1), 520)
      return
    case 'full':
      tone(sfxBus, 140, 0.2, 'sawtooth', 0.06 * (opts?.vol ?? 1), 120)
      return
    case 'achieve':
      tone(sfxBus, 660, 0.12, 'triangle', 0.12)
      tone(sfxBus, 880, 0.18, 'triangle', 0.1)
      burst(sfxBus, 0.16, 3200, 1.2, 0.05, 1.2)
      return
    case 'cleanup':
      tone(sfxBus, 420, 0.12, 'sine', 0.09, 620)
      return
    default:
      return
  }
}

// ---------------------------------------------------------------- 环境声

function startWind(): void {
  if (!audio || !ambientBus || !noise || wind) return
  wind = audio.createBufferSource()
  wind.buffer = noise
  wind.loop = true
  const filter = audio.createBiquadFilter()
  filter.type = 'bandpass'
  filter.frequency.value = 420
  filter.Q.value = 0.4
  windGain = audio.createGain()
  windGain.gain.value = AUDIO.WIND_VOL * 0.05
  wind.connect(filter)
  filter.connect(windGain)
  windGain.connect(ambientBus)
  wind.start()
}

function birdChirp(): void {
  if (!audio || !ambientBus) return
  const ctx = audio
  const bus = ambientBus
  const chirps = 2 + Math.floor(Math.random() * 3)
  for (let i = 0; i < chirps; i++) {
    const delay = i * (0.07 + Math.random() * 0.05)
    const freq = 1700 + Math.random() * 900
    window.setTimeout(() => {
      if (muted || !ambienceActive) return
      if (!acquireVoice()) return
      const t = ctx.currentTime
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.setValueAtTime(freq, t)
      osc.frequency.exponentialRampToValueAtTime(freq * 1.35, t + 0.05)
      gain.gain.setValueAtTime(0.0001, t)
      gain.gain.exponentialRampToValueAtTime(0.06 * AUDIO.BIRD_VOL, t + 0.01)
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.09)
      osc.connect(gain)
      gain.connect(bus)
      osc.onended = releaseVoice
      osc.start(t)
      osc.stop(t + 0.1)
    }, delay * 1000)
  }
}

function cricketPulse(): void {
  if (!audio || !ambientBus) return
  const ctx = audio
  const bus = ambientBus
  const pulses = 3 + Math.floor(Math.random() * 4)
  for (let i = 0; i < pulses; i++) {
    const delay = i * (0.055 + Math.random() * 0.02)
    window.setTimeout(() => {
      if (muted || !ambienceActive) return
      if (!acquireVoice()) return
      const t = ctx.currentTime
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'triangle'
      osc.frequency.value = 4100 + Math.random() * 400
      gain.gain.setValueAtTime(0.0001, t)
      gain.gain.exponentialRampToValueAtTime(0.03 * AUDIO.CRICKET_VOL, t + 0.005)
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.03)
      osc.connect(gain)
      gain.connect(bus)
      osc.onended = releaseVoice
      osc.start(t)
      osc.stop(t + 0.04)
    }, delay * 1000)
  }
}

function scheduleAmbient(): void {
  if (ambientTimer !== null || !audio || !ambienceActive) return
  const day = ambienceDay
  let gap: number
  if (day > 0.5) {
    gap = AUDIO.BIRD_GAP_MIN + Math.random() * (AUDIO.BIRD_GAP_MAX - AUDIO.BIRD_GAP_MIN)
  } else if (day < 0.25) {
    gap = AUDIO.CRICKET_GAP_MIN + Math.random() * (AUDIO.CRICKET_GAP_MAX - AUDIO.CRICKET_GAP_MIN)
  } else {
    gap = 4000
  }
  ambientTimer = window.setTimeout(() => {
    ambientTimer = null
    if (!ambienceActive) return
    if (day > 0.5) birdChirp()
    else if (day < 0.25) cricketPulse()
    if (windGain && audio) {
      // 风随昼夜略变:夜里轻一点
      const target = AUDIO.WIND_VOL * (0.035 + (1 - day) * 0.02)
      windGain.gain.setTargetAtTime(target, audio.currentTime, 1.2)
    }
    scheduleAmbient()
  }, gap)
}

/** 主循环每 ~2 秒调一次:告诉环境声现在是白天还是夜里、要不要出声 */
export function setAmbience(day: number, active: boolean): void {
  ambienceDay = Math.max(0, Math.min(1, day))
  const was = ambienceActive
  ambienceActive = active && !muted && !!audio
  if (!ambienceActive) {
    stopAmbient()
    return
  }
  if (!was) scheduleAmbient()
}

export function stopAmbient(): void {
  if (ambientTimer !== null) {
    window.clearTimeout(ambientTimer)
    ambientTimer = null
  }
}
