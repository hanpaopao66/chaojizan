// 方块原野的数值、文案、调色板集中地(GAME-STANDARD §2:所有数值集中在数据文件,
// 逻辑代码里不出现魔法数)。
//
// 这里只放数据和类型,不放逻辑 —— 逻辑在 worldgen / world / player / interaction / gameplay 里。
// 调手感、调难度、调画面、调音量都改这一个文件;改完跑 `npm run test:sandbox` 和 typecheck。

// ---------------------------------------------------------------- 方块

export const AIR = 0
export const GRASS = 1
export const DIRT = 2
export const STONE = 3
export const SAND = 4
export const WATER = 5
export const LOG = 6
export const LEAVES = 7
export const PLANKS = 8
export const GLASS = 9
export const BRICK = 10
/** 世界最底下两层,挖不动,保证不会掉出世界 */
export const BEDROCK = 11

/** 脚步/挖放音效按材质分类 */
export type Material = 'grass' | 'dirt' | 'stone' | 'sand' | 'wood' | 'leaves' | 'glass' | 'brick' | 'water'

export interface BlockDef {
  id: number
  /** 界面和提示里显示的名字 */
  name: string
  /** 有没有碰撞(水没有:可以走进去游泳) */
  solid: boolean
  /** 挖穿需要按住多少秒(空手);Infinity = 挖不动 */
  hardness: number
  /** 音效和粒子用的材质 */
  material: Material
  /** 挖碎时飞出的粒子颜色(RGB 0–255) */
  dust: readonly [number, number, number]
}

/** 方块表:下标就是编号。编号写进存档,不要改已有的编号,新方块只能往后加。 */
export const BLOCKS: readonly BlockDef[] = [
  { id: AIR, name: '空气', solid: false, hardness: Infinity, material: 'stone', dust: [0, 0, 0] },
  { id: GRASS, name: '草方块', solid: true, hardness: 0.35, material: 'grass', dust: [96, 168, 60] },
  { id: DIRT, name: '泥土', solid: true, hardness: 0.4, material: 'dirt', dust: [138, 96, 56] },
  { id: STONE, name: '石头', solid: true, hardness: 0.85, material: 'stone', dust: [138, 138, 143] },
  { id: SAND, name: '沙子', solid: true, hardness: 0.3, material: 'sand', dust: [232, 216, 160] },
  { id: WATER, name: '水', solid: false, hardness: Infinity, material: 'water', dust: [64, 120, 180] },
  { id: LOG, name: '木头', solid: true, hardness: 0.75, material: 'wood', dust: [110, 75, 42] },
  { id: LEAVES, name: '树叶', solid: true, hardness: 0.12, material: 'leaves', dust: [76, 138, 52] },
  { id: PLANKS, name: '木板', solid: true, hardness: 0.55, material: 'wood', dust: [185, 139, 84] },
  { id: GLASS, name: '玻璃', solid: true, hardness: 0.22, material: 'glass', dust: [196, 236, 242] },
  { id: BRICK, name: '砖', solid: true, hardness: 0.9, material: 'brick', dust: [164, 72, 58] },
  { id: BEDROCK, name: '基岩', solid: true, hardness: Infinity, material: 'stone', dust: [74, 74, 82] },
]

/** 快捷栏里的九种方块(正好 1–9 九个数字键) */
export const HOTBAR: readonly number[] = [GRASS, DIRT, STONE, SAND, LOG, LEAVES, PLANKS, GLASS, BRICK]

/**
 * 新世界的初始物资:只送木板/玻璃/砖(自然世界里挖不到的三种),
 * 草/土/石/沙/木/叶要自己挖 —— 这样「满热栏」成就才有意义,开局也有材料可搭。
 */
export const STARTER_COUNTS: readonly number[] = [0, 0, 0, 0, 0, 0, 8, 6, 6]

// ---------------------------------------------------------------- 世界

export const WORLD = {
  W: 128,
  D: 128,
  H: 48,
  /** 海平面:y < SEA_LEVEL 的格子才可能装水,水面在这个高度 */
  SEA_LEVEL: 10,
  /** 最底下多少层是基岩 */
  BEDROCK_LAYERS: 2,
} as const

