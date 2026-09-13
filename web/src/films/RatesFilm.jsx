import React from 'react'

import { CHANNELS, STATE_LABEL } from '../SiteChrome.jsx'
import { Caption, Film, P, SANS, SERIF, enter, tween, useFilm, useWidth } from './kit.jsx'

/* 费率页(/rates)的片子:六个频道抽多少、什么时候抽,同一把尺量给你看。
 *
 * 频道的字、颜色取 SiteChrome 的 CHANNELS(= channels.dart),费率和「什么时候收」
 * 同费率表,行业那一段同首页费率表的「行业现状」。行业只画区间带
 * (20%+、OTA 12%–20%、两三成),不画成一个假的小数点;没有区间可画的频道
 * 就不写行业那半句。
 *
 * 和原稿不一样:原稿说「开没开不写在这里」,六行一律按开着画。可它就放在费率表
 * 正上方,表里没开的频道挂着「暂未开放」,片子里却是满色的 —— 读 /channels 的
 * 状态由页面传进来(stateOf),没开的频道字块和名字压成弱色、名字后面挂同一句
 * 「暂未开放」;费率照画,那是写在代码里的数。 */

// @serif-cjk-begin
// 字幕大字(衬线显示,这个圈里的字才会进官网的衬线子集)
const TITLES = [
  '一把尺，量六个频道。',
  '他们的那一段，也画上去。',
  '关键不是抽多少，是什么时候抽。',
  '5% 是上限，不是目标。',
]
// @serif-cjk-end

/* 字幕底下那行说明(黑体,不进衬线子集) */
const DETAILS = [
  '整条轨是 25%。我们的那一段，和别人的那一段，画在同一把尺上。',
  '区间就画成区间 —— 我们不替别人编一个好看的小数点。',
  '订单完成才收、离店才收、核销才收：没成的单，平台分文不取。',
  '哪天 3% 能活，就降到 3% —— 这行写在开源仓的 README 里当立字据。',
]

/** 整条轨 = 25%,所有行同一把尺 */
const SCALE = 25

const RATE = {
  food: { rate: 5, when: '订单完成才收 · 配送费、小费不抽', ind: [20, 25], indText: '行业：商家总负担普遍 20%+' },
  retail: { rate: 5, when: '同外卖 · 同一套配送' },
  stay: { rate: 5, when: '离店才收 · 取消、未入住不收', ind: [12, 20], indText: 'OTA 12%–20%，另有排他条款' },
  voucher: { rate: 2, when: '到店核销才收 · 未用随时全退' },
  errand: { rate: 2, when: '只收跑腿费的 2% · 商品款不抽' },
  ride: { rate: 0, when: '计价规则公开后再定', ind: [20, 25], indText: '行业：司机每单被抽两三成' },
}
const BAND = 'repeating-linear-gradient(115deg,#CFCABD 0 4px,#DCD8CB 4px 8px)'

const CUE = { rows: 0.3, bars: 2.3, bands: 6.6, when: 9.8, close: 13.2 }
const TOTAL = 16.6
const STILL = 12.4

