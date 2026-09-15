// 萌兽三路的全部内容数据:卡牌、塔、章节关卡、奖励表、成就。只有数据和查表函数,和界面无关。
//
// 数值口径:长度按「格」算(战场 9 格宽、14 格高),时间按秒。卡牌 1 级的数值写在这里,
// 每升一级生命、攻击、治疗、法术伤害 ×1.1(statMul)。

export type Side = 0 | 1 // 0 = 玩家(下方),1 = 电脑(上方)
export type CardKind = 'unit' | 'building' | 'spell'
export type ShotKind = 'pellet' | 'bolt' | 'arrow' | 'none'

export interface Pulse {
  /** 每隔几秒发作一次 */
  every: number
  radius: number
  damage?: number
  /** 定住多少秒 */
  stun?: number
}

export interface UnitStats {
  hp: number
  /** 每次攻击的伤害 */
  atk: number
  /** 两次攻击间隔(秒) */
  rate: number
  /** 攻击距离:自己边缘到目标边缘(格) */
  range: number
  /** 每秒走几格 */
  speed: number
  /** 占地半径(格),也决定画出来多大 */
  radius: number
  /** 飞在天上:只有能打空中的才打得到 */
  air?: boolean
  /** 能打空中目标(远程默认能) */
  hitsAir?: boolean
  /** 只打建筑(塔、大本营、建筑卡) */
  siege?: boolean
  /** 溅射半径 */
  splash?: number
  /** 一张卡出几只 */
  count?: number
  /** 远程的弹道 */
  shot?: ShotKind
  /** 冲锋:连续走 2 格后加速,下一击双倍 */
  charge?: boolean
  /** 扑击:离目标 2.5 格内直接跳过去,第一击双倍 */
  leap?: boolean
  /** 命中后减速(比例)1.5 秒 */
  slow?: number
  /** 命中后中毒,每秒伤害,持续 4 秒 */
  poison?: number
  /** 每秒给身边 2.2 格内的友军回血 */
  heal?: number
  /** 每秒给自己回血 */
  regen?: number
  /** 击退距离(格) */
  knock?: number
  /** 打出去的伤害按比例回血 */
  lifesteal?: number
  /** 周期性的范围伤害 / 定身 */
  pulse?: Pulse
  /** 建筑:存在几秒 */
  life?: number
  /** 建筑:每隔 every 秒生出一只 card */
  spawn?: { card: string; every: number }
}

export interface SpellStats {
  radius: number
  damage?: number
  /** 对塔只打这个比例 */
  towerPct?: number
  /** 冻住几秒(单位和塔都停手) */
  freeze?: number
  /** 两秒内回多少血 */
  heal?: number
  /** 鼓舞几秒:移动和攻击快 40% */
  rage?: number
}

export interface CardDef {
  id: string
  name: string
  kind: CardKind
  cost: number
  /** 画:动物的名字(units 图集里的键)或法术 / 建筑的图 */
  art: string
  /** 一句话说明 */
  desc: string
  /** 标签:近战 / 远程 / 飞行 / 攻城 / 群体 / 坦克 / 辅助 / 建筑 / 法术 */
  tags: string[]
  unit?: UnitStats
  spell?: SpellStats
  /** 只有电脑用(章节里的特色兵和 Boss),不进收藏 */
  aiOnly?: boolean
  boss?: boolean
}

// ---------------------------------------------------------------- 卡牌

