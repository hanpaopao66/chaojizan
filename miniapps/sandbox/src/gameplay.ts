// 一局世界里的玩法:移动、挖、放、统计、成就、碎屑粒子。纯逻辑 + 可注入的副作用,
// 不碰 DOM、不碰存档、不碰渲染 —— 所以可以在 node 单测里驱动它(见 test/gameplay.test.ts)。
//
// main.ts 只负责:把设备输入翻译成 GameInput、把副作用接到 HUD/音效/存档/弹层、每帧调 update。
import {
  AIR, GRASS, HOTBAR, SAND, STONE, WATER, blockMaterial, blockName, breakTime,
} from './blocks'
import { addBlock } from './inventory'
import { DAY, FEEL, LIMITS, TEXT, type AchievementDef, type Material, type SoundName, type SoundOptions } from './data'
import { checkAchievements, emptyContext, BIOME_GRASS, BIOME_SAND, BIOME_STONE } from './achievements'
import { canPlace, newMineState, newPlaceCooldown, nextStreak, tickMining, tickPlaceCooldown, type MineState } from './interaction'
import { MAX_PARTICLES, spawnBreakParticles, updateParticles, type Particle } from './particles'
import {
  cameraEye, clampPitch, newPlayer, placePlayer, stepPlayer, type PlayerState, type StepResult,
} from './player'
import { addStat, emptyProfile, unlockedCount, type Profile } from './profile'
import { placePosition, rayFromEye, type RayHit } from './raycast'
import { newSave, type GameSave } from './save'
import { DAY_SECONDS, daylight, wrapTime } from './time'
import { World } from './world'
import { D, H, W, type Spawn } from './worldgen'

export interface GameEffects {
  sound(name: SoundName, opts?: SoundOptions): void
  toast(text: string): void
  announce(text: string): void
  /** 解锁了一个成就(界面弹提示 + 写档案) */
  achievement(def: AchievementDef): void
  /** 改动到 4000 格上限:界面弹清理面板 */
  cleanupNeeded(): void
  /** 世界/档案有改动,主循环按节流策略存档 */
  markDirty(kind: 'world' | 'profile'): void
}

/** 一帧的输入(设备层翻译好;视角增量单位是弧度) */
export interface GameInput {
  forward: number
  strafe: number
  jump: boolean
  jumpPressed: boolean
  mine: boolean
  placePressed: boolean
  lookDX: number
  lookDY: number
  lookKeyX: number
  lookKeyY: number
}

export function emptyInput(): GameInput {
  return {
    forward: 0, strafe: 0, jump: false, jumpPressed: false, mine: false,
    placePressed: false, lookDX: 0, lookDY: 0, lookKeyX: 0, lookKeyY: 0,
  }
}

/** 统计面板需要的数据 */
export interface GameStats {
  seed: number
  mined: number
  placed: number
  walked: number
  seconds: number
  achievements: number
  achievementsTotal: number
  edits: number
  editRatio: number
  height: number
  time: number
}

const TAU = Math.PI * 2

export class Game {
  world: World | null = null
  player: PlayerState = newPlayer(0, 0, 0, 0)
  inv: number[] = []
  hot = 0
  /** 世界时间 0..1 */
  time: number = DAY.START
  /** 准星对准的方块(没有就是 null) */
  target: RayHit | null = null
  /** 累计统计 + 成就(由 main 放进 SaveSlot 的 best 槽) */
  profile: Profile = emptyProfile()
  particles: Particle[] = []
  /** 挖掘进度 0..1(渲染裂纹/进度条用) */
  miningProgress = 0

  private mine: MineState = newMineState()
  private placeCooldown = 0
  private streak = 0
  private nightMined = 0
  private swimSeconds = 0
  private biomeMask = 0
  private maxY = 0
  private stepAccum = 0
  private achieveTimer = 0
  private particleSeed = 1
  private deniedKey = ''
  private profileDirty = false
  private worldDirty = false

