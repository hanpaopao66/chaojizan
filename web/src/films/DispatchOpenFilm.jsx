import React from 'react'

import { Caption, Ease, Film, MONO, P, SERIF, enter, pop, tween, useFilm, useWidth } from './kit.jsx'

/* 透明中心「派单算法」一节(第 8 节)的片子:公式已经贴在那儿了,这支是让人看懂它。
 * 算法只排信息,不做决定。
 *
 * 每个权重都是 server/app/services/dispatch.py 里的真实常量:
 *   WAIT_WEIGHT_M_PER_MIN = 150   WAIT_BONUS_MAX_M = 3000
 *   TIP_WEIGHT_M_PER_YUAN = 300   TIP_BONUS_MAX_M  = 1500
 *   SAME_SHOP_BONUS_M = 2000
 *   SAME_WAY_STRONG_MAX_M = 500  → SAME_WAY_STRONG_BONUS_M = 1800
 *   SAME_WAY_WEAK_MAX_M   = 1500 → SAME_WAY_WEAK_BONUS_M   = 700
 *   TRIP_WEIGHT = 0.35
 * /transparency/dispatch 不用登录,公开值从这些常量拼出来;单测
 * test_dispatch.py 的「改了常量公开值跟着变」钉着。每一条「为什么」照 public_spec 的原意缩写。
 *
 * 三张候选单是示例,分数能自己算:旧公式(2026-07-31 改版前,riders.py)=
 * 到取餐点直线距离 − 等待分钟 × 150 − 小费元 × 300,两项都没上限;新公式见画面。
 * DEV-PROMPTS-15 记的三条验证正是画面里这件事:「同店 220m 单排在 4km 单前」
 * 「巨额小费买不过强顺路 + 同店」「假顺路从 True 变 none(绕路 7214m)」。
 *
 * 和原稿不一样(按代码核过):
 * - 顺路的参照点:原稿写「→ 手头单送达」。2026-09-10 起手头单还没取餐时参照点是
 *   那家店(riders.py 的 my_drops),而且四段都按直线 × 1.2 估(routing.detour_m);
 * - 红线里「选单权在骑手手里」:后台有人工改派(异常时协调),改成「系统不派单」;
 *   「不做自动接单」后面那句「友商都有」查不到出处,删;「恶劣天气是加价 + 降速」的
 *   「降速」容易读成让骑手骑慢,照 LABOR_PROMISES 写成「加价的同时放宽时限」
 *   (「ETA 只放宽不收紧」「加价同时放宽时限」这两条的服务端改动和这一批一起上);
 * - 周报那条:e2e 查的是返回体的字段名(score / rank / level…),不是「排名」这两个字;
 * - 片子就放在透明中心这一节里,收尾那句不再写「官网透明中心第 8 节」。 */

// @serif-cjk-begin
const TITLES = [
  '谁排在前面，凭什么？',
  '公式和每个权重的当前取值，全都公开。',
  '算法只排信息，不做决定。',
]
// @serif-cjk-end

/* 字幕底下那行说明(黑体,不进衬线子集) */
const DETAILS = [
  '旧公式只有「到取餐点直线距离 − 等待 − 小费」，小费还没有上限 —— 20 元小费能抵消 6000 米，超过整个 4 公里的配送半径。',
  '不是描述性文字：接口从 dispatch.py 的常量同源读取，改一个常量，公开值跟着变（有单测钉住）。',
  '它决定谁排在前面，不决定谁必须去 —— 系统不派单，大厅里的单骑手自己挑。',
]

const REPO = 'https://github.com/hanpaopao66/chaojizan/blob/main/'

// ---------- 真实常量(dispatch.py) ----------
const K = {
  WAIT_PER_MIN: 150, WAIT_MAX: 3000,
  TIP_PER_YUAN: 300, TIP_MAX: 1500,
  SAME_SHOP: 2000,
  WAY_STRONG_MAX: 500, WAY_WEAK_MAX: 1500,
  WAY_STRONG_BONUS: 1800, WAY_WEAK_BONUS: 700,
  TRIP_WEIGHT: 0.35,
}

