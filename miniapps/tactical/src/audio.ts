// 音效 + BGM:全部用 WebAudio 现场合成,不下载任何音频文件。
//
// - 空间化:带位置的音效(枪声、脚步、炸弹、爆炸)走 PannerNode,按和玩家的相对位置左右偏、按距离衰减;
// - 混音:sfx / music 两条总线汇到 compressor,再进 master —— 多声齐发也不削波;
// - 并发:同一音效有最小间隔,同时在响的音效有上限;切后台/暂停时 BGM 停;
// - 静音开关存本机 localStorage(打开时不用等云存档),同时也会写进战绩存档。

export type SfxName =
  | 'shot' | 'guardShot' | 'hit' | 'hurt' | 'reload' | 'empty' | 'swap'
  | 'step' | 'plant' | 'planted' | 'beep' | 'defuse' | 'defused' | 'explode'
  | 'win' | 'lose' | 'click' | 'tick' | 'achieve'

const KEY = 'tactical:sound'

export interface SpatialPoint { x: number; y: number }

export interface PlayOptions {
  vol?: number
  rate?: number
  gap?: number
  /** 声源世界坐标;给了 x/y 就做空间化 */
  x?: number
  y?: number
  /** 听者(玩家)世界坐标;不传就按地图中心算 */
  listener?: SpatialPoint
}

let ctx: AudioContext | null = null
let master: GainNode | null = null
let sfxBus: GainNode | null = null
let musicBus: GainNode | null = null
let noiseBuffer: AudioBuffer | null = null
let muted = readMuted()
const lastAt = new Map<SfxName, number>()
let voices = 0

/** BGM 的状态:节点、调度定时器、当前是否在响 */
let musicTimer: number | null = null
let musicNodes: AudioNode[] = []
let musicPlaying = false
let musicPaused = false

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

/** 打开/关闭声音;同时写本机缓存 */
export function setSound(on: boolean): void {
  muted = !on
  try {
    window.localStorage.setItem(KEY, on ? '1' : '0')
  } catch (_) { /* 存不了就只管这一次 */ }
  if (master) master.gain.value = on ? 1 : 0
  if (!on) stopMusic()
  else if (musicPlaying) startMusic()
}

/** 在用户点过之后调:建上下文、总线、白噪声。重复调没关系 */
export function unlock(): void {
  if (!ctx) {
    const Ctor = window.AudioContext
      || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return
    try {
      ctx = new Ctor()
      master = ctx.createGain()
      master.gain.value = muted ? 0 : 1
      const compressor = ctx.createDynamicsCompressor()
      compressor.threshold.value = -18
      compressor.knee.value = 18
      compressor.ratio.value = 6
      compressor.attack.value = 0.004
      compressor.release.value = 0.25
      master.connect(compressor)
      compressor.connect(ctx.destination)
      sfxBus = ctx.createGain()
      sfxBus.gain.value = 0.9
      sfxBus.connect(master)
      musicBus = ctx.createGain()
      musicBus.gain.value = 0.22
      musicBus.connect(master)
      const len = Math.floor(ctx.sampleRate * 0.4)
      noiseBuffer = ctx.createBuffer(1, len, ctx.sampleRate)
      const data = noiseBuffer.getChannelData(0)
      for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1
    } catch (_) {
      ctx = null
      master = null
      sfxBus = null
      musicBus = null
      return
    }
  }
  if (ctx.state === 'suspended') void ctx.resume().catch(() => undefined)
}

export function suspend(): void {
  pauseMusic(true)
  if (ctx && ctx.state === 'running') void ctx.suspend().catch(() => undefined)
}

export function resume(): void {
  if (ctx && ctx.state === 'suspended' && !muted) void ctx.resume().catch(() => undefined)
  pauseMusic(false)
}

/** 放一个音效。同一个音效 gap 毫秒内只响一次;同时发声数封顶 */
export function play(name: SfxName, opts: PlayOptions = {}): void {
  if (muted || !ctx || !sfxBus) return
  const stamp = performance.now()
  const gap = opts.gap ?? 40
  if (stamp - (lastAt.get(name) ?? -1e9) < gap) return
  if (voices > 26) return
  lastAt.set(name, stamp)
  const t = ctx.currentTime + 0.001
  const gainOut = opts.x !== undefined && opts.y !== undefined
    ? spatialOut(t, opts.x, opts.y, opts.listener)
    : null
  const dest = gainOut ?? sfxBus
  voices++
  try {
    switch (name) {
      case 'shot': shot(t, dest, opts.vol ?? 0.5, opts.rate ?? 1, false); break
      case 'guardShot': shot(t, dest, opts.vol ?? 0.3, opts.rate ?? 0.82, true); break
      case 'hit': tone(t, dest, 1250, 700, 0.05, 'square', 0.16); break
      case 'hurt': thud(t, dest); break
      case 'reload': reload(t, dest); break
      case 'empty': tone(t, dest, 320, 240, 0.04, 'square', 0.14); break
      case 'swap': swapClick(t, dest); break
      case 'step': step(t, dest); break
      case 'plant': plantTone(t, dest); break
      case 'planted': planted(t, dest); break
      case 'beep': beep(t, dest, opts.rate ?? 1); break
      case 'defuse': tone(t, dest, 520, 760, 0.06, 'triangle', 0.12); break
      case 'defused': sad(t, dest); break
      case 'explode': explode(t, dest); break
      case 'win': win(t, dest); break
      case 'lose': lose(t, dest); break
      case 'click': tone(t, dest, 900, 700, 0.03, 'triangle', 0.1); break
      case 'tick': tone(t, dest, 1600, 1500, 0.02, 'square', 0.05); break
      case 'achieve': achieve(t, dest); break
    }
  } catch (_) { /* 声音出不来不影响玩 */ }
  window.setTimeout(() => { voices = Math.max(0, voices - 1) }, 300)
}

