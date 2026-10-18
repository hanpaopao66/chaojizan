// 带种子的 value noise:同一个种子永远得到同一座岛,测试也能复现。
//
// 实现:用 shared/src/rand 的 mulberry32 一次性生成几层低分辨率晶格值(每层格距不同),
// 采样时对每层做 smoothstep 双线性插值再叠加。不用 Math.random,不用浮点哈希的玄学实现 ——
// 只要 rand() 不变,同一个种子在任何设备上生成的山都一模一样。
import { rand } from '../../shared/src/rand'

/** 采样函数:x、z 是方块坐标(0..128 附近),返回 0..1 */
export interface ValueNoise {
  (x: number, z: number): number
}

/** 一层噪声:格距(方块数)、振幅、每边格点数、晶格值 */
interface Layer {
  cell: number
  amp: number
  cols: number
  vals: Float32Array
}

export const NOISE_SIZE = 128

const smooth = (t: number): number => t * t * (3 - 2 * t)

function buildLayers(seed: number, cells: readonly number[], amps: readonly number[]): Layer[] {
  let s = (seed ^ 0x9e3779b9) >>> 0
  const layers: Layer[] = []
  for (let i = 0; i < cells.length; i++) {
    const cell = cells[i]
    // 覆盖 0..NOISE_SIZE 再留两格:采样到边界外面也不会越界
    const cols = Math.ceil(NOISE_SIZE / cell) + 2
    const vals = new Float32Array(cols * cols)
    for (let k = 0; k < vals.length; k++) {
      const [v, next] = rand(s)
      s = next
      vals[k] = v
    }
    layers.push({ cell, amp: amps[i], cols, vals })
  }
  return layers
}

function sampleLayer(layer: Layer, x: number, z: number): number {
  const gx = x / layer.cell
  const gz = z / layer.cell
  const ix = Math.floor(gx)
  const iz = Math.floor(gz)
  const fx = smooth(gx - ix)
  const fz = smooth(gz - iz)
  const cols = layer.cols
  const vals = layer.vals
  // 取模:噪声是周期性的(周期约等于世界大小),世界生成里带偏移采样(比如 x+37)也不会越界
  const x0 = ((ix % cols) + cols) % cols
  const x1 = (x0 + 1) % cols
  const z0 = ((iz % cols) + cols) % cols
  const z1 = (z0 + 1) % cols
  const i00 = z0 * cols + x0
  const i01 = z0 * cols + x1
  const i10 = z1 * cols + x0
  const i11 = z1 * cols + x1
  const a = vals[i00] + (vals[i01] - vals[i00]) * fx
  const b = vals[i10] + (vals[i11] - vals[i10]) * fx
  return a + (b - a) * fz
}

function makeNoise(seed: number, cells: readonly number[], amps: readonly number[]): ValueNoise {
  const layers = buildLayers(seed, cells, amps)
  let total = 0
  for (const a of amps) total += a
  return (x: number, z: number): number => {
    let sum = 0
    for (let i = 0; i < layers.length; i++) sum += sampleLayer(layers[i], x, z) * layers[i].amp
    return sum / total
  }
}

/** 地形用:波长 64 / 32 / 16 / 8 格,四层叠加(0..1) */
export function terrainNoise(seed: number): ValueNoise {
  return makeNoise(seed, [64, 32, 16, 8], [0.42, 0.27, 0.19, 0.12])
}

/** 细节用:波长 16 / 8 / 4 / 2 格,决定沙滩边线、石头斑块、树的位置(0..1) */
export function detailNoise(seed: number): ValueNoise {
  return makeNoise(seed ^ 0x5bd1e995, [16, 8, 4, 2], [0.4, 0.28, 0.2, 0.12])
}

/** 把平滑斜坡映射到 0..1(比 clamp 温柔的过渡,做海岸线和昼夜亮度用) */
export function smoothstep(edge0: number, edge1: number, x: number): number {
  if (edge0 === edge1) return x < edge0 ? 0 : 1
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)))
  return t * t * (3 - 2 * t)
}
