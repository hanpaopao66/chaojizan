// 星火牌局的公共类型与常量:卡牌 / 英雄的定义、对局状态、事件、动作。这里不碰界面,
// 规则(engine.ts)、电脑(ai.ts)和测试都只依赖它。
//
// 对局状态是一份 JSON 就能表达的数据:能整份写进存档、能原样读回来,测试里也能用 deepEqual 比较。
// 每次操作(clone → 改副本)返回新的一份,不改传进来的那一份(纯函数,方便单测和「关了再开」)。

export type Side = 0 | 1 // 0 = 玩家(下方),1 = 电脑(上方)
export type Level = 'normal' | 'hard'
export type ClassId = 'neutral' | 'forge' | 'frost' | 'dusk'
export type CardType = 'minion' | 'spell'

/** 卡面图案的键:art.ts 用程序化 SVG 画出来(没有任何外部图片) */
export type ArtKey =
  | 'flame' | 'ember' | 'hammer' | 'giant' | 'orb' // 熔火工坊
  | 'snow' | 'feather' | 'shield' | 'ring' | 'winter' | 'leaf' // 霜林哨站
  | 'dagger' | 'lantern' | 'coin' | 'crown' | 'swirl' | 'moon' // 暮影集市
  | 'spark' | 'rock' | 'wind' | 'bird' | 'vial' | 'wall' | 'horn' | 'twins' | 'cart' | 'owl' | 'star' | 'swap' // 中立

/** 卡牌效果。和界面无关;engine 里一个 applyEffect 按 kind 分发 */
export type Effect =
  /** 对指定的一个敌方角色造成伤害 */
  | { kind: 'damage'; amount: number }
  /** 对敌方所有随从造成伤害 */
  | { kind: 'aoe'; amount: number }
  /** 为一个指定的友方角色恢复生命 */
  | { kind: 'heal'; amount: number }
  /** 抽牌(手牌满了会烧掉) */
  | { kind: 'draw'; count: number }
  /** 使一个指定的友方随从获得 +攻击/+生命 */
  | { kind: 'buff'; attack: number; health: number }
  /** 自己获得 +攻击/+生命(随从的战吼用,不用选目标) */
  | { kind: 'buffSelf'; attack: number; health: number }
  /** 召唤随从到己方场上(场上满了就少召唤几只) */
  | { kind: 'summon'; card: string; count: number }
  /** 对敌方英雄造成伤害(亡语/战吼用,不用选目标) */
  | { kind: 'heroDamage'; amount: number }

export interface CardDef {
  id: string
  name: string
  /** 职业:中立卡三套卡组都能带;职业卡只能进对应英雄的卡组 */
  cls: ClassId
  cost: number
  type: CardType
  /** 随从的初始攻击 / 生命 */
  attack?: number
  health?: number
  /** 嘲讽:对面必须先打它 */
  taunt?: boolean
  /** 冲锋:上场当回合就能攻击 */
  charge?: boolean
  /** 圣盾:第一次受到伤害时免疫并破盾 */
  shield?: boolean
  /** 随从的战吼(从手里打出时触发) */
  battlecry?: Effect
  /** 随从的亡语(死亡结算时触发) */
  deathrattle?: Effect
  /** 法术效果 */
  spell?: Effect
  /** 卡面上写的规则文本 */
  text: string
  /** 风味文案(卡面下方的小字,纯装饰) */
  flavor: string
  /** 程序化卡面图案 */
  art: ArtKey
  /** 召唤物:不进卡组,也不能被合成(这里没有合成,只是数据自检时区分开) */
  token?: boolean
}

export interface HeroDef {
  id: string
  /** 英雄名 */
  name: string
  /** 阵营 / 卡组名 */
  title: string
  cls: ClassId
  /** 一句话打法 */
  style: string
  /** 卡组说明 */
  desc: string
  /** 程序化头像用的图案 */
  art: ArtKey
  /** 30 张卡的卡组(可以重复,但同一张最多 2 份) */
  deck: string[]
}

