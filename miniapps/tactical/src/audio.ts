// 音效:全部用 WebAudio 现场合成,不下载任何音频文件(包体小,也不发网络请求)。
//
// 浏览器不许没点过就出声:第一次点击或按键之后才建 AudioContext。
// 静音开关存本机 localStorage 一份(打开时不用等云存档),同时也会写进战绩存档里。

export type SfxName =
  | 'shot' | 'guardShot' | 'hit' | 'hurt' | 'reload' | 'empty'
  | 'plant' | 'planted' | 'beep' | 'defuse' | 'defused' | 'explode'
  | 'win' | 'lose' | 'click' | 'tick'

const KEY = 'tactical:sound'

let ctx: AudioContext | null = null
let master: GainNode | null = null
let noiseBuffer: AudioBuffer | null = null
let muted = readMuted()
const lastAt = new Map<SfxName, number>()

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

/** 打开/关闭声音;同时写本机缓存(不碰云存档,调用方负责写战绩) */
export function setSound(on: boolean): void {
  muted = !on
  try {
    window.localStorage.setItem(KEY, on ? '1' : '0')
  } catch (_) { /* 存不了就只管这一次 */ }
  if (master) master.gain.value = on ? 0.9 : 0
  if (on) unlock()
}

/** 在用户点过之后调:建上下文。重复调没关系 */
export function unlock(): void {
  if (muted) return
  if (!ctx) {
    const Ctor = window.AudioContext
      || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return
    try {
      ctx = new Ctor()
      master = ctx.createGain()
      master.gain.value = 0.9
      master.connect(ctx.destination)
      // 0.4 秒白噪声,枪声/爆炸都从它切片
      const len = Math.floor(ctx.sampleRate * 0.4)
      noiseBuffer = ctx.createBuffer(1, len, ctx.sampleRate)
      const data = noiseBuffer.getChannelData(0)
      for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1
    } catch (_) {
      ctx = null
      master = null
      return
    }
  }
  if (ctx.state === 'suspended') void ctx.resume().catch(() => undefined)
}

export function suspend(): void {
  if (ctx && ctx.state === 'running') void ctx.suspend().catch(() => undefined)
}

export function resume(): void {
  if (ctx && ctx.state === 'suspended' && !muted) void ctx.resume().catch(() => undefined)
}

/** 放一个音效。同一个音效 gap 毫秒内只响一次,连射时不会炸耳朵 */
export function play(name: SfxName, opts: { vol?: number; rate?: number; gap?: number } = {}): void {
  if (muted) return
  if (!ctx || !master) return
  const now = ctx.currentTime
  const gap = opts.gap ?? 40
  const stamp = performance.now()
  if (stamp - (lastAt.get(name) ?? -1e9) < gap) return
  lastAt.set(name, stamp)
  try {
    switch (name) {
      case 'shot': shot(now, opts.vol ?? 0.5, opts.rate ?? 1, false); break
      case 'guardShot': shot(now, opts.vol ?? 0.24, opts.rate ?? 0.82, true); break
      case 'hit': tone(now, 1250, 700, 0.05, 'square', 0.16); break
      case 'hurt': thud(now); break
      case 'reload': reload(now); break
      case 'empty': tone(now, 320, 240, 0.04, 'square', 0.14); break
      case 'plant': plantTone(now); break
      case 'planted': planted(now); break
      case 'beep': beep(now, opts.rate ?? 1); break
      case 'defuse': tone(now, 520, 760, 0.06, 'triangle', 0.12); break
      case 'defused': sad(now); break
      case 'explode': explode(now); break
      case 'win': win(now); break
      case 'lose': lose(now); break
      case 'click': tone(now, 900, 700, 0.03, 'triangle', 0.1); break
      case 'tick': tone(now, 1600, 1500, 0.02, 'square', 0.05); break
    }
  } catch (_) { /* 声音出不来不影响玩 */ }
}

// ---------------------------------------------------------------- 合成积木

