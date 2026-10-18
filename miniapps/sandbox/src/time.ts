// 世界时间:一轮约 8 分钟,太阳/月亮的位置、昼夜亮度、HUD 时钟都从这里算。纯函数。
//
// t = 0 是日出(06:00),0.25 正午,0.5 日落(18:00),0.75 午夜。
// 存档里存的是 0..1 的进度,换设备、关了再开时间接着走。
// 亮度/暖色的平滑参数在 data.ts 的 DAY 里。
import { DAY, VIEW } from './data'

/** 一轮多少秒(8 分钟) */
export const DAY_SECONDS = DAY.SECONDS

/** 太阳/月亮在天空里的角半径(弧度),投影到屏幕时用 */
export const SUN_RADIUS = VIEW.SUN_RADIUS

/** 把任意数折回 [0,1) */
export function wrapTime(t: number): number {
  if (!Number.isFinite(t)) return 0
  const r = t % 1
  return r < 0 ? r + 1 : r
}

/** 太阳方向(单位向量,y 向上)。月亮就是它的反方向。 */
export function sunDirection(t: number): { x: number; y: number; z: number } {
  const a = wrapTime(t) * Math.PI * 2
  const x = Math.cos(a)
  const y = Math.sin(a)
  const z = 0.22
  const len = Math.hypot(x, y, z)
  return { x: x / len, y: y / len, z: z / len }
}

/** 0 = 全黑(深夜),1 = 大白天;日出日落前后平滑过渡 */
export function daylight(t: number): number {
  const s = sunDirection(t)
  const x = Math.min(1, Math.max(0, (s.y - DAY.LIGHT_LO) / DAY.LIGHT_SPAN))
  return x * x * (3 - 2 * x)
}

/** 天边暖色强度:太阳贴着地平线时最大(日出/日落),用来给天空和地面染色 */
export function warmth(t: number): number {
  const y = sunDirection(t).y
  const v = 1 - Math.min(1, Math.abs(y) / DAY.WARM_SPAN)
  return v * v
}

/** 一天的时段名,给 ARIA 播报和图标用 */
export function phaseOf(t: number): 'dawn' | 'day' | 'dusk' | 'night' {
  const d = daylight(t)
  if (d < DAY.NIGHT_LIGHT) return 'night'
  if (warmth(t) > 0.6) return wrapTime(t) < 0.5 ? 'dawn' : 'dusk'
  return 'day'
}

/** 时钟文字 06:00 / 18:30;t=0 从 6 点开始 */
export function clockText(t: number): string {
  const hours = (6 + wrapTime(t) * 24) % 24
  const h = Math.floor(hours)
  const m = Math.floor((hours - h) * 60)
  return `${h < 10 ? '0' : ''}${h}:${m < 10 ? '0' : ''}${m}`
}

/** HUD 上的时间图标:白天太阳、夜里月亮、日出日落也是太阳 */
export function phaseIcon(t: number): string {
  return daylight(t) < DAY.NIGHT_LIGHT ? '☾' : '☀'
}
