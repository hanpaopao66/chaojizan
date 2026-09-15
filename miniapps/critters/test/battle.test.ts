import assert from 'node:assert/strict'
import { test } from 'node:test'
import { MAX_UNITS, canPlay, forfeit, goalMet, loadBattle, newBattle, place, run, saveBattle, starsOf, step } from '../src/battle'
import {
  AI_HARD, AI_NORMAL, BASE_TOWER, BASE_Y, ENERGY_MAX, LANE_TOWER, LANE_X, STARTERS, TOWER_Y, ZONE, statMul,
} from '../src/data'
import { Battle, BattleConfig, Cmd, DT, baseOf, laneTower } from '../src/field'

const lv = (ids: string[], n = 1) => Object.fromEntries(ids.map((i) => [i, n]))

function cfg(over: Partial<BattleConfig> = {}): BattleConfig {
  return {
    seed: 1, duration: 150, objective: 'siege', target: 0,
    decks: [{ cards: STARTERS, levels: lv(STARTERS) }, { cards: STARTERS, levels: lv(STARTERS) }],
    ai: [null, null], regen: [1, 1], startEnergy: [5, 5], towerHp: [1, 1], towerLevel: [1, 1], closed: [], speed: 1,
    stars: [{ kind: 'win' }, { kind: 'lost', n: 1 }, { kind: 'lost', n: 0 }], tag: 'test', theme: 'meadow', ...over,
  }
}

/** 把手里第一张换成 id(测试直接改自己这份状态) */
function hand(b: Battle, side: 0 | 1, id: string, energy = ENERGY_MAX): Battle {
  const n: Battle = JSON.parse(JSON.stringify(b))
  n.sides[side].hand[0] = id
  n.sides[side].energy = energy
  return n
}

const cmd = (b: Battle, side: 0 | 1, slot: number, x: number, y: number): Cmd => ({ side, slot, card: b.sides[side].hand[slot], x, y })

function steps(b: Battle, k: number, cmds: Cmd[] = []): Battle {
  let s = step(b, cmds).state
  for (let i = 1; i < k && !s.over; i++) s = step(s).state
  return s
}

test('开局:手里 4 张、排队 4 张、两边各 3 座哨塔 + 大本营;封掉的路没有塔', () => {
  const b = newBattle(cfg())
  for (const s of b.sides) {
    assert.equal(s.hand.length, 4)
    assert.equal(s.queue.length, 4)
    assert.deepEqual([...s.hand, ...s.queue].sort(), STARTERS.slice().sort())
    assert.equal(s.energy, 5)
  }
  assert.equal(b.towers.length, 8)
  assert.equal(laneTower(b, 1, 0)!.hp, LANE_TOWER.hp)
  assert.equal(baseOf(b, 0).hp, BASE_TOWER.hp)
  const c = newBattle(cfg({ closed: [0, 2] }))
  assert.equal(c.towers.length, 4)
  assert.equal(laneTower(c, 0, 0), undefined)
  // 塔按等级长血
  const d = newBattle(cfg({ towerLevel: [1, 3], towerHp: [1, 1.5] }))
  assert.equal(laneTower(d, 1, 1)!.hp, Math.round(LANE_TOWER.hp * 1.5 * statMul(3)))
})

test('step 是纯函数:传进去的对局一点不变', () => {
  let b = newBattle(cfg({ ai: [AI_NORMAL, AI_NORMAL] }))
  b = run(b, 400)
  const before = JSON.stringify(b)
  const r = step(b, [])
  assert.equal(JSON.stringify(b), before)
  assert.notEqual(r.state, b)
})

test('可复现:同一个种子、同一串操作,结果一模一样;换个种子就不一样', () => {
  const play = (seed: number) => JSON.stringify(run(newBattle(cfg({ seed, ai: [AI_HARD, AI_NORMAL] })), 1500))
  assert.equal(play(7), play(7))
  assert.notEqual(play(7), play(8))
})

