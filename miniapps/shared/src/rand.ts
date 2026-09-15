// 带种子的随机数(mulberry32,和 2048 同一个)。
//
// 状态就是一个 32 位整数,存进存档里:同一个种子、同一串操作,结果永远一样 ——
// 关了再开接得上,测试也能复现。引擎里只用这里的函数,不碰 Math.random。

/** 取一个 [0, 1) 的数,返回 [数, 下一个状态] */
export function rand(seed: number): [number, number] {
  let t = (seed + 0x6d2b79f5) >>> 0
  const next = t
  t = Math.imul(t ^ (t >>> 15), t | 1)
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
  return [((t ^ (t >>> 14)) >>> 0) / 4294967296, next]
}

/** 取 [0, n) 的整数,返回 [数, 下一个状态] */
export function randInt(seed: number, n: number): [number, number] {
  const [a, next] = rand(seed)
  return [Math.floor(a * n), next]
}

/** 洗牌(Fisher–Yates),不改原数组,返回 [新数组, 下一个状态] */
export function shuffle<T>(items: readonly T[], seed: number): [T[], number] {
  const out = items.slice()
  let s = seed
  for (let i = out.length - 1; i > 0; i--) {
    let j: number
    ;[j, s] = randInt(s, i + 1)
    const t = out[i]
    out[i] = out[j]
    out[j] = t
  }
  return [out, s]
}

/** 开新局用的种子。只在界面层调 */
export function freshSeed(): number {
  return (Math.random() * 2 ** 32) >>> 0
}