export default function RatesFilm({ stateOf }) {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.5 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 720
  const capIdx = T >= CUE.close ? 3 : T >= CUE.when ? 2 : T >= CUE.bands ? 1 : 0

  return (
    <Film film={film} label="平台收多少 · 同一把尺（整条轨 = 25%）" loop="循环 · 17 秒" gap={16}
      summary="示例动画：同一把尺（整条 25%）量六个频道：点外卖、买菜买水果、住宿收 5%，超值团购、帮我送收 2%，打车在筹备。外卖行业商家总负担普遍 20% 以上，OTA 抽 12% 到 20%，画成区间带。关键是什么时候收：订单完成才收、离店才收、核销才收。"
      style={{ background: P.card, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      <div style={{ borderTop: `1px solid ${P.line}` }}>
        {CHANNELS.map((ch, i) => {
          const r = RATE[ch.key]
          const state = ch.coming ? 'coming' : (stateOf ? stateOf(ch.key) : 'open')
          const dim = state !== 'open'
          const at = CUE.rows + i * 0.36
          const barAt = CUE.bars + i * 0.28
          const k = tween(T, { to: r.rate / SCALE, start: barAt, end: barAt + 0.9 })
          const bandAt = CUE.bands + i * 0.35
          const bandK = r.ind ? tween(T, { start: bandAt, end: bandAt + 0.5 }) : 0
          const whenK = tween(T, { start: CUE.when + i * 0.22, end: CUE.when + i * 0.22 + 0.4 })
          return (
            <div key={ch.key} style={{
              borderBottom: `1px solid ${P.line}`, padding: narrow ? '12px 0' : '13px 0',
              display: 'grid', gridTemplateColumns: narrow ? '28px minmax(0,1fr) 62px' : '28px 132px minmax(0,1fr) 62px',
              columnGap: 12, rowGap: 6, alignItems: 'center', ...enter(T, at, 0.22),
            }}>
              <span style={{
                width: 28, height: 28, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontFamily: "'SzSerifCJK','PingFang SC',serif", fontWeight: 600, fontSize: 14, lineHeight: 1,
                color: dim ? P.ink3 : ch.color, background: dim ? P.alt : ch.tint,
              }} aria-hidden="true">{ch.glyph}</span>
              <span style={{ minWidth: 0, lineHeight: 1.35 }}>
                <span style={{ display: 'block', fontSize: 14, fontWeight: 600, color: dim ? P.ink3 : P.ink, whiteSpace: narrow ? 'normal' : 'nowrap' }}>
                  {ch.coming ? `${ch.name}（筹备）` : (ch.fullName ?? ch.name)}
                </span>
                {state === 'closed' && <span style={{ display: 'block', fontSize: 11.5, color: P.ink3 }}>{STATE_LABEL.closed}</span>}
              </span>

              {/* 尺 */}
              <div style={{ gridColumn: narrow ? '1 / -1' : 'auto', minWidth: 0 }}>
                <div style={{ position: 'relative', height: 12, borderRadius: 999, background: P.alt, overflow: 'hidden' }}>
                  {r.ind && (
                    <span style={{
                      position: 'absolute', top: 0, bottom: 0,
                      left: `${(r.ind[0] / SCALE) * 100}%`, width: `${((r.ind[1] - r.ind[0]) / SCALE) * 100}%`,
                      background: BAND, opacity: bandK, transform: `scaleX(${0.6 + 0.4 * bandK})`, transformOrigin: 'left',
                    }} />
                  )}
                  <span style={{
                    position: 'absolute', left: 0, top: 0, bottom: 0, width: `${k * 100}%`, borderRadius: 999,
                    background: ch.coming ? '#CFCABD' : P.hold,
                  }} />
                </div>
                <div style={{ fontSize: 12, color: P.ink2, marginTop: 5, display: 'flex', columnGap: 10, flexWrap: 'wrap' }}>
                  <span style={{ opacity: whenK }}>{r.when}</span>
                  {r.ind && <span style={{ opacity: bandK * 0.9, color: P.ink3 }}>{r.indText}</span>}
                </div>
              </div>

              <span style={{
                fontFamily: ch.coming ? SANS : SERIF, fontWeight: 600, fontSize: ch.coming ? 12.5 : 16,
                color: ch.coming ? P.ink3 : P.hold, textAlign: 'right', fontVariantNumeric: 'tabular-nums',
                gridColumn: narrow ? '3' : 'auto', gridRow: narrow ? '1' : 'auto',
              }}>{ch.coming ? STATE_LABEL.coming : `${r.rate}%`}</span>
            </div>
          )
        })}
      </div>

      <div style={{ display: 'flex', gap: 16, fontSize: 11.5, color: P.ink2, flexWrap: 'wrap' }}>
        <span><span style={{ display: 'inline-block', width: 14, height: 8, borderRadius: 2, background: P.hold, marginRight: 6 }} />平台收</span>
        <span><span style={{ display: 'inline-block', width: 14, height: 8, borderRadius: 2, background: BAND, marginRight: 6 }} />行业区间（普遍口径，非某一家实数）</span>
      </div>

      <Caption titles={TITLES} details={DETAILS} index={capIdx} narrow={narrow} detailColor={P.ink2} />
    </Film>
  )
}
