// 星火牌局的全部内容数据:36 张可收集卡牌、1 张召唤物、3 位英雄和他们的 30 张预组卡组。
// 只有数据和查表函数,和界面无关。数值口径按费用走:1 费约 2/2,每多 1 费大约 +1/+1,
// 关键字(嘲讽 / 冲锋 / 圣盾 / 战吼 / 亡语)各算半费到一费。
//
// 世界观、卡名、文案全部原创,不使用任何商业卡牌游戏的角色、卡牌名和素材。
import type { CardDef, ClassId, Effect, HeroDef } from './types'

const C = (c: CardDef): CardDef => c

// ---------------------------------------------------------------- 卡牌

/** 可收集的卡一共 36 张;外加 1 张召唤物(灯苗) */
export const CARDS: readonly CardDef[] = [
  // ===== 中立 · 15 张(三套卡组都能带) =====
  C({ id: 'spark', name: '星火萤', cls: 'neutral', cost: 1, type: 'minion', attack: 1, health: 2, art: 'spark',
    text: '', flavor: '一小团赶夜路的光,落在谁肩上谁就暖和。' }),
  C({ id: 'swap', name: '换牌小贩', cls: 'neutral', cost: 1, type: 'minion', attack: 1, health: 1, art: 'swap',
    battlecry: { kind: 'draw', count: 1 }, text: '战吼:抽一张牌。', flavor: '旧牌换新牌,概不赊账。' }),
  C({ id: 'pebble', name: '碎岩兵', cls: 'neutral', cost: 2, type: 'minion', attack: 2, health: 3, taunt: true,
    art: 'rock', text: '嘲讽', flavor: '它往门口一站,连风都得绕着走。' }),
  C({ id: 'scout', name: '风哨斥候', cls: 'neutral', cost: 2, type: 'minion', attack: 3, health: 2, art: 'wind',
    text: '', flavor: '听见哨声的时候,她已经跑过三道街了。' }),
  C({ id: 'starling', name: '织星雀', cls: 'neutral', cost: 2, type: 'minion', attack: 2, health: 2, art: 'bird',
    battlecry: { kind: 'draw', count: 1 }, text: '战吼:抽一张牌。', flavor: '翅膀一抖,抖落一把会飞的纸片。' }),
  C({ id: 'medic', name: '铜药学徒', cls: 'neutral', cost: 3, type: 'minion', attack: 2, health: 3, art: 'vial',
    battlecry: { kind: 'heal', amount: 3 }, text: '战吼:为一个友方角色恢复 3 点生命。', flavor: '药不能停,账也不能停。' }),
  C({ id: 'guard', name: '守夜卫', cls: 'neutral', cost: 3, type: 'minion', attack: 2, health: 4, taunt: true,
    art: 'wall', text: '嘲讽', flavor: '整条街睡了,只有他的灯还亮着。' }),
  C({ id: 'herald', name: '星火传令官', cls: 'neutral', cost: 4, type: 'minion', attack: 4, health: 3, art: 'horn',
    battlecry: { kind: 'damage', amount: 2 }, text: '战吼:造成 2 点伤害。', flavor: '号角一响,星火顺着屋檐跑。' }),
  C({ id: 'twin', name: '双生灯灵', cls: 'neutral', cost: 3, type: 'minion', attack: 3, health: 3, art: 'twins',
    deathrattle: { kind: 'summon', card: 'wisp', count: 1 }, text: '亡语:召唤一个 1/1 的灯苗。', flavor: '一盏灭了,另一盏会亮起来。' }),
  C({ id: 'shell', name: '光壳侍从', cls: 'neutral', cost: 4, type: 'minion', attack: 3, health: 3, shield: true,
    art: 'shield', text: '圣盾', flavor: '壳很薄,但那一下它替你挡了。' }),
  C({ id: 'warhammer', name: '陨铁战锤', cls: 'neutral', cost: 5, type: 'minion', attack: 4, health: 3, charge: true,
    art: 'hammer', text: '冲锋', flavor: '从天外掉下来的时候,还是热的。' }),
  C({ id: 'owl', name: '夜巡枭', cls: 'neutral', cost: 3, type: 'minion', attack: 2, health: 2, art: 'owl',
    battlecry: { kind: 'buffSelf', attack: 2, health: 1 }, text: '战吼:获得 +2/+1。', flavor: '它不叫,只是盯着你看。' }),
  C({ id: 'cart', name: '旧货车', cls: 'neutral', cost: 5, type: 'minion', attack: 4, health: 5, taunt: true,
    art: 'cart', text: '嘲讽', flavor: '轮子有点歪,堵路正好。' }),
  C({ id: 'doom', name: '收灯人', cls: 'neutral', cost: 5, type: 'minion', attack: 5, health: 4, art: 'lantern',
    deathrattle: { kind: 'aoe', amount: 1 }, text: '亡语:对所有敌方随从造成 1 点伤害。', flavor: '灯灭之后,他才开始数数。' }),
  C({ id: 'giant', name: '星岩巨像', cls: 'neutral', cost: 8, type: 'minion', attack: 8, health: 8, taunt: true,
    art: 'giant', text: '嘲讽', flavor: '它坐下来的时候,整片星图晃了一下。' }),

  // ===== 熔火工坊 · 7 张 =====
  C({ id: 'f_ember', name: '火舌学徒', cls: 'forge', cost: 1, type: 'minion', attack: 2, health: 1, art: 'flame',
    battlecry: { kind: 'damage', amount: 1 }, text: '战吼:造成 1 点伤害。', flavor: '师傅说别玩火;师傅的眉毛就是证据。' }),
  C({ id: 'f_ash', name: '烬火傀儡', cls: 'forge', cost: 3, type: 'minion', attack: 3, health: 2, art: 'ember',
    deathrattle: { kind: 'heroDamage', amount: 2 }, text: '亡语:对敌方英雄造成 2 点伤害。', flavor: '熄灭不是结束,是最后一把火。' }),
  C({ id: 'f_thrower', name: '烈焰投手', cls: 'forge', cost: 4, type: 'minion', attack: 3, health: 4, art: 'flame',
    battlecry: { kind: 'damage', amount: 2 }, text: '战吼:造成 2 点伤害。', flavor: '准头一般,热度满分。' }),
  C({ id: 'f_guard', name: '熔心卫士', cls: 'forge', cost: 4, type: 'minion', attack: 3, health: 5, taunt: true,
    art: 'wall', text: '嘲讽', flavor: '心脏是炉子,堵住门就是火墙。' }),
  C({ id: 'f_bolt', name: '燧石击', cls: 'forge', cost: 2, type: 'spell', art: 'orb',
    spell: { kind: 'damage', amount: 3 }, text: '造成 3 点伤害。', flavor: '两块石头,一下火星,足够了。' }),
  C({ id: 'f_rain', name: '赤焰雨', cls: 'forge', cost: 4, type: 'spell', art: 'flame',
    spell: { kind: 'aoe', amount: 2 }, text: '对所有敌方随从造成 2 点伤害。', flavor: '工坊上空的云,颜色不太对。' }),
  C({ id: 'f_giant', name: '熔火巨人', cls: 'forge', cost: 6, type: 'minion', attack: 6, health: 5, charge: true,
    art: 'giant', text: '冲锋', flavor: '它迈出一步,烟囱就少一根。' }),

  // ===== 霜林哨站 · 7 张 =====
  C({ id: 'r_sentry', name: '霜线哨兵', cls: 'frost', cost: 2, type: 'minion', attack: 1, health: 3, taunt: true,
    art: 'snow', text: '嘲讽', flavor: '站了一整个冬天,靴子冻在地上。' }),
  C({ id: 'r_medic', name: '雪羽医师', cls: 'frost', cost: 3, type: 'minion', attack: 2, health: 3, art: 'feather',
    battlecry: { kind: 'heal', amount: 4 }, text: '战吼:为一个友方角色恢复 4 点生命。', flavor: '雪落在伤口上,就不疼了。' }),
  C({ id: 'r_shell', name: '冰壳卫士', cls: 'frost', cost: 5, type: 'minion', attack: 4, health: 6, shield: true,
    art: 'shield', text: '圣盾', flavor: '壳是冰的,里面的心是热的。' }),
  C({ id: 'r_ring', name: '霜环术', cls: 'frost', cost: 4, type: 'spell', art: 'ring',
    spell: { kind: 'aoe', amount: 2 }, text: '对所有敌方随从造成 2 点伤害。', flavor: '一圈白线落下,脚步声就停了。' }),
  C({ id: 'r_bless', name: '凛冬祝福', cls: 'frost', cost: 2, type: 'spell', art: 'winter',
    spell: { kind: 'buff', attack: 2, health: 2 }, text: '使一个友方随从获得 +2/+2。', flavor: '冬天不只会带走东西,也会留下东西。' }),
  C({ id: 'r_spring', name: '雪泉之息', cls: 'frost', cost: 2, type: 'spell', art: 'vial',
    spell: { kind: 'heal', amount: 6 }, text: '为一个友方角色恢复 6 点生命。', flavor: '泉眼在冰层下面,一直没有停。' }),
  C({ id: 'r_watch', name: '永冻守望', cls: 'frost', cost: 7, type: 'minion', attack: 7, health: 7, taunt: true,
    art: 'winter', text: '嘲讽', flavor: '守望的意思就是:它还在,路就不通。' }),

  // ===== 暮影集市 · 7 张 =====
  C({ id: 's_thief', name: '影巷小贼', cls: 'dusk', cost: 1, type: 'minion', attack: 2, health: 1, art: 'dagger',
    text: '', flavor: '她只偷两样东西:钱,和时间。' }),
  C({ id: 's_lamp', name: '提灯人', cls: 'dusk', cost: 2, type: 'minion', attack: 1, health: 2, art: 'lantern',
    deathrattle: { kind: 'summon', card: 'wisp', count: 1 }, text: '亡语:召唤一个 1/1 的灯苗。', flavor: '灯交出去,路就交给别人了。' }),
  C({ id: 's_merchant', name: '夜市商人', cls: 'dusk', cost: 3, type: 'minion', attack: 2, health: 3, art: 'coin',
    battlecry: { kind: 'draw', count: 1 }, text: '战吼:抽一张牌。', flavor: '买什么?不买也进来看看。' }),
  C({ id: 's_dancer', name: '影舞者', cls: 'dusk', cost: 3, type: 'minion', attack: 3, health: 2, charge: true,
    art: 'swirl', text: '冲锋', flavor: '你别眨眼,眨眼她就到身后了。' }),
  C({ id: 's_ambush', name: '暗巷伏击', cls: 'dusk', cost: 2, type: 'spell', art: 'dagger',
    spell: { kind: 'damage', amount: 3 }, text: '造成 3 点伤害。', flavor: '巷子拐角那一下,总是最凉。' }),
  C({ id: 's_memory', name: '星屑追忆', cls: 'dusk', cost: 4, type: 'spell', art: 'star',
    spell: { kind: 'draw', count: 2 }, text: '抽两张牌。', flavor: '记不住的,星星替你记。' }),
  C({ id: 's_lord', name: '暮影领主', cls: 'dusk', cost: 6, type: 'minion', attack: 5, health: 6, art: 'crown',
    battlecry: { kind: 'summon', card: 'wisp', count: 2 }, text: '战吼:召唤两个 1/1 的灯苗。', flavor: '整条集市的灯,都是他的眼睛。' }),

  // ===== 召唤物(不进卡组) =====
  C({ id: 'wisp', name: '灯苗', cls: 'neutral', cost: 1, type: 'minion', attack: 1, health: 1, art: 'spark',
    token: true, text: '', flavor: '谁提着它,它就替谁照路。' }),
]