/* 三张候选单(示例)。detour = 绕路增量,null 表示手头没单可顺 */
const CANDS = [
  { id: 'A', shop: '张记面馆', pick: 220, trip: 1800, wait: 4, tip: 0, sameShop: true, detour: 380 },
  { id: 'B', shop: '李婶砂锅粥', pick: 900, trip: 2600, wait: 12, tip: 0, sameShop: false, detour: 1200 },
  { id: 'C', shop: '城西川香居', pick: 1500, trip: 4000, wait: 2, tip: 20, sameShop: false, detour: 7214 },
]

const wayLevel = d => (d == null ? 'none' : d < K.WAY_STRONG_MAX ? 'strong' : d < K.WAY_WEAK_MAX ? 'weak' : 'none')
const wayBonus = d => ({ strong: K.WAY_STRONG_BONUS, weak: K.WAY_WEAK_BONUS, none: 0 })[wayLevel(d)]
const oldScore = c => c.pick - c.wait * K.WAIT_PER_MIN - c.tip * K.TIP_PER_YUAN
const newScore = c => c.pick + c.trip * K.TRIP_WEIGHT
  - Math.min(c.wait * K.WAIT_PER_MIN, K.WAIT_MAX)
  - Math.min(c.tip * K.TIP_PER_YUAN, K.TIP_MAX)
  - (c.sameShop ? K.SAME_SHOP : 0)
  - wayBonus(c.detour)
const BY_OLD = [...CANDS].sort((a, b) => oldScore(a) - oldScore(b))
const BY_NEW = [...CANDS].sort((a, b) => newScore(a) - newScore(b))

/* [项, 取值, 为什么是这个数] */
const WEIGHTS = [
  ['送程', '× 0.35 入分', '取 0.35 不取 1：送程有配送费覆盖，去取餐那段是白跑的，白跑的更该算成本'],
  ['等待', '150 米 / 分钟，封顶 3000', '让久等的单不永远垫底；等太久的走无人接单兜底，不靠把它顶到榜首硬推'],
  ['小费', '300 米 / 元，封顶 1500', '这是「钱能买多靠前」的定价 —— 不封顶就是价高者得；超出的小费骑手照收'],
  ['同店', '−2000 米', '在同一家店多取一单，取餐几乎零成本，比路线接近值钱'],
  ['强顺路', '绕路增量 < 500 → −1800', '按多跑的路判，不按两点距离 —— 多跑的路才是骑手真正付出的'],
  ['弱顺路', '绕路增量 < 1500 → −700', '同上，少一档'],
]

/* 红线:每一条都有代码撑着(dispatch.py 的 never_do、labor_guard 的 LABOR_PROMISES、
 * DEV-PROMPTS-29 #267、e2e_rider_growth) */
const LINES = [
  ['系统不派单', '大厅里的单骑手自己挑，不接不扣分'],
  ['算法只排信息，不做决定', '它决定谁排在前面，不决定谁必须去'],
  ['不做自动接单', '骑手端没有这个开关，每一单都是自己点的'],
  ['ETA 只能放宽，不能收紧', '恶劣天气加价的同时放宽时限'],
  ['周报没有评分、等级、排名', 'e2e 逐个查返回的字段名，出现 score、rank、level 就失败'],
]

const CUE = { cands: 0.3, oldsort: 1.6, formula: 3.2, weights: 4.4, resort: 7.2, note: 9.8, lines: 11.2, close: 15.6 }
const TOTAL = 19.6
/** 静帧:已按新公式排好、说明和五条红线都在、收尾那句也出了 */
const STILL = 16.4
/* 行距:卡片 74px(内容 + padding 9×2 + 边框 2,box-sizing 算进去)+ 8px 间隙。
 * 窄屏那行「取餐 · 送程 · 等待」要折成两行,卡片高一截 */
const ROW_H = 82
const ROW_H_NARROW = 96

const Src = ({ children, to }) => (
  <a href={REPO + to} target="_blank" rel="noopener noreferrer" style={{ fontFamily: MONO, fontSize: 11, color: P.link }}>{children}</a>
)