const C: CardDef[] = [
  // —— 开局就有的 8 张
  { id: 'chick', name: '小鸡仔', kind: 'unit', cost: 2, art: 'chick', tags: ['近战', '群体'],
    desc: '一次出四只,跑得快、血很薄。人多势众,怕范围攻击。',
    unit: { hp: 70, atk: 28, rate: 1.0, range: 0.3, speed: 1.35, radius: 0.24, count: 4 } },
  { id: 'rabbit', name: '野兔', kind: 'unit', cost: 2, art: 'rabbit', tags: ['近战'],
    desc: '便宜又快,适合追着远程单位咬,或者去拆没人守的塔。',
    unit: { hp: 260, atk: 60, rate: 0.8, range: 0.35, speed: 1.6, radius: 0.32 } },
  { id: 'duck', name: '鸭子', kind: 'unit', cost: 2, art: 'duck', tags: ['远程'],
    desc: '在后排吐水泡,能打天上的。血薄,别让它站最前面。',
    unit: { hp: 170, atk: 50, rate: 1.1, range: 3.0, speed: 1.0, radius: 0.3, hitsAir: true, shot: 'pellet' } },
  { id: 'monkey', name: '猴子', kind: 'unit', cost: 3, art: 'monkey', tags: ['远程'],
    desc: '射程远的投手,能打天上的。躲在坦克后面最舒服。',
    unit: { hp: 320, atk: 75, rate: 1.2, range: 3.6, speed: 1.0, radius: 0.33, hitsAir: true, shot: 'pellet' } },
  { id: 'pig', name: '小猪', kind: 'unit', cost: 3, art: 'pig', tags: ['近战', '冲锋'],
    desc: '连着跑两格就冲起来,冲到跟前的第一下双倍伤害。',
    unit: { hp: 560, atk: 95, rate: 1.3, range: 0.35, speed: 0.95, radius: 0.36, charge: true } },
  { id: 'penguin', name: '企鹅', kind: 'unit', cost: 3, art: 'penguin', tags: ['近战'],
    desc: '滑得飞快,每一下都让对方减速,拖住冲过来的大家伙。',
    unit: { hp: 380, atk: 65, rate: 1.0, range: 0.35, speed: 1.5, radius: 0.33, slow: 0.35 } },
  { id: 'bear', name: '大熊', kind: 'unit', cost: 5, art: 'bear', tags: ['近战', '坦克'],
    desc: '血厚的前排,顶在前面给后面的远程挡伤害。',
    unit: { hp: 1900, atk: 125, rate: 1.5, range: 0.45, speed: 0.7, radius: 0.46 } },
  { id: 'fire', name: '火球', kind: 'spell', cost: 4, art: 'spell-fire', tags: ['法术'],
    desc: '在一小片地方炸开,烧掉扎堆的小兵;打塔只有三成伤害。',
    spell: { radius: 1.4, damage: 300, towerPct: 0.35 } },

  // —— 闯关解锁
  { id: 'fence', name: '木栅栏', kind: 'building', cost: 2, art: 'fence', tags: ['建筑'],
    desc: '往路上一插,地面的敌人得先把它拆了才过得去。只打建筑的也会被它吸引。',
    unit: { hp: 1300, atk: 0, rate: 1, range: 0, speed: 0, radius: 0.55, life: 25 } },
  { id: 'cow', name: '奶牛', kind: 'unit', cost: 4, art: 'cow', tags: ['近战', '辅助'],
    desc: '走到哪儿,身边的友军就回血到哪儿。',
    unit: { hp: 760, atk: 45, rate: 1.2, range: 0.4, speed: 0.8, radius: 0.42, heal: 35 } },
  { id: 'rage', name: '鼓舞', kind: 'spell', cost: 3, art: 'spell-rage', tags: ['法术'],
    desc: '范围内的友军 5 秒里移动和出手都快四成。',
    spell: { radius: 2.2, rage: 5 } },
  { id: 'coop', name: '鸡窝', kind: 'building', cost: 4, art: 'coop', tags: ['建筑', '群体'],
    desc: '每隔 4.5 秒孵出一只小鸡仔,能撑 30 秒。',
    unit: { hp: 850, atk: 0, rate: 1, range: 0, speed: 0, radius: 0.5, life: 30, spawn: { card: 'chick', every: 4.5 } } },
  { id: 'frog', name: '青蛙', kind: 'unit', cost: 3, art: 'frog', tags: ['近战'],
    desc: '看到 2.5 格内的敌人就扑过去,扑中的第一下双倍。',
    unit: { hp: 420, atk: 85, rate: 1.2, range: 0.4, speed: 1.05, radius: 0.34, leap: true } },
  { id: 'snake', name: '蛇', kind: 'unit', cost: 3, art: 'snake', tags: ['近战'],
    desc: '咬一口带毒,4 秒里慢慢掉血。专治血厚的。',
    unit: { hp: 320, atk: 45, rate: 1.0, range: 0.4, speed: 1.1, radius: 0.32, poison: 22 } },
  { id: 'heal', name: '回春', kind: 'spell', cost: 3, art: 'spell-heal', tags: ['法术', '辅助'],
    desc: '两秒里给范围内的友军回 420 点血(不回塔)。',
    spell: { radius: 2.0, heal: 420 } },
  { id: 'hippo', name: '河马', kind: 'unit', cost: 4, art: 'hippo', tags: ['近战', '范围'],
    desc: '一屁股坐下去砸一片,专治扎堆的小兵。',
    unit: { hp: 950, atk: 105, rate: 1.6, range: 0.45, speed: 0.7, radius: 0.45, splash: 1.0 } },
  { id: 'crocodile', name: '鳄鱼', kind: 'unit', cost: 5, art: 'crocodile', tags: ['近战'],
    desc: '一口咬得很重,出手慢。拿来对付大块头最划算。',
    unit: { hp: 1050, atk: 240, rate: 1.8, range: 0.45, speed: 0.8, radius: 0.44 } },
  { id: 'owl', name: '猫头鹰', kind: 'unit', cost: 4, art: 'owl', tags: ['飞行', '范围'],
    desc: '从天上俯冲,砸一小片。地上的近战够不着它。',
    unit: { hp: 520, atk: 115, rate: 1.5, range: 0.5, speed: 1.15, radius: 0.38, air: true, hitsAir: true, splash: 0.7 } },
  { id: 'freeze', name: '冰冻', kind: 'spell', cost: 3, art: 'spell-freeze', tags: ['法术'],
    desc: '范围内的敌人和塔冻住 3 秒,一动不动。',
    spell: { radius: 1.8, freeze: 3 } },
  { id: 'lookout', name: '瞭望台', kind: 'building', cost: 4, art: 'lookout', tags: ['建筑', '远程'],
    desc: '一座小塔,自己会射箭,能打天上的,撑 30 秒。',
    unit: { hp: 900, atk: 55, rate: 0.8, range: 4.5, speed: 0, radius: 0.5, life: 30, hitsAir: true, shot: 'arrow' } },
  { id: 'parrot', name: '鹦鹉', kind: 'unit', cost: 3, art: 'parrot', tags: ['飞行', '远程'],
    desc: '飞在天上啄人,地上的近战够不着它。',
    unit: { hp: 280, atk: 60, rate: 1.0, range: 2.6, speed: 1.35, radius: 0.33, air: true, hitsAir: true, shot: 'pellet' } },
  { id: 'giraffe', name: '长颈鹿', kind: 'unit', cost: 4, art: 'giraffe', tags: ['远程'],
    desc: '看得最远的狙击手,一发很疼,打得慢。',
    unit: { hp: 440, atk: 150, rate: 2.2, range: 5.0, speed: 0.8, radius: 0.38, hitsAir: true, shot: 'bolt' } },
  { id: 'elephant', name: '大象', kind: 'unit', cost: 7, art: 'elephant', tags: ['攻城', '坦克'],
    desc: '慢吞吞地走到塔下面,只拆建筑,一脚一个坑。',
    unit: { hp: 3400, atk: 270, rate: 2.0, range: 0.5, speed: 0.55, radius: 0.56, siege: true } },
  { id: 'gorilla', name: '大猩猩', kind: 'unit', cost: 6, art: 'gorilla', tags: ['近战', '范围', '坦克'],
    desc: '又能扛又能砸,一拳打一片。',
    unit: { hp: 2100, atk: 190, rate: 1.6, range: 0.5, speed: 0.72, radius: 0.5, splash: 1.2 } },
  { id: 'rhino', name: '犀牛', kind: 'unit', cost: 5, art: 'rhino', tags: ['攻城', '冲锋'],
    desc: '只盯着建筑冲,冲起来的第一下双倍。',
    unit: { hp: 1500, atk: 210, rate: 1.8, range: 0.45, speed: 0.9, radius: 0.46, siege: true, charge: true } },

  // —— 电脑的章节特色兵(不进收藏)
  { id: 'dog', name: '牧羊犬', kind: 'unit', cost: 3, art: 'dog', tags: ['近战'], aiOnly: true,
    desc: '牧场的看门狗,跑得快。',
    unit: { hp: 400, atk: 70, rate: 0.9, range: 0.35, speed: 1.5, radius: 0.34 } },
  { id: 'walrus', name: '海象', kind: 'unit', cost: 5, art: 'walrus', tags: ['近战', '坦克'], aiOnly: true,
    desc: '冰原上的大块头。',
    unit: { hp: 1600, atk: 115, rate: 1.5, range: 0.45, speed: 0.65, radius: 0.46 } },
  { id: 'narwhal', name: '独角鲸', kind: 'unit', cost: 4, art: 'narwhal', tags: ['近战', '冲锋'], aiOnly: true,
    desc: '顶着长角冲过来。',
    unit: { hp: 720, atk: 150, rate: 1.5, range: 0.4, speed: 1.0, radius: 0.4, charge: true } },
  { id: 'panda', name: '熊猫', kind: 'unit', cost: 5, art: 'panda', tags: ['近战', '坦克'], aiOnly: true,
    desc: '边打边嚼竹子,自己回血。',
    unit: { hp: 1450, atk: 105, rate: 1.4, range: 0.45, speed: 0.7, radius: 0.46, regen: 30 } },
  { id: 'sloth', name: '树懒', kind: 'unit', cost: 3, art: 'sloth', tags: ['近战'], aiOnly: true,
    desc: '慢,被它碰到也跟着变慢。',
    unit: { hp: 850, atk: 55, rate: 1.4, range: 0.4, speed: 0.55, radius: 0.4, slow: 0.5 } },
  { id: 'goat', name: '山羊', kind: 'unit', cost: 3, art: 'goat', tags: ['近战'], aiOnly: true,
    desc: '一头把人顶开。',
    unit: { hp: 600, atk: 90, rate: 1.3, range: 0.4, speed: 1.1, radius: 0.36, knock: 0.8 } },
  { id: 'horse', name: '野马', kind: 'unit', cost: 4, art: 'horse', tags: ['近战', '冲锋'], aiOnly: true,
    desc: '高原上的快马。',
    unit: { hp: 680, atk: 120, rate: 1.3, range: 0.4, speed: 1.4, radius: 0.4, charge: true } },

  // —— Boss(只在第五关出场)
  { id: 'buffalo', name: '野牛首领', kind: 'unit', cost: 7, art: 'buffalo', tags: ['Boss'], aiOnly: true, boss: true,
    desc: '牧场的老大,冲起来能把一排人顶飞。',
    unit: { hp: 2100, atk: 150, rate: 1.6, range: 0.5, speed: 0.85, radius: 0.62, charge: true, knock: 1.0 } },
  { id: 'crocking', name: '鳄鱼王', kind: 'unit', cost: 8, art: 'crocodile', tags: ['Boss'], aiOnly: true, boss: true,
    desc: '沼泽之主,咬到的血一半回到自己身上。',
    unit: { hp: 2400, atk: 240, rate: 1.8, range: 0.5, speed: 0.7, radius: 0.66, lifesteal: 0.5 } },
  { id: 'whale', name: '鲸王', kind: 'unit', cost: 8, art: 'whale', tags: ['Boss'], aiOnly: true, boss: true,
    desc: '每隔 5 秒掀起一圈浪,身边的人都挨一下。',
    unit: { hp: 2300, atk: 150, rate: 1.7, range: 0.55, speed: 0.5, radius: 0.72, splash: 1.3,
      pulse: { every: 5, radius: 2.0, damage: 80 } } },
  { id: 'gorking', name: '猩猩王', kind: 'unit', cost: 8, art: 'gorilla', tags: ['Boss'], aiOnly: true, boss: true,
    desc: '每隔 7 秒捶胸一吼,身边的人愣住一秒。',
    unit: { hp: 2200, atk: 190, rate: 1.6, range: 0.55, speed: 0.6, radius: 0.72, splash: 1.2,
      pulse: { every: 7, radius: 1.8, stun: 1.0 } } },
  { id: 'moose', name: '驼鹿王', kind: 'unit', cost: 9, art: 'moose', tags: ['Boss'], aiOnly: true, boss: true,
    desc: '高原之王,只冲建筑,冲起来谁也挡不住。',
    unit: { hp: 2800, atk: 230, rate: 2.0, range: 0.55, speed: 0.55, radius: 0.76, siege: true, charge: true, knock: 1.2 } },
]