test('出牌:扣能量,这张排到队尾,排头的补进这个位置', () => {
  const b0 = newBattle(cfg())
  const id = b0.sides[0].hand[1]
  const next = b0.sides[0].queue[0]
  const b = hand(b0, 0, b0.sides[0].hand[0], 10)
  const r = step(b, [cmd(b, 0, 1, LANE_X[1], 10)])
  const s = r.state.sides[0]
  assert.equal(s.hand[1], next)
  assert.equal(s.queue[s.queue.length - 1], id)
  assert.ok(r.events.some((e) => e.e === 'play' && e.card === id), '有出牌事件')
  // 先扣费,同一步里再回一点
  assert.ok(Math.abs(s.energy - Math.min(10, 10 - costOf(id) + DT / 2.8)) < 1e-9, String(s.energy))
  assert.equal(r.state.stats[0].played, 1)
})

function costOf(id: string): number {
  return ({ chick: 2, rabbit: 2, duck: 2, monkey: 3, pig: 3, penguin: 3, bear: 5, fire: 4 } as Record<string, number>)[id]
}

test('出不了的牌:能量不够、这一路封了、界面和状态对不上,都原样忽略', () => {
  const b = hand(newBattle(cfg({ closed: [0] })), 0, 'bear', 4)
  assert.equal(canPlay(b, 0, 0, LANE_X[1], 10).why, '能量不够')
  assert.equal(step(b, [cmd(b, 0, 0, LANE_X[1], 10)]).state.units.length, 0)
  const c = hand(b, 0, 'rabbit', 10)
  assert.equal(canPlay(c, 0, 0, LANE_X[0], 10).ok, false, '封掉的左路')
  assert.equal(step(c, [cmd(c, 0, 0, LANE_X[0], 10)]).state.units.length, 0)
  const wrong = { ...cmd(c, 0, 0, LANE_X[1], 10), card: 'elephant' }
  assert.equal(step(c, [wrong]).state.units.length, 0)
})

test('落点:单位吸到最近的一路,y 限在自己半场;法术哪儿都能放', () => {
  const b = hand(newBattle(cfg()), 0, 'rabbit')
  const p = canPlay(b, 0, 0, LANE_X[2] + 0.9, 3)
  assert.equal(p.ok, true)
  assert.equal(p.lane, 2)
  assert.equal(p.y, ZONE[0][0], '拖到对面半场:放在自己半场的边上')
  assert.ok(Math.abs(p.x - LANE_X[2]) <= 0.45 + 1e-9)
  const s = hand(b, 0, 'fire')
  const q = canPlay(s, 0, 0, 2.2, 2.5)
  assert.equal(q.ok, true)
  assert.equal(q.y, 2.5)
  const e = hand(b, 1, 'rabbit')
  assert.equal(canPlay(e, 1, 0, LANE_X[1], 12).y, ZONE[1][1], '电脑也只能放在自己半场')
})

test('能量:每 2.8 秒回 1 点,最多 10 点', () => {
  const b = newBattle(cfg())
  const s = run(b, Math.round(2.8 / DT))
  assert.ok(Math.abs(s.sides[0].energy - 6) < 1e-6, String(s.sides[0].energy))
  const full = run(b, Math.round(30 / DT))
  assert.equal(full.sides[0].energy, ENERGY_MAX)
  const fast = run(newBattle(cfg({ regen: [2, 1] })), Math.round(2.8 / DT))
  assert.ok(Math.abs(fast.sides[0].energy - 7) < 1e-6)
})

test('击倒返还能量:这只的费用 × 25%(一张卡出几只的按只分摊),满了不溢出', () => {
  // 右路电脑的一只野兔,血只剩 1,玩家的野兔贴脸:一下打死
  let b = newBattle(cfg())
  b = place(b, 'rabbit', 1, 2, LANE_X[2], 7)
  b = place(b, 'rabbit', 0, 2, LANE_X[2], 7.7)
  b.units[0].hp = 1
  b.units[1].cd = 0
  b.sides[0].energy = 3
  const r = steps(b, 3)
  assert.equal(r.stats[0].kills, 1)
  assert.ok(Math.abs(r.stats[0].refund - 2 * 0.25) < 1e-9, String(r.stats[0].refund))
  // 小鸡仔一张出 4 只:每只算 0.5 费
  let c = newBattle(cfg())
  c = place(c, 'chick', 1, 1, LANE_X[1], 7)
  c = place(c, 'rabbit', 0, 1, LANE_X[1], 7.6)
  c.units[0].hp = 1
  c.units[1].cd = 0
  const rc = steps(c, 3)
  assert.ok(Math.abs(rc.stats[0].refund - 0.5 * 0.25) < 1e-9, String(rc.stats[0].refund))
  // 能量满了:返还不溢出
  b.sides[0].energy = ENERGY_MAX
  const full = steps(b, 3)
  assert.equal(full.sides[0].energy, ENERGY_MAX)
  assert.equal(full.stats[0].refund, 0)
})

