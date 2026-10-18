// 只在开发服务器上安装的测试钩子:浏览器端到端(自动走位/切枪/安放)需要读对局状态。
//
// 只读:所有写操作(移动、开火、切枪、安放)仍然走真实的键盘/鼠标/触摸事件。
// 生产构建里 main.ts 的 `if (import.meta.env.DEV)` 是 false,这个模块不会被包含进产物
// (见 ASSETS/验收里的 grep:构建产物中搜不到 __tactical)。

import { GameMap, Vec, WORLD_H, WORLD_W, lineOfSight } from './map'
import { MatchState, Round, canPlant } from './match'
import { routeBetween } from './nav'

export interface DevEnv {
  round: () => Round | null
  match: () => MatchState | null
  running: () => boolean
  paused: () => boolean
  coarse: () => boolean
  map: () => GameMap
  frames: () => number
}

/** 世界坐标 → 视口坐标(端到端脚本瞄准用) */
function screenAt(world: Vec): Vec {
  const canvas = document.getElementById('field') as HTMLCanvasElement
  const rect = canvas.getBoundingClientRect()
  const scale = Math.min(rect.width / WORLD_W, rect.height / WORLD_H)
  const ox = (rect.width - WORLD_W * scale) / 2
  const oy = (rect.height - WORLD_H * scale) / 2
  return { x: rect.left + ox + world.x * scale, y: rect.top + oy + world.y * scale }
}

export function installDevHook(env: DevEnv): void {
  const dev: Record<string, unknown> = {}

  dev.state = () => {
    const round = env.round()
    const match = env.match()
    if (!round || !match) return null
    const p = round.player
    return {
      running: env.running(),
      paused: env.paused(),
      coarse: env.coarse(),
      phase: round.phase,
      clock: round.clock,
      elapsed: round.elapsed,
      roundNo: match.round,
      score: [match.scorePlayer, match.scoreGuard],
      matchOver: match.over,
      training: round.training,
      mapId: round.map.id,
      mapName: round.map.name,
      player: {
        x: p.pos.x,
        y: p.pos.y,
        hp: p.hp,
        alive: p.alive,
        site: p.site,
        active: p.active,
        weapon: p.weapons[p.active].name,
        mag: p.guns[p.active].mag,
        reserve: p.guns[p.active].reserve,
        secondary: p.guns[p.active === 0 ? 1 : 0].mag,
        switchLeft: p.switchLeft,
      },
      guards: round.guards.map((g) => ({
        id: g.id, x: g.pos.x, y: g.pos.y, hp: g.hp, alive: g.alive, mode: g.brain.mode,
      })),
      bomb: {
        state: round.bomb.state,
        x: round.bomb.pos ? round.bomb.pos.x : null,
        y: round.bomb.pos ? round.bomb.pos.y : null,
        plant: round.bomb.plant,
        timer: round.bomb.timer,
        defuse: round.bomb.defuse,
      },
    }
  }

  dev.route = (from: Vec, to: Vec): Vec[] => {
    const round = env.round()
    return round ? routeBetween(round.nav, from, to) : []
  }
  dev.site = (id: 'A' | 'B'): Vec => {
    const rect = id === 'A' ? env.map().siteA : env.map().siteB
    return { x: ((rect.x0 + rect.x1 + 1) / 2) * 24, y: ((rect.y0 + rect.y1 + 1) / 2) * 24 }
  }
  dev.los = (a: Vec, b: Vec): boolean => lineOfSight(env.map(), a, b)
  dev.canPlant = (): boolean => {
    const round = env.round()
    return round ? canPlant(round) : false
  }
  dev.placeAtSite = (id: 'A' | 'B'): boolean => {
    const round = env.round()
    if (!round || round.phase === 'over') return false
    // 放到炸弹点靠角的一格,避免和守卫出生点(点在正中心)重叠
    const rect = id === 'A' ? round.map.siteA : round.map.siteB
    round.player.pos = { x: (rect.x0 + 1.5) * 24, y: (rect.y0 + 1.5) * 24 }
    round.player.site = id
    return true
  }
  dev.frames = (): number => env.frames()
  dev.world = (): { w: number; h: number } => ({ w: WORLD_W, h: WORLD_H })
  dev.screenAt = screenAt

  ;(window as unknown as { __tactical?: Record<string, unknown> }).__tactical = dev
}