function tone(t: number, from: number, to: number, dur: number, type: OscillatorType, vol: number): void {
  if (!ctx || !master) return
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = type
  osc.frequency.setValueAtTime(from, t)
  osc.frequency.exponentialRampToValueAtTime(Math.max(20, to), t + dur)
  gain.gain.setValueAtTime(0.0001, t)
  gain.gain.exponentialRampToValueAtTime(vol, t + 0.004)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  osc.connect(gain)
  gain.connect(master)
  osc.start(t)
  osc.stop(t + dur + 0.02)
}

function noiseBurst(
  t: number, dur: number, vol: number, kind: BiquadFilterType, freq: number, q = 1,
): void {
  if (!ctx || !master || !noiseBuffer) return
  const src = ctx.createBufferSource()
  src.buffer = noiseBuffer
  const filter = ctx.createBiquadFilter()
  filter.type = kind
  filter.frequency.setValueAtTime(freq, t)
  filter.Q.value = q
  const gain = ctx.createGain()
  gain.gain.setValueAtTime(vol, t)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  src.connect(filter)
  filter.connect(gain)
  gain.connect(master)
  src.start(t)
  src.stop(t + dur + 0.02)
}

function shot(t: number, vol: number, rate: number, muted: boolean): void {
  noiseBurst(t, 0.07, vol, 'bandpass', 1600 * rate, 0.9)
  tone(t, 190 * rate, 70 * rate, 0.06, 'square', vol * (muted ? 0.35 : 0.5))
  // 远处/敌人的枪声更闷一点
  if (muted) noiseBurst(t, 0.09, vol * 0.5, 'lowpass', 900, 0.7)
}

function thud(t: number): void {
  if (!ctx || !master) return
  tone(t, 120, 60, 0.16, 'sine', 0.4)
  noiseBurst(t, 0.12, 0.25, 'lowpass', 600, 0.8)
}

function reload(t: number): void {
  if (!ctx || !master) return
  // 卸弹匣、上弹匣两个机械声,第二个排在换弹快结束时
  noiseBurst(t, 0.035, 0.22, 'bandpass', 2600, 1.2)
  noiseBurst(t + 0.22, 0.03, 0.18, 'bandpass', 3400, 1.4)
  noiseBurst(t + 0.24, 0.03, 0.12, 'bandpass', 1800, 1.2)
}

function plantTone(t: number): void {
  tone(t, 520, 700, 0.09, 'triangle', 0.2)
  noiseBurst(t, 0.05, 0.12, 'bandpass', 1200, 1)
}

function planted(t: number): void {
  tone(t, 660, 660, 0.09, 'square', 0.18)
  tone(t + 0.1, 990, 990, 0.12, 'square', 0.18)
  if (ctx && master) {
    const osc = ctx.createOscillator()
    const g = ctx.createGain()
    osc.type = 'sine'
    osc.frequency.setValueAtTime(330, t)
    osc.frequency.linearRampToValueAtTime(220, t + 0.5)
    g.gain.setValueAtTime(0.0001, t)
    g.gain.exponentialRampToValueAtTime(0.16, t + 0.05)
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.6)
    osc.connect(g)
    g.connect(master)
    osc.start(t)
    osc.stop(t + 0.65)
  }
}

function beep(t: number, rate: number): void {
  // rate 越大越急(炸弹最后几秒),音高也跟着上去
  const freq = 1500 * Math.min(2, Math.max(0.8, rate))
  tone(t, freq, freq * 0.95, 0.06, 'square', 0.14)
}

function sad(t: number): void {
  tone(t, 420, 380, 0.14, 'triangle', 0.2)
  tone(t + 0.16, 300, 240, 0.28, 'triangle', 0.2)
}

function explode(t: number): void {
  noiseBurst(t, 0.7, 0.9, 'lowpass', 900, 0.7)
  noiseBurst(t, 0.25, 0.5, 'bandpass', 2200, 0.6)
  tone(t, 90, 30, 0.9, 'sine', 0.7)
  tone(t + 0.05, 60, 24, 1.1, 'triangle', 0.4)
}

function win(t: number): void {
  const notes = [523, 659, 784, 1046]
  notes.forEach((f, i) => tone(t + i * 0.11, f, f, 0.16, 'triangle', 0.2))
}

function lose(t: number): void {
  const notes = [392, 330, 262]
  notes.forEach((f, i) => tone(t + i * 0.14, f, f * 0.98, 0.22, 'triangle', 0.2))
}