export const CARDS: Record<string, CardDef> = Object.fromEntries(C.map((c) => [c.id, c]))
/** 收藏里的卡(按图鉴顺序) */
export const COLLECTION: string[] = C.filter((c) => !c.aiOnly).map((c) => c.id)
/** 开局就有的 8 张,也是第一套卡组 */
export const STARTERS = ['chick', 'rabbit', 'duck', 'monkey', 'pig', 'penguin', 'bear', 'fire']

export function card(id: string): CardDef {
  const c = CARDS[id]
  if (!c) throw new Error(`没有这张卡:${id}`)
  return c
}

// ---------------------------------------------------------------- 等级与升级

export const MAX_LEVEL = 10
/** 从 L 级升到 L+1 级要多少金币(下标是 L) */
export const UPGRADE_COST = [0, 30, 60, 100, 160, 240, 350, 500, 700, 950]

/** L 级的数值倍率 */
export function statMul(level: number): number {
  return Math.pow(1.1, Math.max(0, Math.min(MAX_LEVEL, level) - 1))
}

/** 升到 level 级一共花了多少金币 */
export function spentOn(level: number): number {
  let s = 0
  for (let l = 1; l < Math.min(level, MAX_LEVEL); l++) s += UPGRADE_COST[l]
  return s
}