/** 带空间位置的音效:让声音有左右和远近 */
function spatialOut(t: number, x: number, y: number, listener?: SpatialPoint): GainNode {
  const c = ctx!
  const pan = c.createPanner()
  pan.panningModel = 'equalpower'
  pan.distanceModel = 'inverse'
  pan.refDistance = 220
  pan.maxDistance = 1800
  pan.rolloffFactor = 0.9
  const at = listener ?? { x: 528, y: 312 }
  if (pan.positionX) {
    pan.positionX.setValueAtTime(x, t)
    pan.positionY.setValueAtTime(y, t)
    pan.positionZ.setValueAtTime(0, t)
    c.listener.positionX?.setValueAtTime(at.x, t)
    c.listener.positionY?.setValueAtTime(at.y, t)
    c.listener.positionZ?.setValueAtTime(0, t)
  } else {
    pan.setPosition(x, y, 0)
    c.listener.setPosition(at.x, at.y, 0)
  }
  const gain = c.createGain()
  gain.gain.value = 1
  pan.connect(gain)
  gain.connect(sfxBus!)
  return gain
}

// ---------------------------------------------------------------- BGM(紧张感循环)

/** 比赛内循环的轻量 BGM:低音持续音 + 心跳般的低频脉冲 + 偶尔的金属噪声 */
export function startMusic(): void {
  if (muted) return
  unlock()
  if (!ctx || !musicBus || musicPlaying) return
  musicPlaying = true
  musicPaused = false
  const c = ctx
  const droneGain = c.createGain()
  droneGain.gain.value = 0.0001
  droneGain.connect(musicBus)
  const droneA = c.createOscillator()
  droneA.type = 'sine'
  droneA.frequency.value = 55
  const droneB = c.createOscillator()
  droneB.type = 'sawtooth'
  droneB.frequency.value = 82.5
  const filter = c.createBiquadFilter()
  filter.type = 'lowpass'
  filter.frequency.value = 240
  const lfo = c.createOscillator()
  lfo.frequency.value = 0.09
  const lfoGain = c.createGain()
  lfoGain.gain.value = 0.012
  droneA.connect(filter)
  droneB.connect(filter)
  filter.connect(droneGain)
  lfo.connect(lfoGain)
  lfoGain.connect(droneGain.gain)
  droneA.start()
  droneB.start()
  lfo.start()
  droneGain.gain.setTargetAtTime(0.11, c.currentTime, 1.5)
  musicNodes = [droneA, droneB, lfo, filter, droneGain, lfoGain]
  // 心跳:每 1.7 秒两下低频脉冲
  const beat = (): void => {
    if (!ctx || !musicBus || musicPaused || muted) return
    const t = ctx.currentTime
    pulse(t, 0.09)
    pulse(t + 0.34, 0.055)
  }
  beat()
  musicTimer = window.setInterval(beat, 1700)
}

function pulse(t: number, vol: number): void {
  if (!ctx || !musicBus) return
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = 'sine'
  osc.frequency.setValueAtTime(98, t)
  osc.frequency.exponentialRampToValueAtTime(52, t + 0.28)
  gain.gain.setValueAtTime(0.0001, t)
  gain.gain.exponentialRampToValueAtTime(vol, t + 0.015)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.32)
  osc.connect(gain)
  gain.connect(musicBus)
  osc.start(t)
  osc.stop(t + 0.36)
}

export function stopMusic(): void {
  musicPlaying = false
  musicPaused = true
  if (musicTimer !== null) {
    window.clearInterval(musicTimer)
    musicTimer = null
  }
  const c = ctx
  if (!c) return
  for (const node of musicNodes) {
    try {
      if (node instanceof OscillatorNode || node instanceof AudioBufferSourceNode) node.stop(c.currentTime + 0.3)
    } catch (_) { /* 已经停了 */ }
  }
  musicNodes = []
}

export function pauseMusic(paused: boolean): void {
  musicPaused = paused
  if (!ctx || !musicBus) return
  const target = paused ? 0.0001 : 0.22
  musicBus.gain.setTargetAtTime(target, ctx.currentTime, 0.25)
}

// ---------------------------------------------------------------- 合成积木

