// 快捷栏图标:把程序化纹理(侧面,变体 0)画成 16×16 的小图,做成 data URL 给 <img> 用。
// 不请求任何外部图片;CSP 的 img-src 'self' data: blob: 允许 data: URL。
import { TEX, TEX_SIDE, buildTextures, sampleFace, type BlockTex } from './textures'

let textures: BlockTex[] | null = null
const cache = new Map<number, string>()

export function blockIconUrl(blockId: number): string {
  const hit = cache.get(blockId)
  if (hit) return hit
  if (!textures) textures = buildTextures()
  const tex = textures[blockId][TEX_SIDE]
  const canvas = document.createElement('canvas')
  canvas.width = TEX
  canvas.height = TEX
  const ctx = canvas.getContext('2d')
  let url = ''
  if (ctx) {
    const img = ctx.createImageData(TEX, TEX)
    const out = new Uint32Array(img.data.buffer)
    for (let y = 0; y < TEX; y++) {
      for (let x = 0; x < TEX; x++) out[y * TEX + x] = sampleFace(tex, 0, x, y)
    }
    ctx.putImageData(img, 0, 0)
    url = canvas.toDataURL('image/png')
  }
  cache.set(blockId, url)
  return url
}