export const TERRAIN = {
  /** 岛的椭圆半径(x / z 方向),归一化距离 1 附近就是海岸 */
  ISLAND_RX: 60,
  ISLAND_RZ: 64,
  /** 噪声扰动海岸线的幅度 */
  EDGE_WARP: 0.55,
  /** 陆地系数:edge 在 [LAND_LO, LAND_HI] 之间从 1 渐变到 0 */
  LAND_LO: 0.45,
  LAND_HI: 1.02,
  /** 海床高度 = SEA_LEVEL - BASE_DROP,再按陆地系数抬升 */
  BASE_DROP: 6,
  LAND_HEIGHT: 11,
  BIG_AMP: 9,
  DETAIL_AMP: 5,
  /** 内陆石丘:细节噪声超过 RIDGE_START 的部分按 RIDGE_AMP 抬高 */
  RIDGE_START: 0.54,
  RIDGE_AMP: 24,
  RIDGE_LO: 0.55,
  RIDGE_HI: 0.95,
  /** 地形高度夹在 [MIN_HEIGHT, H - MAX_HEIGHT_MARGIN] */
  MIN_HEIGHT: 2,
  MAX_HEIGHT_MARGIN: 12,
  /** 地表:水下/岸边是沙,高处带一定随机才露石头 */
  BEACH_TOP: 1,
  SAND_DEPTH: 2,
  ROCK_TOP_HEIGHT: 21,
  ROCK_NOISE: 0.45,
} as const

export const TREE = {
  /** 每列长出树的概率(还要过间距和坡度检查) */
  DENSITY: 0.05,
  TRUNK_MIN: 4,
  TRUNK_MAX: 6,
  /** 树和树之间至少隔几格(占位半径) */
  SPACING_RADIUS: 2,
  /**
   * 出生点周围这个半径(平方)内不种树。数值是 **1.0.0 发布版定的 18**:
   * 这一句会跳过 rand 消耗,改了会把整条 RNG 流挪位 —— 同一 seed 的树全变,
   * 旧档里树屋/树旁的建筑会悬空或卡进树里。golden 回归测试守着这个值。
   */
  SPAWN_CLEAR_SQ: 18,
  /** 坡度过陡不长树:四邻高差和上限 */
  SLOPE_MAX: 3,
  /** 最小生长高度:高于海平面多少格 */
  MIN_ABOVE_SEA: 2,
  /** 树冠:下面几层半径 1,上面半径 2 */
  CANOPY_LOW_RADIUS: 1,
  CANOPY_HIGH_RADIUS: 2,
  CANOPY_CORNER_SKIP: 0.55,
} as const

export const SPAWN = {
  /** 从岛心往外最多找多远 */
  MAX_RADIUS: 52,
  /** 优先低处的海岸草原(视野好、走几步就能下水) */
  LOW_ALTITUDE: 7,
  /** 身边 5×5 的地形高差上限 */
  FLAT_DIFF: 1,
  /** 找出生点的四轮放宽顺序里的轮数 */
  PASSES: 4,
} as const

// ---------------------------------------------------------------- 玩家与手感

export const PLAYER = {
  WIDTH: 0.6,
  HEIGHT: 1.8,
  EYE_HEIGHT: 1.62,
} as const