// ---------------------------------------------------------------- 战场与塔

export const FIELD_W = 9
export const FIELD_H = 14
export const LANE_X = [1.6, 4.5, 7.4]
export const MID_Y = 7
/** 哨塔和大本营的 y:[玩家, 电脑] */
export const TOWER_Y: [number, number] = [10.85, 3.15]
export const BASE_Y: [number, number] = [13.2, 0.8]
/** 能出兵的范围(y):[玩家, 电脑] */
export const ZONE: [[number, number], [number, number]] = [[7.3, 13.4], [0.6, 6.7]]
/** 路的宽度的一半:同一路里的单位左右挪不出这个范围 */
export const LANE_HALF = 0.55

export interface TowerStats { hp: number; atk: number; rate: number; range: number; radius: number }
export const LANE_TOWER: TowerStats = { hp: 1400, atk: 52, rate: 0.8, range: 4.2, radius: 0.55 }
export const BASE_TOWER: TowerStats = { hp: 2400, atk: 70, rate: 1.0, range: 4.8, radius: 0.85 }

export const ENERGY_MAX = 10
/** 每秒回多少能量(1 点 2.8 秒) */
export const ENERGY_REGEN = 1 / 2.8
/** 击倒敌方单位返还的能量 = 这只单位的费用(一张卡出好几只的按只分摊)× 这个比例 */
export const REFUND_RATE = 0.25