  constructor(private readonly effects: GameEffects) {}

  /** 开始/读档进入一个世界;profile 由调用方合并好传进来(会被本对象就地更新) */
  load(save: GameSave, profile: Profile, prebuilt: World | null = null): void {
    const world = prebuilt ?? new World(save.seed)
    if (!prebuilt && !world.loadEdits(save.edits)) world.loadEdits('')
    this.world = world
    this.profile = profile
    this.player = newPlayer(save.player.x, save.player.y, save.player.z, save.player.yaw)
    this.player.pitch = clampPitch(save.player.pitch)
    placePlayer(world, this.player, save.player.x, save.player.y, save.player.z)
    this.inv = save.inv.slice()
    this.hot = Math.max(0, Math.min(HOTBAR.length - 1, Math.floor(save.hot)))
    this.time = wrapTime(save.time)
    this.target = null
    this.mine = newMineState()
    this.placeCooldown = 0
    this.miningProgress = 0
    this.particles = []
    this.walkedReset()
    this.profileDirty = false
    this.worldDirty = false
    this.streak = 0
    this.nightMined = 0
    this.swimSeconds = 0
    this.biomeMask = 0
    this.maxY = this.player.y
    this.achieveTimer = 0
    this.deniedKey = ''
  }

  /** 新建世界的快捷入口:生成出生点、默认背包 */
  loadNew(seed: number, prebuilt: World): void {
    const save = newSave(seed, prebuilt.spawn, prebuilt.yaw)
    this.load(save, this.profile, prebuilt)
    this.profileDirty = true
    this.worldDirty = true
  }

  // ---------------------------------------------------------------- 每帧

  update(dt: number, input: GameInput): void {
    const world = this.world
    if (!world) return
    const step = Math.min(FEEL.MAX_DT, Math.max(0, dt))
    if (step <= 0) return
    addStat(this.profile, 'seconds', step)
    this.time = wrapTime(this.time + step / DAY_SECONDS)

    // ---- 视角
    const p = this.player
    p.yaw += input.lookDX
    p.pitch = clampPitch(p.pitch - input.lookDY)
    if (input.lookKeyX || input.lookKeyY) {
      p.yaw += input.lookKeyX * FEEL.KEY_LOOK_YAW * step
      p.pitch = clampPitch(p.pitch + input.lookKeyY * FEEL.KEY_LOOK_PITCH * step)
    }
    p.yaw = ((p.yaw % TAU) + TAU) % TAU

    // ---- 移动
    const beforeX = p.x
    const beforeZ = p.z
    const res: StepResult = stepPlayer(world, p, {
      forward: input.forward, strafe: input.strafe, jump: input.jump, jumpPressed: input.jumpPressed,
    }, step)
    this.afterMove(world, res, beforeX, beforeZ, step)

    // ---- 准星
    const eye = cameraEye(p)
    this.target = rayFromEye(world, eye.x, eye.y, eye.z, p.yaw, p.pitch, LIMITS.REACH)

    // ---- 挖
    this.updateMining(world, input, step)

    // ---- 放(带冷却,防止连点一口气放一排)
    this.placeCooldown = tickPlaceCooldown(this.placeCooldown, step)
    if (input.placePressed && canPlace(this.placeCooldown)) {
      this.placeCooldown = newPlaceCooldown()
      this.tryPlace(world)
    }

    // ---- 成就:每 0.4 秒查一遍 + 挖/放时立刻查
    this.achieveTimer += step
    if (this.achieveTimer >= LIMITS.ACHIEVE_CHECK) {
      this.achieveTimer = 0
      this.checkAchievements()
    }

    // ---- 碎屑
    updateParticles(this.particles, step)
  }