const CARD_BY_ID = new Map<string, CardDef>(CARDS.map((c) => [c.id, c]))

/** 查一张卡;查不到就是数据有错(存档读取会先用 cardOrNull 过滤) */
export function card(id: string): CardDef {
  const c = CARD_BY_ID.get(id)
  if (!c) throw new Error(`没有这张卡:${id}`)
  return c
}

/** 查一张卡,查不到返回 null(读坏档用) */
export function cardOrNull(id: unknown): CardDef | null {
  return typeof id === 'string' ? CARD_BY_ID.get(id) || null : null
}

/** 这张卡是不是随从 */
export function isMinion(c: CardDef): boolean {
  return c.type === 'minion'
}

/** 出这张牌要不要选目标;要的话是哪种目标 */
export function targetKindOf(c: CardDef): 'none' | 'enemy' | 'friendly' | 'friendlyMinion' {
  const e: Effect | undefined = c.type === 'spell' ? c.spell : c.battlecry
  if (!e) return 'none'
  switch (e.kind) {
    case 'damage': return 'enemy'
    case 'heal': return 'friendly'
    case 'buff': return 'friendlyMinion'
    default: return 'none'
  }
}

/** 卡面上的关键字徽章 */
export function keywordsOf(c: CardDef): string[] {
  const out: string[] = []
  if (c.taunt) out.push('嘲讽')
  if (c.charge) out.push('冲锋')
  if (c.shield) out.push('圣盾')
  if (c.battlecry) out.push('战吼')
  if (c.deathrattle) out.push('亡语')
  if (c.type === 'spell') out.push('法术')
  return out
}