test('哨塔只打自己这一路;大本营打射程里的所有路', () => {
  // 电脑左路哨塔跟前,中路有一只玩家的熊:左路塔不打它
  let b = newBattle(cfg())
  b = place(b, 'bear', 0, 1, LANE_X[1] - 0.5, TOWER_Y[1] + 1.2)
  const t0 = laneTower(b, 1, 0)!
  const r = run(b, 20)
  const left = r.towers.find((t) => t.id === t0.id)!
  assert.equal(left.tgt, -1, '左路哨塔不打中路的')
  assert.equal(laneTower(r, 1, 1)!.tgt, r.units[0].id, '中路哨塔打它')
  // 大本营:射程里别的路的也打
  let c = newBattle(cfg())
  c = place(c, 'bear', 0, 0, LANE_X[0] + 0.5, BASE_Y[1] + 1.5)
  const rc = run(c, 20)
  assert.equal(baseOf(rc, 1).tgt, rc.units[0].id)
})

test('这一路的哨塔还在,打不到大本营;塔倒了才去打', () => {
  // 一只熊站在电脑中路哨塔和大本营之间(哨塔还在):它打哨塔
  let b = newBattle(cfg())
  b = place(b, 'bear', 0, 1, LANE_X[1], TOWER_Y[1] - 0.9)
  let r = run(b, 30)
  const tw = laneTower(r, 1, 1)!
  assert.equal(r.units[0].tgt, tw.id)
  // 把中路哨塔拆了:改打大本营
  const c: Battle = JSON.parse(JSON.stringify(b))
  const t = laneTower(c, 1, 1)!
  t.alive = false
  t.hp = 0
  r = run(c, 30)
  assert.equal(r.units[0].tgt, baseOf(r, 1).id)
})

test('只打建筑的不理小兵;栅栏能把它吸过去', () => {
  let b = newBattle(cfg())
  b = place(b, 'elephant', 0, 1, LANE_X[1], 8.5)
  b = place(b, 'rabbit', 1, 1, LANE_X[1], 7.6)
  const r = run(b, 10)
  const ele = r.units.find((u) => u.card === 'elephant')!
  assert.notEqual(ele.tgt, r.units.find((u) => u.card === 'rabbit')!.id, '大象不打野兔')
  let c = newBattle(cfg())
  c = place(c, 'elephant', 0, 1, LANE_X[1], 8.5)
  c = place(c, 'fence', 1, 1, LANE_X[1], 6.2)
  const rc = run(c, 10)
  assert.equal(rc.units.find((u) => u.card === 'elephant')!.tgt, rc.units.find((u) => u.card === 'fence')!.id)
})

test('地面近战打不到天上的;远程能打', () => {
  let b = newBattle(cfg())
  b = place(b, 'parrot', 1, 1, LANE_X[1], 7.2)
  b = place(b, 'rabbit', 0, 1, LANE_X[1], 7.6)
  b = place(b, 'duck', 0, 1, LANE_X[1], 9.4)
  const r = run(b, 6)
  const parrot = r.units.find((u) => u.card === 'parrot')!
  assert.notEqual(r.units.find((u) => u.card === 'rabbit')!.tgt, parrot.id)
  assert.equal(r.units.find((u) => u.card === 'duck')!.tgt, parrot.id)
})

test('溅射:河马一屁股坐下去,旁边的小鸡仔一起挨', () => {
  let b = newBattle(cfg())
  b = place(b, 'hippo', 0, 1, LANE_X[1], 8)
  for (const dx of [-0.25, 0, 0.25]) b = place(b, 'chick', 1, 1, LANE_X[1] + dx, 7.05)
  b.units[0].cd = 0
  const r = run(b, 2)
  const hurt = r.units.filter((u) => u.card === 'chick' && u.hp < u.max).length + (3 - r.units.filter((u) => u.card === 'chick').length)
  assert.ok(hurt >= 2, `只打中了 ${hurt} 只`)
})

