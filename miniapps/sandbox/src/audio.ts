// 音效:全部用 WebAudio 现场合成,没有音频文件。挖、放、跳、落地、菜单点击、挖不动。
//
// 浏览器规定音频必须等用户第一次点按之后才能出声,所以界面在第一次交互时调 unlock()。
// 静音开关只存在本机 localStorage(不上云、不进存档)。

export type SfxName = 'mine' | 'break' | 'place' | 'jump' | 'land' | 'click' | 'deny' | 'splash' | 'respawn' | 'full'

const MUTE_KEY = 'sandbox:muted'

let audio: AudioContext | null = null
let master: GainNode | null = null
let noise: AudioBuffer | null = null
let muted = false

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
  if (master && audio) master.gain.setTargetAtTime(next ? 0 : 0.5, audio.currentTime, 0.02)
}

/** 第一次点按/按键时调用:建 AudioContext 并恢复(自动播放策略) */
export function unlock(): void {
  try {
    if (!audio) {
      const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!Ctor) return
      audio = new Ctor()
      master = audio.createGain()
      master.gain.value = muted ? 0 : 0.5
      master.connect(audio.destination)
      // 1 秒白噪声,所有「沙沙」「砰」的音效都从这块里剪
      const len = Math.floor(audio.sampleRate * 0.5)
      noise = audio.createBuffer(1, len, audio.sampleRate)
      const data = noise.getChannelData(0)
      for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1
    }
    if (audio.state === 'suspended') void audio.resume()
  } catch (_) {
    audio = null
    master = null
  }
}

export function suspend(): void {
  try {
    if (audio && audio.state === 'running') void audio.suspend()
  } catch (_) {
    /* 忽略 */
  }
}

function tone(freq: number, dur: number, type: OscillatorType, vol: number, slideTo?: number): void {
  if (!audio || !master) return
  const t = audio.currentTime
  const osc = audio.createOscillator()
  const gain = audio.createGain()
  osc.type = type
  osc.frequency.setValueAtTime(freq, t)
  if (slideTo !== undefined) osc.frequency.exponentialRampToValueAtTime(Math.max(20, slideTo), t + dur)
  gain.gain.setValueAtTime(0.0001, t)
  gain.gain.exponentialRampToValueAtTime(vol, t + 0.008)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  osc.connect(gain)
  gain.connect(master)
  osc.start(t)
  osc.stop(t + dur + 0.02)
}

function burst(dur: number, freq: number, q: number, vol: number, playbackRate = 1): void {
  if (!audio || !master || !noise) return
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
  gain.connect(master)
  src.start(t)
  src.stop(t + dur + 0.02)
}

/** 播一个音效;名字不认识就什么都不做 */
export function sfx(name: SfxName, vol = 1): void {
  if (muted || !audio) return
  switch (name) {
    case 'mine':
      burst(0.045, 900, 1.2, 0.1 * vol, 1.4)
      break
    case 'break':
      burst(0.14, 620, 0.9, 0.22 * vol, 0.75)
      tone(150, 0.1, 'triangle', 0.1 * vol, 90)
      break
    case 'place':
      burst(0.05, 1300, 1.1, 0.12 * vol, 1.2)
      tone(320, 0.07, 'square', 0.06 * vol, 240)
      break
    case 'jump':
      tone(300, 0.14, 'sine', 0.11 * vol, 470)
      break
    case 'land':
      burst(0.09, 240, 0.8, 0.16 * vol, 0.6)
      tone(95, 0.09, 'sine', 0.1 * vol, 60)
      break
    case 'click':
      tone(660, 0.05, 'sine', 0.07 * vol, 880)
      break
    case 'deny':
      tone(190, 0.12, 'square', 0.07 * vol, 150)
      break
    case 'splash':
      burst(0.22, 1100, 0.6, 0.14 * vol, 0.55)
      break
    case 'respawn':
      tone(330, 0.18, 'sine', 0.1 * vol, 520)
      break
    case 'full':
      tone(140, 0.2, 'sawtooth', 0.07 * vol, 120)
      break
    default:
      break
  }
}