export const FEEL = {
  GRAVITY: 27,
  JUMP_SPEED: 8.4,
  WALK_SPEED: 4.6,
  /** 空中水平加速占地面加速的比例 */
  AIR_CONTROL: 0.35,
  /** 水平速度趋近目标速度的速率(1/s) */
  ACCEL: 18,
  MAX_FALL: 48,
  WATER_GRAVITY: 6,
  WATER_MAX_FALL: 3.2,
  SWIM_UP: 2.8,
  WATER_SPEED: 2.4,
  WATER_DRAG: 1.2,
  /** 站在地上时自动迈上去的高度(方块单位) */
  STEP_HEIGHT: 1,
  /** 离开地面后还能跳的宽限时间(秒) */
  COYOTE_TIME: 0.1,
  /** 落地前按跳的缓冲时间(秒) */
  JUMP_BUFFER: 0.12,
  /** 一次移动最多分几步(防穿模) */
  MAX_SUBSTEP: 0.4,
  /** 碰撞 / 落地用的容差 */
  EPS: 1e-4,
  GROUND_SNAP: 1e-3,
  /** 俯仰限幅(弧度,约 74°):y-shear 投影在接近垂直时会拉伸,限制一下更稳 */
  PITCH_LIMIT: 1.3,
  /** 两次放置之间的冷却(秒) */
  PLACE_COOLDOWN: 0.12,
  /** 水里挖方块慢多少倍 */
  MINE_WATER_FACTOR: 1.35,
  /** 按住挖时「沙沙」声的间隔(秒) */
  MINE_SOUND_INTERVAL: 0.2,
  /** 挖掘进度条显示的阈值 */
  MINE_BAR_MIN: 0.004,
  /** 走路响一声脚步需要走多远(格) */
  STEP_DISTANCE: 1.7,
  /** 键盘方向键转视角速度(弧度/秒) */
  KEY_LOOK_YAW: 1.9,
  KEY_LOOK_PITCH: 1.35,
  /** 一帧 dt 上限(秒) */
  MAX_DT: 0.05,
  /** 掉出世界的判定高度 */
  VOID_Y: -6,
} as const

// ---------------------------------------------------------------- 画面

export const VIEW = {
  /** 水平视场角(度) */
  HFOV: 78,
  /** 最远看多少格;更远的用雾吃掉 */
  RENDER_DIST: 46,
  /** 一列最多经过多少格 */
  MAX_CELLS: 80,
  /** 内部缓冲目标像素数(乘以自适应画质系数) */
  TARGET_PIXELS: 100000,
  MAX_INTERNAL_W: 640,
  MIN_INTERNAL_W: 200,
  MIN_INTERNAL_H: 120,
  /** 自适应画质范围 */
  QUALITY_MIN: 0.5,
  QUALITY_STEP: 0.15,
  QUALITY_DOWN_MS: 24,
  QUALITY_UP_MS: 13,
  QUALITY_CHECK_FRAMES: 90,
  QUALITY_LOW: 0.5,
  /** 距离雾:从 RENDER_DIST 的 FOG_START 比例开始,到 FOG_END 结束 */
  FOG_START_RATIO: 0.62,
  FOG_END_RATIO: 1.05,
  UNDER_FOG_START: 1.5,
  UNDER_FOG_END: 15,
  /** 太阳/月亮的角半径(弧度) */
  SUN_RADIUS: 0.055,
  MOON_RADIUS_FACTOR: 0.72,
  /** 云层 / 星星:天空贴图尺寸 */
  CLOUD_W: 64,
  CLOUD_H: 32,
  CLOUD_DRIFT: 0.004,
  CLOUD_ALPHA: 0.55,
  STAR_ALPHA: 0.9,
  /** 水面波光、反射强度 */
  WATER_WAVE_SPEED: 1.6,
  WATER_WAVE_FREQ: 1.9,
  WATER_REFLECT: 0.5,
  WATER_ALPHA_MIN: 0.3,
  WATER_ALPHA_MAX: 0.82,
  WATER_ALPHA_BASE: 0.46,
  WATER_ALPHA_DEPTH: 0.2,
  /** 目标描边 */
  OUTLINE_WIDTH: 2,
  OUTLINE_GLOW_WIDTH: 4,
} as const

/** 渲染用的面编号:0 顶、1 底、2 x-、3 x+、4 z-、5 z+ */
export const FACE_TOP = 0
export const FACE_BOTTOM = 1
export const FACE_NEG_X = 2
export const FACE_POS_X = 3
export const FACE_NEG_Z = 4
export const FACE_POS_Z = 5

/** 六个面的基础明暗(顶最亮、底最暗)。阳光最多再加 0.16,总亮度压在 1.06 以内。 */
export const FACE_SHADE: readonly number[] = [0.92, 0.4, 0.7, 0.74, 0.82, 0.78]
/** 六个面的法线 */
export const FACE_NORMAL: ReadonlyArray<readonly [number, number, number]> = [
  [0, 1, 0], [0, -1, 0], [-1, 0, 0], [1, 0, 0], [0, 0, -1], [0, 0, 1],
]
/** 太阳方向对每个面的额外亮度 */
export const SUN_FACE_GAIN = 0.16
export const LIGHT_MAX = 1.06
export const AMBIENT_MAX = 1.02