function tone(
  t: number, dest: AudioNode, from: number, to: number, dur: number, type: OscillatorType, vol: number,
): void {
  if (!ctx) return
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = type
  osc.frequency.setValueAtTime(from, t)
  osc.frequency.exponentialRampToValueAtTime(Math.max(20, to), t + dur)
  gain.gain.setValueAtTime(0.0001, t)
  gain.gain.exponentialRampToValueAtTime(vol, t + 0.004)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  osc.connect(gain)
  gain.connect(dest)
  osc.start(t)
  osc.stop(t + dur + 0.02)
}

function noiseBurst(
  t: number, dest: AudioNode, dur: number, vol: number, kind: BiquadFilterType, freq: number, q = 1,
): void {
  if (!ctx || !noiseBuffer) return
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
  gain.connect(dest)
  src.start(t)
  src.stop(t + dur + 0.02)
}

function shot(t: number, dest: AudioNode, vol: number, rate: number, distant: boolean): void {
  noiseBurst(t, dest, 0.07, vol, 'bandpass', 1600 * rate, 0.9)
  tone(t, dest, 190 * rate, 70 * rate, 0.06, 'square', vol * (distant ? 0.35 : 0.5))
  if (distant) noiseBurst(t, dest, 0.09, vol * 0.5, 'lowpass', 900, 0.7)
}

function thud(t: number, dest: AudioNode): void {
  tone(t, dest, 120, 60, 0.16, 'sine', 0.4)
  noiseBurst(t, dest, 0.12, 0.25, 'lowpass', 600, 0.8)
}

function reload(t: number, dest: AudioNode): void {
  noiseBurst(t, dest, 0.035, 0.22, 'bandpass', 2600, 1.2)
  noiseBurst(t + 0.22, dest, 0.03, 0.18, 'bandpass', 3400, 1.4)
  noiseBurst(t + 0.24, dest, 0.03, 0.12, 'bandpass', 1800, 1.2)
}

function swapClick(t: number, dest: AudioNode): void {
  noiseBurst(t, dest, 0.03, 0.18, 'bandpass', 3000, 1.4)
  noiseBurst(t + 0.09, dest, 0.035, 0.16, 'bandpass', 2100, 1.2)
}

/** 脚步:闷闷的一下,音高和音量随机一点,不机械 */
function step(t: number, dest: AudioNode): void {
  noiseBurst(t, dest, 0.045, 0.11 + Math.random() * 0.04, 'lowpass', 380 + Math.random() * 160, 0.8)
  tone(t, dest, 90 + Math.random() * 30, 55, 0.05, 'sine', 0.06)
}

function plantTone(t: number, dest: AudioNode): void {
  tone(t, dest, 520, 700, 0.09, 'triangle', 0.2)
  noiseBurst(t, dest, 0.05, 0.12, 'bandpass', 1200, 1)
}

function planted(t: number, dest: AudioNode): void {
  tone(t, dest, 660, 660, 0.09, 'square', 0.18)
  tone(t + 0.1, dest, 990, 990, 0.12, 'square', 0.18)
  if (!ctx) return
  const osc = ctx.createOscillator()
  const g = ctx.createGain()
  osc.type = 'sine'
  osc.frequency.setValueAtTime(330, t)
  osc.frequency.linearRampToValueAtTime(220, t + 0.5)
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(0.16, t + 0.05)
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.6)
  osc.connect(g)
  g.connect(dest)
  osc.start(t)
  osc.stop(t + 0.65)
}

function beep(t: number, dest: AudioNode, rate: number): void {
  const freq = 1500 * Math.min(2, Math.max(0.8, rate))
  tone(t, dest, freq, freq * 0.95, 0.06, 'square', 0.14)
}

function sad(t: number, dest: AudioNode): void {
  tone(t, dest, 420, 380, 0.14, 'triangle', 0.2)
  tone(t + 0.16, dest, 300, 240, 0.28, 'triangle', 0.2)
}

function explode(t: number, dest: AudioNode): void {
  noiseBurst(t, dest, 0.7, 0.9, 'lowpass', 900, 0.7)
  noiseBurst(t, dest, 0.25, 0.5, 'bandpass', 2200, 0.6)
  tone(t, dest, 90, 30, 0.9, 'sine', 0.7)
  tone(t + 0.05, dest, 60, 24, 1.1, 'triangle', 0.4)
}

function win(t: number, dest: AudioNode): void {
  const notes = [523, 659, 784, 1046]
  notes.forEach((f, i) => tone(t + i * 0.11, dest, f, f, 0.16, 'triangle', 0.2))
}

function lose(t: number, dest: AudioNode): void {
  const notes = [392, 330, 262]
  notes.forEach((f, i) => tone(t + i * 0.14, dest, f, f * 0.98, 0.22, 'triangle', 0.2))
}

function achieve(t: number, dest: AudioNode): void {
  const notes = [659, 880, 1175]
  notes.forEach((f, i) => tone(t + i * 0.09, dest, f, f, 0.14, 'triangle', 0.18))
}