test('法术:火球打塔只打三成五;冰冻让单位和塔都停手 3 秒', () => {
  let b = hand(newBattle(cfg()), 0, 'fire')
  const tw = laneTower(b, 1, 2)!
  let r = step(b, [cmd(b, 0, 0, tw.x, tw.y)]).state
  const hit = tw.hp - laneTower(r, 1, 2)!.hp
  assert.ok(Math.abs(hit - 300 * 0.35) < 1e-6, String(hit))
  b = place(hand(newBattle(cfg()), 0, 'freeze'), 'bear', 1, 2, LANE_X[2], 5)
  r = step(b, [cmd(b, 0, 0, LANE_X[2], TOWER_Y[1] + 0.6)]).state
  assert.ok(r.units[0].frozenT > 2.9)
  assert.ok(laneTower(r, 1, 2)!.frozenT > 2.9)
  const y0 = r.units[0].y
  const later = run(r, 20)
  assert.equal(later.units[0].y, y0, '冻住的不走')
})

test('胜负:推倒大本营直接赢;时间到比推倒的哨塔;一样多比塔血;再一样是平局', () => {
  const b = newBattle(cfg())
  const c: Battle = JSON.parse(JSON.stringify(b))
  baseOf(c, 1).hp = 1
  const d = place(c, 'bear', 0, 1, LANE_X[1], BASE_Y[1] + 1.5)
  const t = laneTower(d, 1, 1)!
  t.alive = false
  t.hp = 0
  d.units[0].cd = 0
  const r = run(d, 40)
  assert.deepEqual([r.over?.winner, r.over?.reason], [0, 'base'])
  // 时间到:推倒的哨塔多的赢
  const e: Battle = JSON.parse(JSON.stringify(b))
  e.t = 150 - DT
  laneTower(e, 1, 0)!.alive = false
  laneTower(e, 1, 0)!.hp = 0
  e.stats[0].towers = 1
  assert.deepEqual([run(e, 1).over?.winner, run(e, 1).over?.reason], [0, 'time'])
  // 一样多:比剩下的塔血
  const f: Battle = JSON.parse(JSON.stringify(b))
  f.t = 150 - DT
  laneTower(f, 0, 2)!.hp -= 100
  assert.equal(run(f, 1).over?.winner, 1)
  const g: Battle = JSON.parse(JSON.stringify(b))
  g.t = 150 - DT
  assert.deepEqual([run(g, 1).over?.winner, run(g, 1).over?.reason], [-1, 'draw'])
  // 认输
  assert.deepEqual(forfeit(b).over?.winner, 1)
})

test('坚守关:时间到大本营还在就赢;速攻关:推够塔就赢,时间到没推够算输', () => {
  const d = newBattle(cfg({ objective: 'defend', duration: 60 }))
  const dd: Battle = JSON.parse(JSON.stringify(d))
  dd.t = 60 - DT
  laneTower(dd, 0, 0)!.alive = false
  assert.deepEqual([run(dd, 1).over?.winner, run(dd, 1).over?.reason], [0, 'defend'])
  const b = newBattle(cfg({ objective: 'blitz', target: 1, duration: 90 }))
  const bb: Battle = JSON.parse(JSON.stringify(b))
  const t = laneTower(bb, 1, 2)!
  t.hp = 1
  const e = place(bb, 'rabbit', 0, 2, LANE_X[2], TOWER_Y[1] + 1.0)
  e.units[0].cd = 0
  assert.deepEqual([run(e, 40).over?.winner, run(e, 40).over?.reason], [0, 'blitz'])
  const late: Battle = JSON.parse(JSON.stringify(b))
  late.t = 90 - DT
  assert.deepEqual([run(late, 1).over?.winner, run(late, 1).over?.reason], [1, 'timeout'])
})