/** 天空 / 昼夜 / 水面的调色板(RGB 0–255) */
export const PALETTE = {
  DAY_HORIZON: [196, 224, 242] as const,
  DAY_ZENITH: [70, 132, 202] as const,
  DAY_HAZE: [164, 192, 212] as const,
  DAY_FOG: [176, 204, 222] as const,
  NIGHT_HORIZON: [22, 32, 52] as const,
  NIGHT_ZENITH: [6, 9, 20] as const,
  NIGHT_HAZE: [16, 24, 40] as const,
  NIGHT_FOG: [20, 28, 44] as const,
  WARM: [255, 158, 100] as const,
  WARM_ZENITH: [120, 96, 150] as const,
  UNDER_FOG: [24, 62, 108] as const,
  UNDER_DEEP: [10, 34, 66] as const,
  WATER_DAY: [40, 94, 150] as const,
  WATER_NIGHT: [10, 24, 52] as const,
  CLOUD_DAY: [255, 255, 255] as const,
  CLOUD_NIGHT: [96, 116, 150] as const,
  NIGHT_AMBIENT: [0.34, 0.39, 0.5] as const,
  DAY_AMBIENT: [1, 1, 1] as const,
  WATER_UNDER_AMBIENT: [0.62, 0.8, 0.95] as const,
  SUN_CORE: [255, 232, 170] as const,
  SUN_CORE_NOON: [255, 250, 235] as const,
  SUN_GLOW: [255, 196, 120] as const,
  MOON_CORE: [226, 233, 246] as const,
  MOON_GLOW: [170, 196, 236] as const,
} as const

// ---------------------------------------------------------------- 昼夜

export const DAY = {
  /** 一轮多少秒(8 分钟) */
  SECONDS: 480,
  /** 新世界从早上开始(0 = 06:00) */
  START: 0.06,
  /** 夜里最亮时段:太阳方向亮度低于这个算夜 */
  NIGHT_LIGHT: 0.12,
  /** 亮度 / 暖色的平滑参数 */
  LIGHT_LO: -0.14,
  LIGHT_SPAN: 0.42,
  WARM_SPAN: 0.45,
} as const

// ---------------------------------------------------------------- 上限与节奏

export const LIMITS = {
  /** 稀疏编辑上限 */
  MAX_EDITS: 4000,
  /** 编辑串长度上限(UTF-8 字节) */
  MAX_EDITS_TEXT: 60000,
  /** 准星能够到几格 */
  REACH: 5,
  /** 改动到上限的多少比例开始提醒 */
  FULL_WARN_RATIO: 0.8,
  /** 点「清理」一次撤销最近多少处改动 */
  CLEANUP_BATCH: 100,
  /** 走动时多久存一次档(编辑是立刻存的) */
  SAVE_EVERY: 2.5,
  /** HUD 刷新间隔(秒) */
  HUD_EVERY: 0.12,
  /** 背包单格上限 */
  MAX_STACK: 9999,
  /** 成就检查间隔(秒) */
  ACHIEVE_CHECK: 0.4,
} as const

// ---------------------------------------------------------------- 音效

export const AUDIO = {
  MASTER: 0.5,
  SFX: 0.9,
  STEP: 0.5,
  AMBIENT: 0.2,
  /** 同时最多几个一发声部,超过就丢掉新的,避免挖矿连点时爆音 */
  MAX_VOICES: 14,
  /** 水下闷音的低通频率(Hz) */
  UNDERWATER_CUTOFF: 620,
  NORMAL_CUTOFF: 18000,
  /** 环境声:鸟 / 虫 / 风 */
  BIRD_VOL: 0.5,
  CRICKET_VOL: 0.4,
  WIND_VOL: 0.5,
  BIRD_GAP_MIN: 2600,
  BIRD_GAP_MAX: 7200,
  CRICKET_GAP_MIN: 1200,
  CRICKET_GAP_MAX: 3600,
} as const

/** 音效名字(和 audio.ts 的实现一一对应;gameplay 只依赖这个类型,不 import DOM) */
export type SoundName =
  | 'mine' | 'break' | 'place' | 'jump' | 'land' | 'step' | 'click' | 'deny'
  | 'splash' | 'respawn' | 'full' | 'achieve' | 'cleanup'