// ---------------------------------------------------------------- 电脑

export interface AiParams {
  /** 每隔几秒想一次 */
  think: number
  /** 攒到多少能量才主动进攻 */
  reserve: number
  /** 发现威胁后过多久才反应(秒) */
  react: number
  /** 0–1:挑克制卡、挑落点的准确程度(剩下的随手出) */
  skill: number
  /** 进攻挑哪一路:平均轮着来 / 专打最弱的一路 / 死磕一路 */
  focus: 'split' | 'weak' | 'one'
  /** 0–1:用法术的积极程度 */
  spell: number
}

export const AI_EASY: AiParams = { think: 1.6, reserve: 8, react: 2.4, skill: 0.25, focus: 'split', spell: 0.2 }
export const AI_NORMAL: AiParams = { think: 1.1, reserve: 7, react: 1.4, skill: 0.55, focus: 'split', spell: 0.5 }
export const AI_HARD: AiParams = { think: 0.7, reserve: 6, react: 0.7, skill: 0.8, focus: 'weak', spell: 0.8 }
export const AI_BOSS: AiParams = { think: 0.6, reserve: 6.5, react: 0.6, skill: 0.85, focus: 'weak', spell: 0.9 }

// ---------------------------------------------------------------- 章节与关卡

export type Objective = 'siege' | 'defend' | 'blitz'
export type Theme = 'meadow' | 'swamp' | 'snow' | 'jungle' | 'highland'

/** 星级目标:赢 / 丢的哨塔不超过 n 座 / n 秒内赢 / 击倒至少 n 个敌方单位 */
export type Goal = { kind: 'win' } | { kind: 'lost'; n: number } | { kind: 'time'; n: number } | { kind: 'kills'; n: number }

export interface LevelDef {
  id: string
  chapter: number
  index: number
  name: string
  /** 关卡说明(一两句) */
  intro: string
  objective: Objective
  /** 速攻:要推倒几座塔(大本营算三座) */
  target?: number
  duration: number
  enemy: string[]
  enemyLevel: number
  ai: AiParams
  /** 能量回复倍率 [玩家, 电脑] */
  regen?: [number, number]
  startEnergy?: [number, number]
  /** 塔血倍率 [玩家, 电脑] */
  towerHp?: [number, number]
  /** 封掉的路(0 左 1 中 2 右):两边都不能在这一路出兵,这一路也没有哨塔 */
  closed?: number[]
  /** 冰面:所有单位移动快这么多 */
  speed?: number
  stars: [Goal, Goal, Goal]
  /** 第一次通关的奖励 */
  coins: number
  unlock?: string
  boss?: boolean
}

export interface ChapterDef { n: number; name: string; theme: Theme; blurb: string; boss: string }

export const CHAPTERS: ChapterDef[] = [
  { n: 1, name: '草地牧场', theme: 'meadow', blurb: '牧场里的小家伙们来切磋,先学会三路怎么守。', boss: 'buffalo' },
  { n: 2, name: '雾气沼泽', theme: 'swamp', blurb: '青蛙会扑、蛇会下毒,泥潭里的对手难缠。', boss: 'crocking' },
  { n: 3, name: '冰雪原野', theme: 'snow', blurb: '冰面上走得飞快,还有会冻人的法术。', boss: 'whale' },
  { n: 4, name: '深绿雨林', theme: 'jungle', blurb: '天上有鹦鹉,远处有长颈鹿,大象在后面慢慢推。', boss: 'gorking' },
  { n: 5, name: '风吹高原', theme: 'highland', blurb: '冲锋的野马和山羊,最后是驼鹿王。', boss: 'moose' },
]

const win: Goal = { kind: 'win' }
const lost = (n: number): Goal => ({ kind: 'lost', n })
const time = (n: number): Goal => ({ kind: 'time', n })
const kills = (n: number): Goal => ({ kind: 'kills', n })

type LevelSeed = Omit<LevelDef, 'id' | 'chapter' | 'index' | 'coins' | 'enemyLevel' | 'duration'> &
  Partial<Pick<LevelDef, 'duration'>>

