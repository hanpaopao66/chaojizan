// 守卫的脑子:纯决策,不动、不开枪,只回答「现在该干什么、看向哪、要不要扣扳机」。
//
// 状态:守点(hold)→ 听到枪声/炸弹声去调查(investigate)→ 看见玩家交火(engage)→ 炸弹安放后去拆(defuse)。
// 走位、转身、开枪的时序在 match.ts 里执行;这里只做判断,所以单测能摆一个局面直接问它「你下一步想干嘛」。
import { GameMap, TILE, Vec, angleDiff, angleTo, dist, lineOfSight } from './map'
import { GuardSkill } from './combat'
import { rand } from '../../shared/src/rand'

export type GuardMode = 'hold' | 'investigate' | 'engage' | 'defuse'

/** 一个「声音」:玩家开枪、安弹、爆炸。守卫听得到才去调查 */
export interface Noise {
  pos: Vec
  kind: 'shot' | 'plant' | 'explode'
  team: 'player' | 'guard'
  /** 发生时间(回合内秒数) */
  at: number
}

export interface BombInfo {
  planted: boolean
  pos: Vec | null
  /** 已经安放了多久(秒) */
  plantedFor: number
}

export interface GuardBrain {
  mode: GuardMode
  /** 守卫的岗位(守点时回到这里) */
  home: Vec
  /** 岗位朝向,守点时沿这个方向左右看 */
  face: number
  /** 当前想去的地方 */
  target: Vec | null
  /** 上一次看见玩家的位置和时间 */
  lastSeen: Vec | null
  lastSeenAt: number
  /** 看见玩家后,到这里才能开枪(反应时间) */
  alertAt: number
  /** 正在去调查的声音位置 */
  heardPos: Vec | null
  /** 炸弹安放后,这名守卫决定去拆弹的时间(1–2 秒的随机延迟) */
  defuseAt: number
  /** 扫视相位,三个守卫不会像复制粘贴一样同步摆头 */
  scan: number
}

export interface GuardContext {
  /** 回合内已经过的秒数 */
  now: number
  pos: Vec
  /** 当前朝向 */
  angle: number
  /** 引擎已经算好的「现在能不能看见玩家」(视距 + 视野角 + 视线) */
  seesPlayer: boolean
  playerPos: Vec
  /** 这个守卫最近听到的、还没过期的声音 */
  heard: Noise | null
  bomb: BombInfo
  skill: GuardSkill
}

export interface GuardIntent {
  mode: GuardMode
  /** 想走到哪(世界坐标);null = 原地 */
  moveTo: Vec | null
  /** 想看向的角度 */
  lookAngle: number
  /** 想扣扳机(还要引擎看反应时间、枪的冷却和瞄准角) */
  fire: boolean
  /** 想拆弹(真的到炸弹旁边、计时由引擎算) */
  defuse: boolean
}

export interface GuardDecision {
  brain: GuardBrain
  intent: GuardIntent
  /** 决策里消耗过随机数,状态要带回去 */
  rng: number
}

/** 新建一个守卫的脑子。seed 决定扫视相位;face 是守点时的朝向 */
export function newBrain(home: Vec, face: number, seed: number, now: number): GuardBrain {
  const [u] = rand(seed)
  return {
    mode: 'hold',
    home,
    face,
    target: null,
    lastSeen: null,
    lastSeenAt: -99,
    alertAt: now,
    heardPos: null,
    defuseAt: 0,
    scan: u * Math.PI * 2,
  }
}

/** 守卫能不能看见玩家:视距内 + 视野角内(贴脸 3 格算 360 度感知)+ 视线没被挡 */
export function guardSeesPlayer(
  map: GameMap, guardPos: Vec, angle: number, skill: GuardSkill, playerPos: Vec,
): boolean {
  const d = dist(guardPos, playerPos)
  if (d > skill.viewRange) return false
  if (d > TILE * 3) {
    const off = Math.abs(angleDiff(angle, angleTo(guardPos, playerPos)))
    if (off > skill.fov / 2) return false
  }
  return lineOfSight(map, guardPos, playerPos)
}