  private afterMove(world: World, res: StepResult, beforeX: number, beforeZ: number, step: number): void {
    const p = this.player
    const moved = Math.hypot(p.x - beforeX, p.z - beforeZ)
    if (moved > 0) {
      addStat(this.profile, 'walked', moved)
      this.stepAccum += moved
    }
    if (p.onGround && this.stepAccum >= FEEL.STEP_DISTANCE) {
      this.stepAccum = 0
      const below = world.blockAt(Math.floor(p.x), Math.floor(p.y - 0.05), Math.floor(p.z))
      this.effects.sound('step', { material: p.inWater ? 'water' : blockMaterial(below), vol: 0.8 })
    }
    if (res.jumped && !p.inWater) this.effects.sound('jump', { vol: 0.8 })
    if (res.landed) this.effects.sound('land', { material: blockMaterial(world.blockAt(Math.floor(p.x), Math.floor(p.y - 0.05), Math.floor(p.z))) })
    if (res.fellOut) this.respawn()

    // 水里待着的时长(「水性不错」)
    if (p.inWater) this.swimSeconds += step
    else this.swimSeconds = 0
    // 踩到过哪种地形
    if (p.onGround) {
      const below = world.blockAt(Math.floor(p.x), Math.floor(p.y - 0.05), Math.floor(p.z))
      if (below === GRASS) this.biomeMask |= BIOME_GRASS
      else if (below === SAND) this.biomeMask |= BIOME_SAND
      else if (below === STONE) this.biomeMask |= BIOME_STONE
    }
    if (p.y > this.maxY) this.maxY = p.y
    this.effects.markDirty('profile')
  }

  private updateMining(world: World, input: GameInput, step: number): void {
    const target = this.target
    const key = target ? `${target.x},${target.y},${target.z}` : null
    const block = target ? target.block : AIR
    const tick = tickMining(this.mine, key, input.mine, block, this.player.inWater, step)
    this.miningProgress = this.mine.progress
    if (tick.tickSound && target) {
      this.effects.sound('mine', { material: blockMaterial(target.block), vol: 0.7 })
    }
    if (tick.changed && !tick.broke) this.effects.markDirty('profile')
    if (tick.broke && target) {
      this.breakBlock(world, target)
      this.streak = nextStreak(this.streak, input.mine, true, false)
      this.checkAchievements()
      this.effects.markDirty('profile')
    }
    // 挖不动的方块(基岩):提示一次,别每帧刷
    if (target && key !== this.deniedKey) {
      const hardness = block === AIR ? Infinity : breakTime(block, this.player.inWater)
      if (!Number.isFinite(hardness)) {
        this.deniedKey = key ?? ''
        this.effects.sound('deny')
        this.effects.toast('基岩挖不动:世界最底下两层是基岩')
        this.effects.announce('基岩挖不动')
      } else {
        this.deniedKey = ''
      }
    }
    if (!input.mine) this.streak = 0
  }

  private breakBlock(world: World, hit: RayHit): void {
    const result = world.setBlock(hit.x, hit.y, hit.z, AIR)
    if (result === 'ok') {
      this.worldDirty = true
      addStat(this.profile, 'mined', 1)
      if (this.isNight()) this.nightMined++
      addBlock(this.inv, hit.block)
      this.spawnDust(hit.x, hit.y, hit.z, hit.block)
      this.effects.sound('break', { material: blockMaterial(hit.block) })
      this.effects.announce(`挖掉了${blockName(hit.block)}`)
      this.effects.markDirty('world')
      this.target = null
      return
    }
    if (result === 'full') {
      this.effects.sound('full')
      this.effects.toast(`${TEXT.FULL_LIMIT}:${TEXT.FULL_HINT}`)
      this.effects.announce('改动到上限了,需要先清理')
      this.effects.cleanupNeeded()
      return
    }
    if (result === 'bedrock') this.effects.sound('deny')
  }

