import React from 'react'

import { Caption, Ease, Film, MONO, P, SERIF, enter, pop, tween, useFilm, useWidth } from './kit.jsx'

/* 透明中心(/transparency#audit)核账那一栏的开场片:差一分钱都亮红灯。
 *
 * 讲的是 services/audit.py 每天 04:00 干的事,口径和这一栏的正文一字不差:
 * 自动核对近 30 天每一笔账 —— 商家入账 = 菜钱 − 佣金、骑手入账 = 配送费
 * (100% 归骑手)、退款汇总 = 逐笔流水之和。绿格子是差错 0 的一天,红格子是
 * 那天的核账查出了差错,灰格子是那天没跑成、没有结论(不是干净,也不是有错)。
 * 格子和笔数是示例,真的 90 格就在这支片子下面,读 /transparency/audit。
 *
 * 和原稿不一样:原稿右上角那颗状态胶囊写着具体日期(「9 月 11 日 04:00 核账通过」)。
 * 它就放在真日历的正上方,长得又和页头那颗真胶囊一模一样 —— 真账那天要是亮了红灯,
 * 示例却在上面写「今天通过」,等于替我们打圆场。所以示例里不写日期。 */

// @serif-cjk-begin
// 字幕大字(衬线显示,这个圈里的字才会进官网的衬线子集)
const TITLES = [
  '每天 04:00，自己查自己。',
  '三条恒等式，一条都不许差。',
  '差一分钱都亮红灯。',
  '绿格子是干净的一天。',
]
// @serif-cjk-end

/* 字幕底下那行说明(黑体,不进衬线子集) */
const DETAILS = [
  '近 30 天每一笔账重算一遍 —— 不是抽查，是逐笔。',
  '商家入账、骑手入账、退款汇总，对不上就不算通过。',
  '示例：这一天的核账查出 1 笔差 ¥0.01，红格子当天就挂在公示页上，不等我们解释完。',
  '灰格子是那天没跑成、没有结论 —— 不粉刷成绿的。',
]

const CUE = { clock: 0.3, scan: 1.4, checks: 4.2, problem: 7.4, lamp: 8.2, grey: 10.2, close: 11.8 }
const TOTAL = 14.6
/** 静帧:红灯亮着、那条恒等式标红 */
const STILL = 9.6

const COLS = 15
const ROWS = 6 // 6 × 15 = 90 天,同这一栏下面的 90 格
const CELLS = COLS * ROWS
const BAD_CELL = 76
const GREY_CELLS = [13, 41]
const SCAN = 3.4

const CHECKS = [
  ['商家入账', '菜钱 − 佣金'],
  ['骑手入账', '配送费 100% 归骑手'],
  ['退款汇总', '逐笔流水之和'],
]

const Swatch = ({ color }) => (
  <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: color, marginRight: 6 }} />
)