/** 指向一个角色:英雄或者场上的随从 */
export type TargetRef = { kind: 'hero'; side: Side } | { kind: 'minion'; side: Side; uid: number }

/** 流派生出来的一张随从(对局状态里存的是这一份,不是卡牌定义) */
export interface Minion {
  uid: number
  card: string
  attack: number
  health: number
  maxHealth: number
  taunt: boolean
  shield: boolean
  /** 召唤失调:刚上场、这回合不能攻击(冲锋除外) */
  sick: boolean
  /** 本回合还能攻击几次(0 或 1;没有风怒) */
  attacks: number
}

export interface SideState {
  hero: string
  hp: number
  /** 当前能量 */
  energy: number
  /** 本回合的能量上限(每回合 +1,最多 10) */
  maxEnergy: number
  /** 牌库,数组顺序就是抽牌顺序(存了一整份,读档不用重放随机数) */
  deck: string[]
  hand: string[]
  /** 场上随从,顺序决定界面从做到右;最多 7 个 */
  board: Minion[]
  /** 下一次疲劳伤害(抽空牌库后 1、2、3… 递增) */
  fatigue: number
  /** 这一局出了几张牌 */
  played: number
  /** 对敌方造成的总伤害(结算页用) */
  dealt: number
  /** 损失了几个随从 */
  lost: number
}

export type OverReason = 'hp' | 'fatigue' | 'quit'

export interface GameState {
  v: 1
  /** 开局的随机数种子(洗牌用;洗好的顺序已经存在 deck 里,种子也留着方便复现) */
  seed: number
  /** 第几回合(从 1 开始,双方各走一次算 +2) */
  turn: number
  /** 轮到谁 */
  active: Side
  sides: [SideState, SideState]
  /** 下一个随从的编号 */
  nextUid: number
  over: { winner: Side | -1; reason: OverReason } | null
}

export interface NewGameOptions {
  seed: number
  /** 玩家英雄(同时也是玩家的卡组) */
  hero0: string
  /** 电脑英雄 */
  hero1: string
  /** 先手,默认玩家先手 */
  first?: Side
}

/** 对局里发生的事。界面拿它放动画、播声音、读屏播报;测试拿它断言 */
export type Ev =
  | { e: 'turn'; side: Side; turn: number }
  | { e: 'draw'; side: Side; card: string }
  | { e: 'burn'; side: Side; card: string }
  | { e: 'fatigue'; side: Side; amount: number }
  | { e: 'play'; side: Side; card: string; target: TargetRef | null }
  | { e: 'summon'; side: Side; uid: number; card: string }
  | { e: 'attack'; side: Side; uid: number; target: TargetRef; toTarget: number; toSelf: number }
  | { e: 'damage'; target: TargetRef; amount: number; shielded: boolean }
  | { e: 'shield'; target: TargetRef }
  | { e: 'death'; side: Side; uid: number; card: string }
  | { e: 'heal'; target: TargetRef; amount: number }
  | { e: 'buff'; target: TargetRef; attack: number; health: number }
  | { e: 'over'; winner: Side | -1; reason: OverReason }

/** 一个可以执行的动作:出牌、攻击、结束回合 */
export type Action =
  | { kind: 'play'; hand: number; target: TargetRef | null }
  | { kind: 'attack'; uid: number; target: TargetRef }
  | { kind: 'end' }

/** 一个动作能不能做:能就是新状态 + 事件,不能就带一句人话的原因 */
export type ActionResult = { ok: true; state: GameState; events: Ev[] } | { ok: false; why: string }

/** 检查一个动作合不合法(界面和 AI 用) */
export interface Check {
  ok: boolean
  why: string
}

export const START_HP = 30
export const MAX_ENERGY = 10
export const MAX_HAND = 10
export const MAX_BOARD = 7
export const MAX_COPIES = 2
export const DECK_SIZE = 30

/** 对手 */
export const foe = (s: Side): Side => (s === 0 ? 1 : 0)
/** 人话里的「你 / 电脑」 */
export const who = (s: Side): string => (s === 0 ? '你' : '电脑')