// ---------------------------------------------------------------- 英雄与预组卡组

/** 卡组:7 张职业卡 ×2 + 8 张中立卡 ×2 = 30 张(同一张最多 2 份) */
function deck(cls: ClassId, neutrals: string[]): string[] {
  const cards = CARDS.filter((c) => c.cls === cls && !c.token).map((c) => c.id)
  const out: string[] = []
  for (const id of cards) out.push(id, id)
  for (const id of neutrals) out.push(id, id)
  return out
}

export const HEROES: readonly HeroDef[] = [
  {
    id: 'forge',
    name: '炉心·赤铜',
    title: '熔火工坊',
    cls: 'forge',
    style: '快攻 · 直伤',
    desc: '学徒、投手和冲锋巨人轮番压上,趁对面还没站稳就把火点到英雄脸上。',
    art: 'hammer',
    deck: deck('forge', ['spark', 'swap', 'pebble', 'scout', 'medic', 'herald', 'warhammer', 'shell']),
  },
  {
    id: 'frost',
    name: '霜羽·岚',
    title: '霜林哨站',
    cls: 'frost',
    style: '防守 · 消耗',
    desc: '嘲讽、圣盾和治疗把场面拖住,等对面牌打完,再用守望和巨像一步步推过去。',
    art: 'snow',
    deck: deck('frost', ['spark', 'pebble', 'guard', 'medic', 'cart', 'starling', 'shell', 'giant']),
  },
  {
    id: 'dusk',
    name: '夜眼·鸦',
    title: '暮影集市',
    cls: 'dusk',
    style: '铺场 · 换牌',
    desc: '灯苗和抽牌滚起场面,小贼和舞者换掉对方的大个子,领主收尾。',
    art: 'moon',
    deck: deck('dusk', ['swap', 'scout', 'starling', 'twin', 'owl', 'doom', 'herald', 'cart']),
  },
]

const HERO_BY_ID = new Map<string, HeroDef>(HEROES.map((h) => [h.id, h]))

export function hero(id: string): HeroDef {
  const h = HERO_BY_ID.get(id)
  if (!h) throw new Error(`没有这个英雄:${id}`)
  return h
}

export function heroOrNull(id: unknown): HeroDef | null {
  return typeof id === 'string' ? HERO_BY_ID.get(id) || null : null
}

/** 玩家选卡组界面用:英雄按固定顺序 */
export function heroList(): readonly HeroDef[] {
  return HEROES
}

/** 阵营名(界面上给卡牌配色/说明用) */
export const CLASS_NAME: Record<ClassId, string> = {
  neutral: '中立',
  forge: '熔火工坊',
  frost: '霜林哨站',
  dusk: '暮影集市',
}

export const CLASS_COLOR: Record<ClassId, string> = {
  neutral: '#A8A29A',
  forge: '#D8623A',
  frost: '#4E8FB8',
  dusk: '#7A5FA8',
}

/** 卡组里每张牌有几份 */
export function copiesIn(deckList: readonly string[], id: string): number {
  return deckList.filter((x) => x === id).length
}