test('星级:赢了才有星,每满足一个目标一颗', () => {
  const b = newBattle(cfg({ stars: [{ kind: 'win' }, { kind: 'time', n: 100 }, { kind: 'kills', n: 3 }] }))
  const won: Battle = { ...b, over: { winner: 0, reason: 'base', t: 90 }, stats: [{ ...b.stats[0], kills: 2 }, b.stats[1]] }
  assert.equal(starsOf(won), 2)
  assert.equal(goalMet(won, { kind: 'kills', n: 3 }), false)
  assert.equal(starsOf({ ...won, stats: [{ ...b.stats[0], kills: 3 }, b.stats[1]] }), 3)
  assert.equal(starsOf({ ...won, over: { winner: 1, reason: 'base', t: 90 } }), 0)
  assert.equal(starsOf({ ...won, over: { winner: -1, reason: 'draw', t: 150 } }), 0)
})

test('场上最多 70 个单位,再出就不生了', () => {
  let b = newBattle(cfg())
  for (let i = 0; i < MAX_UNITS; i++) b = place(b, 'chick', (i % 2) as 0 | 1, i % 3, LANE_X[i % 3], i % 2 ? 2 : 12)
  assert.equal(b.units.length, MAX_UNITS)
  const c = hand(b, 0, 'rabbit')
  const r = step(c, [cmd(c, 0, 0, LANE_X[1], 10)]).state
  assert.ok(r.units.length <= MAX_UNITS)
})

test('存档往返能接着打;坏存档读不出来;场面最满时存档也远小于云存储单个值的 64 KB', () => {
  let b = run(newBattle(cfg({ ai: [AI_HARD, AI_HARD], seed: 3 })), 1200)
  const back = loadBattle(JSON.parse(JSON.stringify(saveBattle(b))))!
  assert.ok(back)
  assert.equal(back.t, b.t)
  assert.equal(back.units.length, b.units.length)
  // 接着打不会出错,也能打完
  const end = run(back, 20 * 200)
  assert.ok(end.over)
  const bad = (patch: (x: Battle) => void) => {
    const x: Battle = JSON.parse(JSON.stringify(saveBattle(b)))
    patch(x)
    return loadBattle(x)
  }
  assert.equal(bad((x) => { (x as { v: number }).v = 2 }), null)
  assert.equal(bad((x) => { x.units[0] && (x.units[0].card = 'dragon') }) === null || b.units.length === 0, true)
  assert.equal(bad((x) => { x.sides[0].hand = ['chick'] }), null)
  assert.equal(bad((x) => { (x.cfg.decks[0] as { cards: string[] }).cards = ['nope'] }), null)
  assert.equal(loadBattle('garbage'), null)
  assert.equal(loadBattle(null), null)
  // 最满的场面:70 个单位 + 60 发弹道
  b = newBattle(cfg())
  for (let i = 0; i < MAX_UNITS; i++) b = place(b, i % 2 ? 'gorilla' : 'parrot', (i % 2) as 0 | 1, i % 3, LANE_X[i % 3] + 0.123456, 3.3333 + (i % 20) * 0.37777)
  for (let i = 0; i < 60; i++) {
    b.shots.push({ id: 5000 + i, side: 0, kind: 'pellet', x: 1.23456, y: 2.34567, px: 1.2, py: 2.3, tgt: b.units[i].id, tx: 3.14159,
      ty: 2.71828, speed: 8, dmg: 123.456789, splash: 0, hitsAir: true, slow: 0, poison: 0 })
  }
  const size = JSON.stringify({ v: 1, battle: saveBattle(b) }).length
  assert.ok(size < 60 * 1024, `最满的对局存档 ${size} 字节`)
})

test('电脑对电脑:打满一局不出 NaN,单位都在战场里', () => {
  for (const seed of [1, 2, 3]) {
    let b = newBattle(cfg({ seed, ai: [AI_NORMAL, AI_HARD], closed: seed === 3 ? [1] : [] }))
    while (!b.over) {
      b = step(b).state
      for (const u of b.units) {
        assert.ok(Number.isFinite(u.x) && Number.isFinite(u.y) && Number.isFinite(u.hp), `单位 ${u.card} 的数不对`)
        assert.ok(u.x >= 0 && u.x <= 9 && u.y >= 0 && u.y <= 14)
      }
    }
    assert.ok(b.over.t <= 150 + 1e-9)
  }
})