const L: LevelSeed[][] = [
  [
    { name: '牧场初战', intro: '把手里的卡拖到下半场的路上就能出兵。推倒对面的大本营就赢。',
      objective: 'siege', enemy: ['chick', 'rabbit', 'duck', 'pig', 'chick', 'rabbit', 'duck', 'pig'],
      ai: AI_EASY, towerHp: [1, 0.85], stars: [win, lost(1), lost(0)], unlock: 'fence' },
    { name: '篱笆那头', intro: '对面学会了插栅栏。只拆建筑的兵会被栅栏吸过去。',
      objective: 'siege', enemy: ['chick', 'rabbit', 'duck', 'pig', 'fence', 'dog', 'duck', 'rabbit'],
      ai: { ...AI_EASY, reserve: 8.5, skill: 0.35, react: 2.0 }, stars: [win, lost(1), time(120)], unlock: 'cow' },
    { name: '左路塌方', intro: '左边的路塌了,只剩两路能走。',
      objective: 'siege', closed: [0], enemy: ['rabbit', 'pig', 'cow', 'duck', 'chick', 'fence', 'dog', 'pig'],
      ai: { ...AI_EASY, reserve: 8, skill: 0.4, react: 1.8 }, stars: [win, lost(0), kills(15)] },
    { name: '守住粮仓', intro: '对面能量回得快一半。守满 100 秒、大本营还在,就算赢。',
      objective: 'defend', duration: 100, regen: [1, 1.5], startEnergy: [7, 5],
      enemy: ['chick', 'rabbit', 'pig', 'dog', 'cow', 'duck', 'pig', 'rabbit'],
      ai: { ...AI_NORMAL, reserve: 5, skill: 0.4 }, stars: [win, lost(1), lost(0)], unlock: 'rage' },
    { name: '野牛首领', intro: 'Boss 关:野牛首领攒够能量就会上场,冲起来能顶飞一排。',
      objective: 'siege', boss: true, enemy: ['buffalo', 'chick', 'rabbit', 'pig', 'cow', 'duck', 'fence', 'dog'],
      ai: { ...AI_NORMAL, skill: 0.45 }, towerHp: [1, 1], stars: [win, lost(1), time(130)], unlock: 'coop' },
  ],
  [
    { name: '泥潭', intro: '青蛙看到人就扑,别让远程站得太靠前。',
      objective: 'siege', enemy: ['frog', 'frog', 'duck', 'snake', 'chick', 'rabbit', 'hippo', 'duck'],
      ai: AI_NORMAL, stars: [win, lost(1), lost(0)], unlock: 'frog' },
    { name: '蛇影', intro: '速攻:130 秒内推倒一座塔。',
      objective: 'blitz', target: 1, duration: 130, enemy: ['snake', 'snake', 'frog', 'duck', 'hippo', 'fence', 'pig', 'heal'],
      ai: { ...AI_NORMAL, skill: 0.35, reserve: 7.5 }, stars: [win, time(80), lost(0)], unlock: 'snake' },
    { name: '急救站', intro: '对面会用回春。开局你只有 3 点能量。',
      objective: 'siege', startEnergy: [3, 5], enemy: ['cow', 'heal', 'frog', 'snake', 'duck', 'hippo', 'rabbit', 'pig'],
      ai: { ...AI_NORMAL, spell: 0.8 }, stars: [win, lost(1), kills(20)], unlock: 'heal' },
    { name: '独木桥', intro: '只有中路能走,硬碰硬。',
      objective: 'siege', closed: [0, 2], enemy: ['hippo', 'frog', 'snake', 'duck', 'cow', 'fence', 'pig', 'chick'],
      ai: { ...AI_NORMAL, skill: 0.6 }, stars: [win, lost(0), time(110)], unlock: 'hippo' },
    { name: '鳄鱼王', intro: 'Boss 关:鳄鱼王咬一口回一半血,别跟它换血。',
      objective: 'siege', boss: true, enemy: ['crocking', 'frog', 'snake', 'duck', 'hippo', 'heal', 'fence', 'chick'],
      ai: { ...AI_NORMAL, skill: 0.6 }, towerHp: [1, 1], stars: [win, lost(1), time(130)], unlock: 'crocodile' },
  ],
  [
    { name: '冰面滑行', intro: '冰面上所有单位都走得快两成。',
      objective: 'siege', speed: 1.2, enemy: ['penguin', 'penguin', 'walrus', 'duck', 'rabbit', 'fire', 'narwhal', 'chick'],
      ai: AI_NORMAL, stars: [win, lost(1), lost(0)], unlock: 'owl' },
    { name: '寒潮', intro: '对面会冰冻,推进的时候别把兵全堆在一起。',
      objective: 'siege', enemy: ['freeze', 'walrus', 'penguin', 'monkey', 'narwhal', 'duck', 'owl', 'chick'],
      ai: { ...AI_NORMAL, spell: 0.9, skill: 0.6 }, stars: [win, lost(1), kills(20)], unlock: 'freeze' },
    { name: '雪夜守望', intro: '守满 120 秒、大本营还在就赢。对面能量回得快四成。',
      objective: 'defend', duration: 120, regen: [1, 1.4], startEnergy: [7, 6],
      enemy: ['walrus', 'narwhal', 'penguin', 'owl', 'freeze', 'monkey', 'duck', 'bear'],
      ai: { ...AI_NORMAL, reserve: 5.5, skill: 0.6 }, stars: [win, lost(1), lost(0)], unlock: 'lookout' },
    { name: '暴风雪', intro: '风雪太大,两边能量都回得慢两成。',
      objective: 'siege', regen: [0.8, 0.8], enemy: ['bear', 'walrus', 'owl', 'penguin', 'freeze', 'monkey', 'narwhal', 'fire'],
      ai: { ...AI_NORMAL, skill: 0.6, reserve: 6.5 }, stars: [win, lost(1), time(140)] },
    { name: '鲸王', intro: 'Boss 关:鲸王每 5 秒掀一圈浪,小兵别往它身边凑。',
      objective: 'siege', boss: true, speed: 1.1, enemy: ['whale', 'walrus', 'penguin', 'owl', 'freeze', 'monkey', 'narwhal', 'duck'],
      ai: { ...AI_NORMAL, skill: 0.65, reserve: 6.5 }, towerHp: [1, 1.05], stars: [win, lost(1), time(135)] },
  ],
  [
    { name: '树冠', intro: '天上的鹦鹉地面近战够不着,带上能打空中的。',
      objective: 'siege', enemy: ['parrot', 'parrot', 'monkey', 'sloth', 'snake', 'owl', 'panda', 'duck'],
      ai: AI_HARD, stars: [win, lost(1), lost(0)], unlock: 'parrot' },
    { name: '长颈瞭望', intro: '对面后排有长颈鹿,射得比塔还远。',
      objective: 'siege', enemy: ['giraffe', 'panda', 'monkey', 'parrot', 'sloth', 'fire', 'snake', 'fence'],
      ai: AI_HARD, stars: [win, lost(1), kills(22)], unlock: 'giraffe' },
    { name: '藤蔓陷阱', intro: '速攻:150 秒内推倒一座塔。对面守得很稳。',
      objective: 'blitz', target: 1, duration: 150, enemy: ['sloth', 'sloth', 'panda', 'giraffe', 'parrot', 'fence', 'monkey', 'heal'],
      ai: { ...AI_NORMAL, skill: 0.65 }, stars: [win, time(100), lost(0)] },
    { name: '象群', intro: '大象只拆建筑,拿栅栏和鳄鱼招呼它。',
      objective: 'siege', enemy: ['elephant', 'monkey', 'parrot', 'giraffe', 'panda', 'heal', 'snake', 'rage'],
      ai: { ...AI_HARD, reserve: 8 }, stars: [win, lost(1), time(130)], unlock: 'elephant' },
    { name: '猩猩王', intro: 'Boss 关:猩猩王一吼,身边的人都愣住。',
      objective: 'siege', boss: true, enemy: ['gorking', 'monkey', 'parrot', 'giraffe', 'panda', 'heal', 'snake', 'sloth'],
      ai: { ...AI_NORMAL, skill: 0.7, reserve: 6.5 }, towerHp: [1, 1.05], stars: [win, lost(1), time(135)], unlock: 'gorilla' },
  ],
  [
    { name: '风口', intro: '野马和山羊冲得快,前排要站得住。',
      objective: 'siege', enemy: ['horse', 'goat', 'horse', 'monkey', 'bear', 'fire', 'owl', 'goat'],
      ai: AI_HARD, stars: [win, lost(1), lost(0)], unlock: 'rhino' },
    { name: '山路', intro: '中路被石头堵死,只有两边能走。',
      objective: 'siege', closed: [1], enemy: ['rhino', 'goat', 'horse', 'giraffe', 'bear', 'freeze', 'owl', 'monkey'],
      ai: AI_HARD, stars: [win, lost(0), time(130)] },
    { name: '石堡', intro: '对面的塔加固过,血多四成;时间也长一些。',
      objective: 'siege', duration: 180, towerHp: [1, 1.4], enemy: ['elephant', 'goat', 'horse', 'monkey', 'giraffe', 'freeze', 'fire', 'panda'],
      ai: AI_HARD, stars: [win, lost(1), kills(25)] },
    { name: '最后防线', intro: '守满 120 秒、大本营还在就赢。对面能量回得快三成。',
      objective: 'defend', duration: 120, regen: [1, 1.3], startEnergy: [8, 6],
      enemy: ['rhino', 'horse', 'goat', 'gorilla', 'owl', 'fire', 'monkey', 'elephant'],
      ai: { ...AI_HARD, reserve: 6 }, stars: [win, lost(1), lost(0)] },
    { name: '驼鹿王', intro: '最终 Boss:驼鹿王只冲建筑,冲起来谁也挡不住。',
      objective: 'siege', boss: true, enemy: ['moose', 'horse', 'goat', 'giraffe', 'gorilla', 'freeze', 'fire', 'owl'],
      ai: { ...AI_BOSS, skill: 0.7 }, towerHp: [1, 1.1], stars: [win, lost(1), time(140)] },
  ],
]