  private tryPlace(world: World): void {
    const target = this.target
    if (!target) return
    const pos = placePosition(target)
    const blockId = HOTBAR[this.hot]
    if (pos.y < 0 || pos.y >= H || pos.x < 0 || pos.x >= W || pos.z < 0 || pos.z >= D) {
      this.effects.sound('deny')
      return
    }
    if (this.inv[this.hot] <= 0) {
      this.effects.sound('deny')
      this.effects.toast(`没有${blockName(blockId)}了:先去挖一点`)
      this.effects.announce(`没有${blockName(blockId)}了`)
      return
    }
    const existing = world.blockAt(pos.x, pos.y, pos.z)
    if (existing !== AIR && existing !== WATER) {
      this.effects.sound('deny')
      return
    }
    if (this.intersectsPlayer(pos.x, pos.y, pos.z)) {
      this.effects.sound('deny')
      this.effects.toast('这里放不下:会卡住自己')
      return
    }
    const result = world.setBlock(pos.x, pos.y, pos.z, blockId)
    if (result === 'ok') {
      this.worldDirty = true
      addStat(this.profile, 'placed', 1)
      this.inv[this.hot] = Math.max(0, this.inv[this.hot] - 1)
      this.streak = nextStreak(this.streak, true, false, true)
      this.spawnDust(pos.x, pos.y, pos.z, blockId)
      this.effects.sound('place', { material: blockMaterial(blockId) })
      this.effects.announce(`放了${blockName(blockId)}`)
      this.effects.markDirty('world')
      this.effects.markDirty('profile')
      this.checkAchievements()
      return
    }
    if (result === 'full') {
      this.effects.sound('full')
      this.effects.toast(`${TEXT.FULL_LIMIT}:${TEXT.FULL_HINT}`)
      this.effects.cleanupNeeded()
    } else if (result === 'bedrock' || result === 'outside') {
      this.effects.sound('deny')
    }
  }

  private spawnDust(x: number, y: number, z: number, blockId: number): void {
    const parts = spawnBreakParticles(x + 0.5, y + 0.5, z + 0.5, blockId, this.particleSeed++)
    this.particles = this.particles.concat(parts)
    if (this.particles.length > MAX_PARTICLES) this.particles.splice(0, this.particles.length - MAX_PARTICLES)
  }

  private intersectsPlayer(x: number, y: number, z: number): boolean {
    const p = this.player
    const half = 0.3
    const minX = p.x - half
    const maxX = p.x + half
    const minY = p.y
    const maxY = p.y + 1.8
    const minZ = p.z - half
    const maxZ = p.z + half
    return x + 1 > minX + 1e-4 && x < maxX - 1e-4 && y + 1 > minY + 1e-4 && y < maxY - 1e-4
      && z + 1 > minZ + 1e-4 && z < maxZ - 1e-4
  }

  private respawn(): void {
    const world = this.world
    if (!world) return
    placePlayer(world, this.player, world.spawn.x, world.spawn.y, world.spawn.z)
    this.player.yaw = world.yaw
    this.player.pitch = 0
    this.effects.sound('respawn')
    this.effects.announce('掉出世界了,回到出生点')
    this.effects.toast('掉出世界了,回到出生点')
  }

  // ---------------------------------------------------------------- 成就

  /** 当前成就判定上下文(面板显示进度也用) */
  achievementContext(): ReturnType<typeof emptyContext> {
    return {
      ...emptyContext(),
      y: this.player.y,
      maxY: this.maxY,
      biomeMask: this.biomeMask,
      inv: this.inv,
      streak: this.streak,
      nightMined: this.nightMined,
      swimSeconds: this.swimSeconds,
    }
  }

  checkAchievements(): void {
    const unlocked = checkAchievements(this.profile, this.achievementContext(), Date.now())
    if (!unlocked.length) return
    for (const def of unlocked) this.effects.achievement(def)
    this.effects.markDirty('profile')
  }

  // ---------------------------------------------------------------- 容量 / 清理

  /** 撤销最近一批改动;返回撤销条数。世界会立刻变化,主循环负责存档 */
  cleanupRecent(): number {
    const n = this.world ? this.world.revertRecent(LIMITS.CLEANUP_BATCH) : 0
    if (n > 0) {
      this.worldDirty = true
      this.target = null
      this.effects.sound('cleanup')
      this.effects.toast(`撤销了最近 ${n} 处改动`)
      this.effects.markDirty('world')
    }
    return n
  }