/**
 * 守卫的一步决策。传入现在看到的/听到的,返回新的脑子和打算。
 * 优先级:看见玩家就交火 > 追刚才看见的位置 > 去拆弹 > 调查声音 > 守点。
 */
export function decideGuard(brain: GuardBrain, ctx: GuardContext, rng: number): GuardDecision {
  const b: GuardBrain = { ...brain }
  let r = rng

  // 炸弹刚安放:每名守卫 1–2 秒后决定去拆(用随机数错开,不会三个人同一个 tick 转身)
  if (ctx.bomb.planted && ctx.bomb.pos && b.defuseAt === 0) {
    const [u, next] = rand(r)
    r = next
    b.defuseAt = ctx.now + 1 + u
  }

  const lookAt = (p: Vec): number => angleTo(ctx.pos, p)

  if (ctx.seesPlayer) {
    if (b.mode !== 'engage') {
      // 刚看见:反应时间带一点随机(0.8–1.3 倍),同一帧三个人不会一起开枪
      const [u, next] = rand(r)
      r = next
      b.alertAt = ctx.now + ctx.skill.reaction * (0.8 + u * 0.5)
      b.mode = 'engage'
    }
    b.lastSeen = ctx.playerPos
    b.lastSeenAt = ctx.now
    b.target = ctx.playerPos
    return {
      brain: b,
      rng: r,
      intent: {
        mode: 'engage',
        // 离得远就压上去,近了站着打 —— 守卫不会贴脸绕圈
        moveTo: dist(ctx.pos, ctx.playerPos) > TILE * 5 ? ctx.playerPos : null,
        lookAngle: lookAt(ctx.playerPos),
        fire: ctx.now >= b.alertAt,
        defuse: false,
      },
    }
  }

  // 刚看不见:去最后看见的位置找一圈,4 秒内找不到就放弃
  if (b.mode === 'engage' && b.lastSeen && ctx.now - b.lastSeenAt < 4) {
    const arrived = dist(ctx.pos, b.lastSeen) < TILE * 0.9
    b.mode = arrived ? 'investigate' : 'engage'
    b.target = arrived ? null : b.lastSeen
    return {
      brain: b,
      rng: r,
      intent: {
        mode: b.mode,
        moveTo: arrived ? null : b.lastSeen,
        lookAngle: lookAt(b.lastSeen),
        fire: false,
        defuse: false,
      },
    }
  }

  // 炸弹安放了:去拆。玩家露头就又会走回上面的交火分支
  if (ctx.bomb.planted && ctx.bomb.pos && ctx.now >= b.defuseAt) {
    b.mode = 'defuse'
    b.target = ctx.bomb.pos
    return {
      brain: b,
      rng: r,
      intent: {
        mode: 'defuse',
        moveTo: ctx.bomb.pos,
        lookAngle: lookAt(ctx.bomb.pos),
        fire: false,
        defuse: true,
      },
    }
  }

  // 听到声音:过去看。到了就在附近原地扫视
  if (ctx.heard && ctx.now - ctx.heard.at < 6) {
    if (b.mode !== 'investigate') {
      b.mode = 'investigate'
      b.heardPos = ctx.heard.pos
    }
    const spot = b.heardPos || ctx.heard.pos
    const arrived = dist(ctx.pos, spot) < TILE * 1.1
    b.target = arrived ? null : spot
    return {
      brain: b,
      rng: r,
      intent: {
        mode: 'investigate',
        moveTo: arrived ? null : spot,
        lookAngle: arrived
          ? b.face + Math.sin(ctx.now * 1.1 + b.scan) * 1.1
          : lookAt(spot),
        fire: false,
        defuse: false,
      },
    }
  }

  // 守点:不在岗位就慢慢走回去,在岗位上左右看
  b.mode = 'hold'
  b.heardPos = null
  const home = b.home
  const homeGap = dist(ctx.pos, home)
  b.target = homeGap > TILE * 1.2 ? home : null
  return {
    brain: b,
    rng: r,
    intent: {
      mode: 'hold',
      moveTo: b.target,
      lookAngle: b.face + Math.sin(ctx.now * 0.75 + b.scan) * 0.9,
      fire: false,
      defuse: false,
    },
  }
}
