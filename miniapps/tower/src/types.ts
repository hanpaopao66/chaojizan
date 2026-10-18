// 瓜田防线的数据形状:塔、虫子、关卡、一局的状态、引擎事件。
// 这里只有类型和极小工具函数,不碰 DOM;数值都在 data.ts,规则在 engine.ts。

/** 三个主题场景:菜园白天 / 果园黄昏 / 虫巢月夜 */
export type Theme = 'garden' | 'orchard' | 'nest'

/** 七种塔 */
export type TowerKind = 'pea' | 'frost' | 'pepper' | 'vine' | 'mushroom' | 'bow' | 'marigold'

/** 八种虫 + Boss + 分裂蚁死后的小蚁(小蚁只在分裂时出现,不进波次) */
export type EnemyKind = 'worm' | 'flea' | 'beetle' | 'moth' | 'wasp' | 'pupa' | 'ant' | 'antling' | 'boss'

/** 网格坐标(列,行),左上角是 (0,0) */
export interface GridPoint {
  readonly c: number
  readonly r: number
}

/** 世界坐标(像素);地图固定 360×560 */
export interface Vec {
  x: number
  y: number
}

/** 塔一级的数值。没写的字段表示这一级没有这个能力 */
export interface TowerLevel {
  /** 单次伤害 */
  damage: number
  /** 每秒攻击次数 */
  rate: number
  /** 射程(格) */
  range: number
  /** 溅射半径(格) */
  splash?: number
  /** 链电最多连几个目标(不含主目标) */
  chain?: number
  /** 减速比例:0.3 = 速度 ×0.7 */
  slowFactor?: number
  /** 减速持续(秒) */
  slowDur?: number
  /** 命中时冻结概率 */
  freezeChance?: number
  /** 冻结时长(秒) */
  freezeDur?: number
  /** 毒每秒伤害(无视护甲) */
  poisonDps?: number
  /** 毒持续(秒) */
  poisonDur?: number
  /** 毒溅射半径(格):命中的目标周围都会中毒 */
  poisonRadius?: number
  /** 灼烧每秒伤害(无视护甲) */
  burnDps?: number
  burnDur?: number
  /** 一次打出几发(豆荚炮 3 级双发) */
  shots?: number
  /** 无视护甲(瓜藤弓 3 级穿甲) */
  pierce?: boolean
  /** 击杀时留下一片毒云(毒蘑菇 3 级) */
  deathCloud?: boolean
  /** 金盏花每波产出金币 */
  goldPerWave?: number
}

/** 一种塔的定义 */
export interface TowerDef {
  kind: TowerKind
  name: string
  /** 一句话定位(建造卡片上显示) */
  role: string
  /** 面板上的说明 */
  desc: string
  cost: number
  /** 升到 2 级 / 3 级的费用 */
  upgrade: readonly [number, number]
  levels: readonly [TowerLevel, TowerLevel, TowerLevel]
  /** 主题色(卡片、塔身、射程圈) */
  color: string
  /** 一眼能认出的轮廓名(render.ts 用) */
  shape: string
  /** 能不能打飞行虫(飞蛾/毒蜂)。豆荚炮、火焰椒、毒蘑菇只打地面 */
  air: boolean
}

/** 一种虫子的定义 */
export interface EnemyDef {
  kind: EnemyKind
  name: string
  hp: number
  /** 格/秒 */
  speed: number
  bounty: number
  /** 护甲:普通伤害每次先减这么多,最少 1 */
  armor: number
  /** 飞行:不走路,直线飞向西瓜 */
  flying: boolean
  /** 走到终点咬一口掉几点 HP */
  leak: number
  /** 治疗周围敌人(治疗蛹) */
  heal?: { rate: number; radius: number }
  /** 死亡分裂成几只小蚁 */
  split?: number
  /** 是不是 Boss(顶部常驻血条、红字播报) */
  boss?: boolean
  /** 画出来的半径(像素) */
  size: number
  color: string
}

/** 一波里的一组怪 */
export interface WaveGroup {
  kind: EnemyKind
  count: number
  /** 组内两只之间的间隔(秒) */
  gap: number
  /** 这一组相对本波开始的延迟(秒) */
  delay?: number
  /** 走哪条路(双入口关卡 0/1) */
  path?: number
}

/** 一波:若干组,外加这波之前的准备时间 */
export interface WaveDef {
  groups: WaveGroup[]
  /** 这波开始前的准备秒数(不写按 3 秒) */
  prep?: number
  /** 这波有 Boss(给界面用) */
  boss?: boolean
}

/** 关卡定义 */
export interface LevelDef {
  /** 关卡 id:1–12;无尽模式是 'endless' */
  id: number | 'endless'
  name: string
  theme: Theme
  /** 一局游戏开始前的大准备时间(秒) */
  firstPrep: number
  /** 大西瓜的 HP */
  goalHp: number
  startGold: number
  /** 每一关能用的塔(没有的塔在建造面板里显示成「第 N 关解锁」) */
  towers: readonly TowerKind[]
  /** 虫子走的路线(网格拐点,轴对齐),会补上西瓜中心作为终点 */
  paths: readonly (readonly GridPoint[])[]
  /** 建造位上限(从路线两侧自动铺开) */
  slotCap: number
  /** 波次;无尽模式这里留空,由 waves.ts 现场生成 */
  waves: readonly WaveDef[]
  /** 基准策略推荐先造的塔(也是新手提示的推荐塔;不强制) */
  recommend: readonly TowerKind[]
  /** 派生:路线的世界坐标(含西瓜中心) */
  world: PathInfo
  /** 派生:建造位(按能盖住的路面从多到少排) */
  slots: readonly GridPoint[]
  /** 派生:新手提示用,离入口最近的建造位下标 */
  hintSlot: number
}