/** 音效选项:材质决定音色,vol 是这一声的相对音量 */
export interface SoundOptions {
  material?: Material
  vol?: number
}

// ---------------------------------------------------------------- 成就

/** 统计型成就用 profile 里的累计数字;条件型成就看运行时的状态(见 achievements.ts) */
export type AchievementStat = 'mined' | 'placed' | 'walked' | 'seconds'
export type AchievementCondition =
  | 'tower40' | 'biomes3' | 'streak50' | 'hotbarFull' | 'nightMine10' | 'swim10'

export interface AchievementDef {
  id: string
  name: string
  desc: string
  /** 面板上的单字图标(和官方图标的「一个字」风格一致) */
  icon: string
  /** 统计型成就的目标值;条件型为 1 */
  goal: number
  stat?: AchievementStat
  condition?: AchievementCondition
}

/** 13 个成就:开局引导 2 个、累计 7 个、探索/技巧 4 个 */
export const ACHIEVEMENTS: readonly AchievementDef[] = [
  { id: 'first_mine', name: '初次落铲', desc: '挖掉第一块方块', icon: '挖', goal: 1, stat: 'mined' },
  { id: 'first_place', name: '添砖加瓦', desc: '放下第一块方块', icon: '放', goal: 1, stat: 'placed' },
  { id: 'mine_100', name: '小有收获', desc: '累计挖掉 100 块方块', icon: '百', goal: 100, stat: 'mined' },
  { id: 'mine_1000', name: '愚公移山', desc: '累计挖掉 1000 块方块', icon: '山', goal: 1000, stat: 'mined' },
  { id: 'place_500', name: '建筑工人', desc: '累计放下 500 块方块', icon: '楼', goal: 500, stat: 'placed' },
  { id: 'walk_500', name: '环岛散步', desc: '累计走 500 米', icon: '步', goal: 500, stat: 'walked' },
  { id: 'time_30', name: '常来坐坐', desc: '累计在岛上待 30 分钟', icon: '时', goal: 1800, stat: 'seconds' },
  { id: 'tower40', name: '云端小屋', desc: '站到 40 格高(自己搭上去)', icon: '塔', goal: 1, condition: 'tower40' },
  { id: 'biomes3', name: '见多识广', desc: '踩过草地、沙滩、石地三种地形', icon: '野', goal: 1, condition: 'biomes3' },
  { id: 'streak50', name: '一口气', desc: '按住挖不松手,连续挖掉 50 块', icon: '气', goal: 1, condition: 'streak50' },
  { id: 'hotbar_full', name: '满载而归', desc: '九格快捷栏每格都有方块', icon: '满', goal: 1, condition: 'hotbarFull' },
  { id: 'night_mine10', name: '夜行者', desc: '在夜里挖掉 10 块方块', icon: '夜', goal: 1, condition: 'nightMine10' },
  { id: 'swim10', name: '水性不错', desc: '在水里连续待 10 秒', icon: '水', goal: 1, condition: 'swim10' },
]

/** 条件型成就的进度说明(面板里显示还差多少) */
export const ACHIEVEMENT_HINTS: Readonly<Record<string, string>> = {
  tower40: '往上搭方块,站到 y = 40',
  biomes3: '草地、沙滩、石地各走一走',
  streak50: '按住挖键,一口气挖 50 块',
  hotbarFull: '九种方块至少各挖/带一个',
  night_mine10: '天黑之后挖 10 块',
  swim10: '跳进水里待满 10 秒',
}

/** 清理面板里一次撤销多少格、以及「全部恢复」的说明文案 */
export const TEXT = {
  FULL_LIMIT: `改动已经到 ${LIMITS.MAX_EDITS} 格上限`,
  FULL_HINT: '可以撤销最近 100 处改动,或者把整座岛恢复成刚生成的样子(保留背包和位置)。',
  CLEANUP_RECENT: `撤销最近 ${LIMITS.CLEANUP_BATCH} 处改动`,
  CLEANUP_ALL: '恢复成原始小岛',
  FULL_WARN: '改动快满了',
} as const
