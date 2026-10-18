// 画布配色与静态地图预渲染:从 render.ts 拆出来,让「画地图」和「每帧画人」两块各自短一点。
//
// 配色全部来自 style.css 的 --tac-* 变量(亮暗 × 两张地图 共四套);改主题时重新读一次即可。

import { CRATE, FLOOR, GameMap, TILE, WALL, WORLD_H, WORLD_W, tileAt } from './map'

/** 画布用的一套颜色,来自 style.css 里的 --tac-* 变量(亮暗各一套) */
export interface Palette {
  bg: string
  floor: string
  floorAlt: string
  grid: string
  wall: string
  wallTop: string
  wallEdge: string
  crate: string
  crateTop: string
  crateEdge: string
  siteA: string
  siteA2: string
  siteB: string
  siteB2: string
  siteInk: string
  player: string
  playerInk: string
  guard: string
  guardInk: string
  bomb: string
  bombInk: string
  ghost: string
  mapInk: string
  tracerPlayer: string
  tracerGuard: string
  shadow: string
  vignette: string
}

const FALLBACK: Palette = {
  bg: '#141A21', floor: '#2C333D', floorAlt: '#273039', grid: '#343D48',
  wall: '#4C5665', wallTop: '#636F81', wallEdge: '#1B2129',
  crate: '#7C5837', crateTop: '#966C43', crateEdge: '#4A301A',
  siteA: '#B98A3E', siteA2: '#9A7130', siteB: '#4F7FA0', siteB2: '#3E6885', siteInk: '#F2E8D0',
  player: '#4FC3F7', playerInk: '#08222E', guard: '#FF7A55', guardInk: '#2A0F08',
  bomb: '#FF5A4D', bombInk: '#2A0B08', ghost: '#CFD8E3', mapInk: '#E8DFC8',
  tracerPlayer: '#9BE1FF', tracerGuard: '#FFB598', shadow: 'rgba(0, 0, 0, .35)',
  vignette: 'rgba(6, 10, 14, .55)',
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** 从 CSS 变量读一套画布配色。主题切换后重新读一次(和界面文字一起换亮暗) */
export function readPalette(): Palette {
  return {
    bg: cssVar('--tac-bg', FALLBACK.bg),
    floor: cssVar('--tac-floor', FALLBACK.floor),
    floorAlt: cssVar('--tac-floor-alt', FALLBACK.floorAlt),
    grid: cssVar('--tac-grid', FALLBACK.grid),
    wall: cssVar('--tac-wall', FALLBACK.wall),
    wallTop: cssVar('--tac-wall-top', FALLBACK.wallTop),
    wallEdge: cssVar('--tac-wall-edge', FALLBACK.wallEdge),
    crate: cssVar('--tac-crate', FALLBACK.crate),
    crateTop: cssVar('--tac-crate-top', FALLBACK.crateTop),
    crateEdge: cssVar('--tac-crate-edge', FALLBACK.crateEdge),
    siteA: cssVar('--tac-site-a', FALLBACK.siteA),
    siteA2: cssVar('--tac-site-a-2', FALLBACK.siteA2),
    siteB: cssVar('--tac-site-b', FALLBACK.siteB),
    siteB2: cssVar('--tac-site-b-2', FALLBACK.siteB2),
    siteInk: cssVar('--tac-site-ink', FALLBACK.siteInk),
    player: cssVar('--tac-player', FALLBACK.player),
    playerInk: cssVar('--tac-player-ink', FALLBACK.playerInk),
    guard: cssVar('--tac-guard', FALLBACK.guard),
    guardInk: cssVar('--tac-guard-ink', FALLBACK.guardInk),
    bomb: cssVar('--tac-bomb', FALLBACK.bomb),
    bombInk: cssVar('--tac-bomb-ink', FALLBACK.bombInk),
    ghost: cssVar('--tac-ghost', FALLBACK.ghost),
    mapInk: cssVar('--tac-map-ink', FALLBACK.mapInk),
    tracerPlayer: cssVar('--tac-tracer-player', FALLBACK.tracerPlayer),
    tracerGuard: cssVar('--tac-tracer-guard', FALLBACK.tracerGuard),
    shadow: cssVar('--tac-shadow', FALLBACK.shadow),
    vignette: cssVar('--tac-vignette', FALLBACK.vignette),
  }
}

export function mapLayerKey(map: GameMap, palette: Palette): string {
  return `${map.theme}|${palette.floor}|${palette.wall}|${palette.siteA}|${palette.siteB}|${map.tiles.length}`
}

/** 把静态地图(地面/墙/摊位/炸弹点)预渲染到一张 2 倍分辨率的离屏画布 */
export function buildMapLayer(map: GameMap, p: Palette): HTMLCanvasElement {
  const layer = document.createElement('canvas')
  const ratio = 2
  layer.width = WORLD_W * ratio
  layer.height = WORLD_H * ratio
  const ctx = layer.getContext('2d')
  if (!ctx) return layer
  const market = map.theme === 'market'
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0)

    // 地面:旧仓库是水泥地 + 砖缝,夜市是斜铺的石板街
    if (market) {
      ctx.fillStyle = p.floor
      ctx.fillRect(0, 0, WORLD_W, WORLD_H)
      for (let row = 0; row < WORLD_H / TILE; row++) {
        for (let col = 0; col < WORLD_W / TILE; col++) {
          ctx.fillStyle = (col + row) % 2 === 0 ? p.floorAlt : p.floor
          ctx.globalAlpha = 0.55
          ctx.fillRect(col * TILE, row * TILE, TILE, TILE)
        }
      }
      ctx.globalAlpha = 1
      ctx.strokeStyle = p.grid
      ctx.globalAlpha = 0.32
      ctx.lineWidth = 1
      ctx.beginPath()
      for (let k = -WORLD_H; k < WORLD_W; k += TILE * 2) {
        ctx.moveTo(k, 0)
        ctx.lineTo(k + WORLD_H, WORLD_H)
      }
      ctx.stroke()
      ctx.globalAlpha = 1
    } else {
      for (let row = 0; row < WORLD_H / TILE; row++) {
        for (let col = 0; col < WORLD_W / TILE; col++) {
          ctx.fillStyle = (col * 7 + row * 13) % 3 === 0 ? p.floorAlt : p.floor
          ctx.fillRect(col * TILE, row * TILE, TILE, TILE)
        }
      }
      ctx.strokeStyle = p.grid
      ctx.globalAlpha = 0.45
      ctx.lineWidth = 1
      ctx.beginPath()
      for (let x = 0; x <= WORLD_W; x += TILE) {
        ctx.moveTo(x + 0.5, 0)
        ctx.lineTo(x + 0.5, WORLD_H)
      }
      for (let y = 0; y <= WORLD_H; y += TILE) {
        ctx.moveTo(0, y + 0.5)
        ctx.lineTo(WORLD_W, y + 0.5)
      }
      ctx.stroke()
      ctx.globalAlpha = 1
    }

    paintSite(ctx, p, map.siteA, p.siteA, p.siteA2, 'A', market)
    paintSite(ctx, p, map.siteB, p.siteB, p.siteB2, 'B', market)

    // 墙和箱子
    for (let row = 0; row < WORLD_H / TILE; row++) {
      for (let col = 0; col < WORLD_W / TILE; col++) {
        const tile = tileAt(map, col, row)
        if (tile === FLOOR) continue
        const x = col * TILE
        const y = row * TILE
        ctx.fillStyle = p.shadow
        ctx.fillRect(x + 2, y + 4, TILE, TILE)
        if (tile === WALL) {
          ctx.fillStyle = p.wall
          ctx.fillRect(x, y, TILE, TILE)
          ctx.fillStyle = p.wallTop
          ctx.fillRect(x, y, TILE, 5)
          ctx.strokeStyle = p.wallEdge
          ctx.lineWidth = 1
          ctx.strokeRect(x + 0.5, y + 0.5, TILE - 1, TILE - 1)
        } else if (tile === CRATE) {
          if (market) {
            // 夜市摊位:遮阳棚条纹 + 下面的桌子
            ctx.fillStyle = p.crate
            ctx.fillRect(x + 2, y + 2, TILE - 4, TILE - 4)
            ctx.fillStyle = p.crateTop
            ctx.fillRect(x + 2, y + 2, TILE - 4, 6)
            ctx.fillStyle = p.siteInk
            ctx.globalAlpha = 0.35
            for (let k = 0; k < 3; k++) ctx.fillRect(x + 3 + k * 8, y + 2, 3, 6)
            ctx.globalAlpha = 1
            ctx.strokeStyle = p.crateEdge
            ctx.lineWidth = 1.5
            ctx.strokeRect(x + 2.5, y + 2.5, TILE - 5, TILE - 5)
            ctx.beginPath()
            ctx.moveTo(x + 3, y + TILE - 4)
            ctx.lineTo(x + TILE - 3, y + TILE - 4)
            ctx.stroke()
          } else {
            ctx.fillStyle = p.crate
            ctx.fillRect(x + 2, y + 2, TILE - 4, TILE - 4)
            ctx.fillStyle = p.crateTop
            ctx.fillRect(x + 2, y + 2, TILE - 4, 5)
            ctx.strokeStyle = p.crateEdge
            ctx.lineWidth = 1.5
            ctx.strokeRect(x + 2.5, y + 2.5, TILE - 5, TILE - 5)
            ctx.beginPath()
            ctx.moveTo(x + 4, y + TILE - 6)
            ctx.lineTo(x + TILE - 6, y + 5)
            ctx.stroke()
          }
        }
      }
    }
    // 地图最外圈压一道深色边
    ctx.strokeStyle = p.wallEdge
    ctx.lineWidth = 6
  ctx.strokeRect(3, 3, WORLD_W - 6, WORLD_H - 6)
  return layer
}