/** 塔在场上的一份状态 */
export interface Tower {
  id: number
  kind: TowerKind
  /** 1–3 */
  level: 1 | 2 | 3
  /** 占用的建造位下标 */
  slot: number
  /** 冷却(秒) */
  cd: number
  /** 炮口朝向(弧度,渲染用) */
  aim: number
  /** 累计投入(卖出按 70% 返还) */
  invested: number
}

/** 虫子的一份状态 */
export interface Enemy {
  id: number
  kind: EnemyKind
  hp: number
  maxHp: number
  /** 沿路线走了多远(世界像素)。飞行虫是直线距离 */
  dist: number
  /** 这条命的总路程(到西瓜中心),用于算进度和漏怪 */
  span: number
  /** 走哪条路(0/1) */
  path: number
  /** 这几样是时间戳(秒):到这个时刻之前有效 */
  slowUntil: number
  slowFactor: number
  freezeUntil: number
  poisonUntil: number
  poisonDps: number
  burnUntil: number
  burnDps: number
  /** 受击闪白剩余时间(秒) */
  flash: number
}

/** 塔打出去的视觉弹道(引擎只为了存档/渲染记录一小段) */
export interface Shot {
  kind: TowerKind
  x: number
  y: number
  tx: number
  ty: number
  life: number
  max: number
}

/** 波次里排好的下一只怪 */
export interface Spawn {
  kind: EnemyKind
  /** 相对本波开始的时刻(秒) */
  at: number
  path: number
}

/** 一局的经济/战绩统计 */
export interface RunStats {
  kills: number
  bossKills: number
  leaks: number
  goldEarned: number
  built: number
  sold: number
  upgrades: number
  towers: TowerKind[]
}

/** 一局游戏的全部状态(可整份存进 SaveSlot) */
export interface GameState {
  v: 1
  levelId: number | 'endless'
  seed: number
  /** 随机数状态(mulberry32);只在引擎里推进 */
  rng: number
  gold: number
  hp: number
  maxHp: number
  /** 当前是第几波(1 开始;0 = 还没开始第一波) */
  wave: number
  phase: 'prep' | 'wave' | 'over'
  /** 准备倒计时(秒) */
  prep: number
  /** 本波已经进行了多久(秒) */
  clock: number
  spawns: Spawn[]
  enemies: Enemy[]
  towers: Tower[]
  shots: Shot[]
  nextId: number
  over: 'win' | 'lose' | null
  /** 胜利时的星级;输了是 0 */
  stars: number
  /** 这一局用的总时间(秒) */
  time: number
  /** 本波已经提前召唤过了吗 */
  summoned: boolean
  paused: boolean
  speed: 1 | 2
  endless: boolean
  /** 无尽模式当前最高波数(随波次推进) */
  stats: RunStats
  /** 固定步长累加器(advance 用) */
  acc: number
  /** 本波有没有 Boss(界面顶部血条) */
  bossWave: boolean
}

/** 引擎事件:界面拿它出声、飘字、播报 */
export type GameEvent =
  | { e: 'shot'; kind: TowerKind; from: Vec; to: Vec }
  | { e: 'chain'; points: Vec[] }
  | { e: 'boom'; kind: TowerKind; pos: Vec; radius: number }
  | { e: 'hit'; pos: Vec; amount: number; armor: boolean }
  | { e: 'kill'; pos: Vec; bounty: number; kind: EnemyKind }
  | { e: 'leak'; pos: Vec; amount: number; boss: boolean; kind: EnemyKind }
  | { e: 'gold'; amount: number; pos: Vec; why: 'kill' | 'wave' | 'early' | 'marigold' | 'sell' }
  | { e: 'wave'; wave: number }
  | { e: 'waveClear'; wave: number; reward: number; marigold: number }
  | { e: 'boss'; name: string }
  | { e: 'freeze'; pos: Vec }
  | { e: 'poison'; pos: Vec }
  | { e: 'burn'; pos: Vec }
  | { e: 'split'; pos: Vec }
  | { e: 'cloud'; pos: Vec; radius: number }
  | { e: 'build'; slot: number; kind: TowerKind }
  | { e: 'upgrade'; id: number }
  | { e: 'sell'; id: number }
  | { e: 'win'; stars: number }
  | { e: 'lose' }

/** 命令的结果:失败时带一句给玩家看的原因 */
export interface CommandResult {
  ok: boolean
  reason?: string
}

/** 引擎命令 */
export type Command =
  | { kind: 'build'; slot: number; tower: TowerKind }
  | { kind: 'upgrade'; id: number }
  | { kind: 'sell'; id: number }
  | { kind: 'summon' }
  | { kind: 'speed'; speed: 1 | 2 }
  | { kind: 'pause'; paused: boolean }

/** 路线的世界坐标信息(按关卡缓存,纯派生) */
export interface PathInfo {
  /** 每一段折线的点(世界坐标),最后一点是西瓜中心 */
  polys: Vec[][]
  /** 每一段折线的长度 */
  lens: number[]
  /** 每条路的入口点 */
  starts: Vec[]
  /** 西瓜中心 */
  target: Vec
}