/** 第一次通关的金币:章节越后越多,Boss 关另加 */
function firstCoins(chapter: number, index: number, boss: boolean): number {
  return 60 + 20 * (chapter - 1) + 10 * (index - 1) + (boss ? 60 : 0)
}

export const LEVELS: LevelDef[] = L.flatMap((list, ci) => list.map((s, li) => ({
  duration: 150,
  ...s,
  id: `${ci + 1}-${li + 1}`,
  chapter: ci + 1,
  index: li + 1,
  enemyLevel: ci + 1,
  coins: firstCoins(ci + 1, li + 1, !!s.boss),
})))

export const LEVEL_BY_ID: Record<string, LevelDef> = Object.fromEntries(LEVELS.map((l) => [l.id, l]))

/** 每颗星另给的金币(按章节) */
export function starCoins(chapter: number): number {
  return 10 + 5 * (chapter - 1)
}

/** 重复通关赢一局的金币 */
export function replayCoins(chapter: number, stars: number): number {
  return 15 + 5 * (chapter - 1) + 5 * stars
}

/** 每日挑战当天第一次赢的金币(没有连续登录奖励,哪天不玩也不亏什么) */
export const DAILY_COINS = 60
/** 每日挑战两边卡牌的固定等级 */
export const DAILY_LEVEL = 4

