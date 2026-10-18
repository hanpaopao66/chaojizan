// 快捷栏图标:把程序化纹理画成 16×16 的小图,做成 data URL 给 <img> 用(不请求任何外部图片)。
import { TEX_SIDE, buildTextures, type BlockTex } from './textures'

let textures: BlockTex[] | null = null
const cache = new Map<number, string>()

export function blockIconUrl(blockId: number): string {
  const hit = cache.get(blockId)
  if (hit) return hit
  if (!textures) textures = buildTextures()
  const tex = textures[blockId][TEX_SIDE]
  const canvas = document.createElement('canvas')
  canvas.width = 16
  canvas.height = 16
  const ctx = canvas.getContext('2d')
  let url = ''
  if (ctx) {
    const bytes = new Uint8ClampedArray(tex.buffer as ArrayBuffer, tex.byteOffset, tex.byteLength)
    ctx.putImageData(new ImageData(bytes, 16, 16), 0, 0)
    url = canvas.toDataURL('image/png')
  }
  cache.set(blockId, url)
  return url
}