  /** 整座岛恢复成原始生成;返回清掉的改动数 */
  cleanupAll(): number {
    const n = this.world ? this.world.resetAll() : 0
    if (n > 0) {
      this.worldDirty = true
      this.target = null
      this.effects.sound('cleanup')
      this.effects.toast(`已把整座岛恢复成原始样子(清掉 ${n} 处改动)`)
      this.effects.announce('世界已恢复成原始小岛')
      this.effects.markDirty('world')
    }
    return n
  }

  // ---------------------------------------------------------------- 查询 / 存档

  selectSlot(i: number): boolean {
    if (i < 0 || i >= HOTBAR.length || i === this.hot) return false
    this.hot = i
    this.effects.sound('click', { vol: 0.5 })
    this.effects.announce(blockName(HOTBAR[this.hot]))
    return true
  }

  cycleSlot(dir: number): void {
    this.selectSlot((this.hot + (dir > 0 ? 1 : -1) + HOTBAR.length) % HOTBAR.length)
  }

  get stats(): GameStats {
    const world = this.world
    return {
      seed: world ? world.seed : 0,
      mined: this.profile.mined,
      placed: this.profile.placed,
      walked: this.profile.walked,
      seconds: this.profile.seconds,
      achievements: unlockedCount(this.profile),
      achievementsTotal: 13,
      edits: world ? world.editCount : 0,
      editRatio: world ? world.editRatio : 0,
      height: this.player.y,
      time: this.time,
    }
  }

  /** 存档快照(编辑串序列化在这里;4000 条排序只在存档时做) */
  snapshot(): GameSave {
    const world = this.world
    if (!world) throw new Error('没有世界可存档')
    return {
      v: 2,
      seed: world.seed,
      edits: world.serializeEdits(),
      player: {
        x: this.player.x, y: this.player.y, z: this.player.z,
        yaw: this.player.yaw, pitch: this.player.pitch,
      },
      time: this.time,
      inv: this.inv.slice(),
      hot: this.hot,
    }
  }

  /** 本轮有没有世界改动 / 档案改动待写(主循环取走并清零) */
  takeDirty(): { world: boolean; profile: boolean } {
    const out = { world: this.worldDirty, profile: this.profileDirty }
    this.worldDirty = false
    this.profileDirty = false
    return out
  }

  /** 主循环发现 world/profile 被外部改了(比如清理面板)时用 */
  markProfileDirty(): void {
    this.profileDirty = true
  }

  /** 夜里(光照最低)判断 */
  isNight(): boolean {
    return daylight(this.time) < DAY.NIGHT_LIGHT
  }

  private walkedReset(): void {
    this.stepAccum = 0
  }

  /** 当前位置能不能站(给测试/重生用) */
  feetBlock(): number {
    const world = this.world
    if (!world) return AIR
    return world.blockAt(Math.floor(this.player.x), Math.floor(this.player.y - 0.05), Math.floor(this.player.z))
  }

  /** 眼睛所在的方块(水下音效/画面染色用) */
  eyeBlock(): number {
    const world = this.world
    if (!world) return AIR
    const eye = cameraEye(this.player)
    return world.blockAt(Math.floor(eye.x), Math.floor(eye.y), Math.floor(eye.z))
  }

  get grounded(): boolean {
    return this.player.onGround
  }

  get eye(): { x: number; y: number; z: number } {
    return cameraEye(this.player)
  }

  /** 地形的材质(脚步音效用) */
  groundMaterial(): Material {
    return blockMaterial(this.feetBlock())
  }

  /** 出生点(测试/界面用) */
  spawn(): Spawn {
    const world = this.world
    return world ? world.spawn : { x: 64.5, y: 10, z: 64.5 }
  }
}