// ---------------------------------------------------------------- 成就

/** 成就的判定口径(progress.ts 按它算):累计数据 / 一局里的数据 / 存档里数出来的 */
export type AchMetric =
  | 'wins' | 'towers' | 'dailyWins' | 'bossWins'
  | 'stars' | 'threeStars' | 'cards' | 'maxLevel' | 'chapters'
  | 'bestKills' | 'bestRefund' | 'allLanes' | 'flawless'

export interface AchDef { id: string; name: string; desc: string; metric: AchMetric; n: number; coins: number }

export const ACHIEVEMENTS: AchDef[] = [
  { id: 'first', name: '初出茅庐', desc: '赢下第一局', metric: 'wins', n: 1, coins: 40 },
  { id: 'wins25', name: '身经百战', desc: '累计赢 25 局', metric: 'wins', n: 25, coins: 150 },
  { id: 'star3', name: '三星好评', desc: '在任意一关拿到三星', metric: 'threeStars', n: 1, coins: 50 },
  { id: 'stars30', name: '摘星能手', desc: '闯关累计 30 颗星', metric: 'stars', n: 30, coins: 150 },
  { id: 'stars75', name: '满天星', desc: '闯关拿满全部 75 颗星', metric: 'stars', n: 75, coins: 500 },
  { id: 'ch1', name: '牧场毕业', desc: '通过第一章', metric: 'chapters', n: 1, coins: 60 },
  { id: 'ch3', name: '踏雪而归', desc: '通过第三章', metric: 'chapters', n: 3, coins: 120 },
  { id: 'ch5', name: '高原之巅', desc: '通过全部五章', metric: 'chapters', n: 5, coins: 300 },
  { id: 'boss3', name: 'Boss 猎手', desc: '击败 3 个 Boss', metric: 'bossWins', n: 3, coins: 120 },
  { id: 'towers20', name: '拆迁队', desc: '累计推倒 20 座塔', metric: 'towers', n: 20, coins: 100 },
  { id: 'kills40', name: '以一当十', desc: '一局里击倒 40 个敌方单位', metric: 'bestKills', n: 40, coins: 100 },
  { id: 'refund12', name: '精打细算', desc: '一局里靠击倒返还 12 点能量', metric: 'bestRefund', n: 12, coins: 100 },
  { id: 'lanes', name: '三路开花', desc: '一局里把对面三路的哨塔都推倒', metric: 'allLanes', n: 1, coins: 100 },
  { id: 'flawless', name: '滴水不漏', desc: '赢下一局,自己一座塔都没丢', metric: 'flawless', n: 1, coins: 80 },
  { id: 'cards16', name: '小有收藏', desc: '解锁 16 张卡', metric: 'cards', n: 16, coins: 100 },
  { id: 'cardsAll', name: '全图鉴', desc: '解锁全部卡牌', metric: 'cards', n: COLLECTION.length, coins: 200 },
  { id: 'level5', name: '悉心栽培', desc: '把一张卡升到 5 级', metric: 'maxLevel', n: 5, coins: 100 },
  { id: 'daily1', name: '今日份挑战', desc: '赢下一次每日挑战', metric: 'dailyWins', n: 1, coins: 50 },
  { id: 'daily10', name: '常来常往', desc: '累计赢下 10 次每日挑战(不用连续)', metric: 'dailyWins', n: 10, coins: 150 },
]