export default function DispatchOpenFilm() {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.5 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 800

  const rowH = narrow ? ROW_H_NARROW : ROW_H
  const k = tween(T, { start: CUE.resort, end: CUE.resort + 1.1, ease: Ease.inOut })
  const showNew = T >= CUE.resort
  const capIdx = T >= CUE.lines ? 2 : T >= CUE.formula ? 1 : 0

  return (
    <Film film={film} label="示例 · 同一时刻的三张候选单" loop="循环 · 20 秒"
      style={{ background: P.card, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      {/* 公式:账目深台面 */}
      <div style={{ background: P.ledger, color: P.dtext, borderRadius: 12, padding: narrow ? '14px 16px' : '16px 18px', ...enter(T, CUE.formula) }}>
        <div style={{ fontSize: 10.5, letterSpacing: 1, color: P.dmute }}>综合分（越小越靠前，单位：米）</div>
        <div style={{ fontFamily: MONO, fontSize: narrow ? 11.5 : 13, marginTop: 7, lineHeight: 1.85 }}>
          <span>到取餐点距离 + 送程 × 0.35</span><br />
          <span style={{ color: P.dgold }}>− min(等待分钟 × 150, 3000) − min(小费元 × 300, 1500)</span><br />
          <span style={{ color: P.dearn }}>− 同店 2000 − 顺路（强 1800 / 弱 700）</span>
        </div>
        <div style={{ fontSize: 11.5, color: P.dfaint, marginTop: 8, lineHeight: 1.6 }}>
          顺路看绕路增量：当前位置 → 新单取餐 → 新单送达 → 手头单下一站（还没取餐就是那家店），比不接这单多跑的那段，按直线 × 1.2 估 —— 不是两个点之间的距离
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : 'minmax(0,1fr) 320px', gap: 18, alignItems: 'start' }}>
        {/* 候选单:重排 */}
        <div>
          <p className="sr">示例：三张候选单。按旧公式，C 城西川香居的 20 元小费抵消 6000 米，排第一；按现在的公式，A 张记面馆同店加强顺路排第一，B 第二，C 的小费封顶 1500 米、绕路 7214 米不算顺路，排到最后。</p>
          <div aria-hidden="true">
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8 }}>
              <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1 }}>{showNew ? '按现在的公式排' : '按旧公式排（小费无上限）'}</span>
              <span style={{ fontSize: 11.5, color: P.ink3 }}>越小越靠前</span>
            </div>
            <div style={{ position: 'relative', height: rowH * CANDS.length }}>
              {CANDS.map((c, idx) => {
                const oi = BY_OLD.indexOf(c)
                const ni = BY_NEW.indexOf(c)
                const y = (oi + (ni - oi) * k) * rowH
                const sc = showNew ? newScore(c) : oldScore(c)
                const lvl = wayLevel(c.detour)
                const fakeWay = c.detour != null && c.detour >= K.WAY_WEAK_MAX
                // 入场上浮和重排位移放在同一个 transform 里(enter() 自带 transform,会把位移盖掉)
                const at = CUE.cands + idx * 0.3
                const ek = tween(T, { start: at, end: at + 0.28 })
                return (
                  <div key={c.id} style={{
                    position: 'absolute', left: 0, right: 0, top: 0, height: rowH - 8, boxSizing: 'border-box',
                    transform: `translateY(${y + (1 - ek) * 10}px)`, opacity: ek,
                    border: `1px solid ${P.line}`, borderRadius: 10, background: P.card,
                    padding: '9px 12px', display: 'flex', alignItems: 'center', gap: 12,
                  }}>
                    <span style={{
                      width: 22, height: 22, borderRadius: 6, flex: 'none', background: P.alt,
                      fontFamily: SERIF, fontWeight: 600, fontSize: 12,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>{c.id}</span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: 'block', fontSize: 13.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.shop}</span>
                      <span style={{ display: 'block', fontSize: 11.5, color: P.ink2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: narrow ? 'normal' : 'nowrap', lineHeight: 1.45 }}>
                        取餐 {c.pick}m · 送程 {c.trip}m · 等待 {c.wait} 分{c.tip > 0 && ` · 小费 ¥${c.tip}`}{c.sameShop && ' · 同店'}
                      </span>
                    </span>
                    <span style={{ flex: 'none', textAlign: 'right' }}>
                      <span style={{ display: 'block', fontFamily: SERIF, fontWeight: 600, fontSize: 15, fontVariantNumeric: 'tabular-nums', color: sc < 0 ? P.earn : P.ink2 }}>
                        {sc < 0 ? `−${Math.round(-sc)}` : Math.round(sc)}
                      </span>
                      <span style={{ display: 'block', fontSize: 10.5, color: fakeWay && showNew ? P.danger : P.ink3 }}>
                        {showNew
                          ? (lvl === 'strong' ? '强顺路' : lvl === 'weak' ? '弱顺路' : `绕路 ${c.detour}m`)
                          : (c.tip > 0 ? `小费 −${c.tip * K.TIP_PER_YUAN}` : '—')}
                      </span>
                    </span>
                  </div>
                )
              })}
            </div>
          </div>

          <div style={{
            marginTop: 4, padding: '11px 13px', borderRadius: 10, background: P.claySoft,
            fontSize: 12.5, lineHeight: 1.6, ...pop(T, CUE.note), transformOrigin: 'left center',
          }}>
            C 的小费 ¥20 在旧公式里抵消 6000 米，把一张送程 4km 的远单顶到第一位。封顶 1500 之后，
            <b style={{ fontWeight: 600 }}>巨额小费买不过强顺路 + 同店</b>；C 的绕路增量 7214m，顺路判定直接从「是」变成「不是」。
          </div>
        </div>

        {/* 权重表 */}
        <div style={{ border: `1px solid ${P.line}`, borderRadius: 12, overflow: 'hidden' }}>
          <div style={{ height: 3, background: P.run }} />
          <div style={{ padding: '13px 15px' }}>
            <div style={{ fontSize: 11, letterSpacing: 1.2, color: P.ink2 }}>每个权重，以及为什么是这个数</div>
            <div style={{ display: 'flex', flexDirection: 'column', marginTop: 4 }}>
              {WEIGHTS.map(([name, value, why], i) => (
                <div key={name} style={{ borderTop: `1px solid ${P.line}`, padding: '9px 0', ...enter(T, CUE.weights + i * 0.32, 0.26) }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 13, fontWeight: 600, flex: 'none' }}>{name}</span>
                    <span style={{ fontSize: 12.5, color: P.hold, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
                  </div>
                  <div style={{ fontSize: 11.5, color: P.ink2, marginTop: 2, lineHeight: 1.55 }}>{why}</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 11, color: P.ink3, marginTop: 10, lineHeight: 1.7 }}>
              出处 <Src to="server/app/services/dispatch.py">server/app/services/dispatch.py</Src><br />
              取舍记录 <Src to="docs/DEV-PROMPTS-15.md">docs/DEV-PROMPTS-15.md</Src>
            </div>
          </div>
        </div>
      </div>

      {/* 红线 */}
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : `repeat(${LINES.length}, minmax(0,1fr))`, gap: 9 }}>
        {LINES.map(([t, d], i) => (
          <div key={t} style={{ border: `1px solid ${P.line}`, borderRadius: 10, padding: '10px 12px', ...enter(T, CUE.lines + i * 0.28, 0.26) }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{t}</div>
            <div style={{ fontSize: 11.5, color: P.ink2, marginTop: 2, lineHeight: 1.55 }}>{d}</div>
          </div>
        ))}
      </div>

      <div aria-hidden="true">
        <Caption titles={TITLES} details={DETAILS} index={capIdx} narrow={narrow} detailColor={P.ink2}>
          <div style={{ fontSize: 12, color: P.ink2, marginTop: 4, opacity: tween(T, { start: CUE.close, end: CUE.close + 0.6 }), lineHeight: 1.7 }}>
            公开、不用登录：<span style={{ fontFamily: MONO }}>/transparency/dispatch</span> · 算法可以改，但不能悄悄改 —— 改了要记一笔：时间、改了什么、为什么（就在这一节下面）。
          </div>
        </Caption>
      </div>
    </Film>
  )
}