function paintSite(
  ctx: CanvasRenderingContext2D,
  palette: Palette,
  rect: { x0: number; y0: number; x1: number; y1: number },
  base: string,
  alt: string,
  letter: string,
  market: boolean,
): void {
    const x = rect.x0 * TILE
    const y = rect.y0 * TILE
    const w = (rect.x1 - rect.x0 + 1) * TILE
    const h = (rect.y1 - rect.y0 + 1) * TILE
  const p = palette
    ctx.save()
    ctx.fillStyle = base
    ctx.globalAlpha = 0.5
    ctx.fillRect(x, y, w, h)
    ctx.globalAlpha = 0.9
    ctx.strokeStyle = alt
    ctx.lineWidth = 3
    ctx.strokeRect(x + 2, y + 2, w - 4, h - 4)
    // 斜纹
    ctx.globalAlpha = 0.22
    ctx.beginPath()
    for (let k = -h; k < w; k += 18) {
      ctx.moveTo(x + k, y + h)
      ctx.lineTo(x + k + h, y)
    }
    ctx.stroke()
    ctx.globalAlpha = 1
    ctx.fillStyle = p.siteInk
    ctx.font = 'bold 58px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    if (market) {
      // 夜市霓虹:字母外圈一点辉光
      ctx.shadowColor = alt
      ctx.shadowBlur = 16
    }
    ctx.fillText(letter, x + w / 2, y + h / 2)
    ctx.restore()
  }

export { FALLBACK as DEFAULT_PALETTE }