export default function AuditLampFilm() {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.5 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 700

  // 扫描:格子按顺序点亮,笔数同步往上滚
  const scanK = tween(T, { start: CUE.scan, end: CUE.scan + SCAN, ease: Ease.inOut })
  const lit = Math.floor(scanK * CELLS)
  const orders = Math.round(1284 * scanK)
  const problem = T >= CUE.problem
  const lamp = T >= CUE.lamp
  const breathe = 3 + 3 * Math.abs(Math.sin(T * 3))
  const capIdx = T >= CUE.grey ? 3 : T >= CUE.problem ? 2 : T >= CUE.checks ? 1 : 0

  return (
    <Film film={film} label="示例 · 每日核账公示" loop="循环 · 15 秒"
      summary="示例动画：系统每天 04:00 把近 30 天的账逐笔重算一遍，90 天的核账结果排成 90 格：绿格是差错 0 的一天，红格是那天的核账查出了差错，灰格是那天没跑成、没有结论。三条恒等式：商家入账等于菜钱减佣金，骑手入账等于配送费，退款汇总等于逐笔流水之和；差一分钱就亮红灯。"
      style={{ background: P.card, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      {/* 04:00 + 笔数 + 状态灯 */}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: narrow ? 16 : 28, flexWrap: 'wrap', ...enter(T, CUE.clock) }}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: 1.2, color: P.ink2 }}>核账时刻</div>
          <div style={{ fontFamily: SERIF, fontWeight: 600, fontSize: narrow ? 30 : 38, fontVariantNumeric: 'tabular-nums', lineHeight: 1.2 }}>04:00</div>
        </div>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ fontSize: 11, letterSpacing: 1.2, color: P.ink2 }}>本次核对（近 30 天）</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: narrow ? 26 : 32, fontVariantNumeric: 'tabular-nums' }}>{orders.toLocaleString()}</span>
            <span style={{ fontSize: 13, color: P.ink2 }}>笔</span>
          </div>
        </div>
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 8, padding: '7px 14px', borderRadius: 999,
          border: `1px solid ${lamp ? P.danger : P.line}`, background: lamp ? 'rgba(208,48,48,.08)' : P.card,
          fontSize: 13, color: lamp ? P.danger : P.ink,
        }}>
          <span style={{
            width: 7, height: 7, borderRadius: '50%', background: lamp ? P.danger : P.earn,
            boxShadow: lamp ? `0 0 0 ${breathe}px rgba(208,48,48,.16)` : 'none',
          }} />
          {lamp ? '查出 1 笔差错 · 当天挂出来' : '04:00 核账通过 · 差错 0 笔'}
        </div>
      </div>

      {/* 90 格 */}
      <div>
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${COLS}, minmax(0,1fr))`, gap: narrow ? 3 : 5 }}>
          {Array.from({ length: CELLS }, (_, i) => {
            const on = i < lit
            const bad = problem && i === BAD_CELL
            // 灰 = 没跑成,同真日历的 .d.blank(发丝线色)
            const bg = !on ? P.alt : bad ? P.danger : GREY_CELLS.includes(i) ? P.line : P.earn
            const at = CUE.scan + (i / CELLS) * SCAN
            const k = on ? tween(T, { start: at, end: at + 0.22, ease: Ease.spring }) : 0
            return (
              <span key={i} style={{
                height: narrow ? 12 : 16, borderRadius: 2, background: bg,
                transform: `scale(${on ? 0.9 + 0.1 * k : 1})`, opacity: on ? 1 : 0.55,
                boxShadow: bad ? `0 0 0 ${breathe - 1}px rgba(208,48,48,.18)` : 'none',
              }} />
            )
          })}
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 11.5, color: P.ink2, flexWrap: 'wrap' }}>
          <span><Swatch color={P.earn} />差错 0 笔</span>
          <span style={{ opacity: problem ? 1 : 0.35 }}><Swatch color={P.danger} />查出差错</span>
          <span style={{ opacity: T >= CUE.grey ? 1 : 0.35 }}><Swatch color={P.line} />那天没跑成 · 没有结论</span>
        </div>
      </div>

      {/* 三条恒等式 */}
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : 'repeat(3, minmax(0,1fr))', gap: 10 }}>
        {CHECKS.map((c, i) => {
          const at = CUE.checks + i * 0.4
          const failed = problem && i === 2
          return (
            <div key={c[0]} style={{
              border: `1px solid ${failed ? P.danger : P.line}`, borderRadius: 10,
              padding: '12px 14px', background: failed ? 'rgba(208,48,48,.05)' : P.card, ...enter(T, at),
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  width: 18, height: 18, borderRadius: '50%', flex: 'none',
                  border: `1.5px solid ${failed ? P.danger : P.earn}`, color: failed ? P.danger : P.earn,
                  fontSize: 11, lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                  ...pop(T, at + 0.3),
                }}>{failed ? '!' : '✓'}</span>
                <span style={{ fontSize: 14, fontWeight: 600 }}>{c[0]}</span>
              </div>
              <div style={{ fontSize: 12.5, color: P.ink2, marginTop: 4 }}>{c[1]}</div>
              {/* 标红的是第三条:这一行一开始就占着位置,标红时卡片不长高
                  (手机上三张卡竖排,长高一截下面的页面就跟着跳) */}
              {i === 2 && (
                <div style={{ fontSize: 12, color: P.danger, marginTop: 6, visibility: failed ? 'visible' : 'hidden', ...pop(T, CUE.problem + 0.2) }}>
                  1 笔差 ¥0.01 · 已挂公示
                </div>
              )}
            </div>
          )
        })}
      </div>

      <Caption titles={TITLES} details={DETAILS} index={capIdx} narrow={narrow}
        color={capIdx === 2 ? P.danger : P.ink} detailColor={P.ink2}>
        <div style={{ fontFamily: MONO, fontSize: 12, color: P.ink3, marginTop: 4 }}>server/app/services/audit.py</div>
      </Caption>
    </Film>
  )
}
