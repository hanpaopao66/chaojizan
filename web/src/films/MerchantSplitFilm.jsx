import React from 'react'

import { Amount, Caption, Film, P, pop, enter, tween, useFilm, useWidth, yuan } from './kit.jsx'

/* 商家入驻页(/join/merchant)的算账片:同一单 ¥26,别处 vs 这里。
 *
 * 数字都是这一单自己算得出来的,和 /rates、首页流程片同一单:
 * 菜价 ¥21 + 配送费 ¥5 = ¥26;这里收菜价的 5% = ¥1.05,商家到手 ¥19.95。
 * 行业那一边只写普遍口径(商家总负担 20%+ → 这一单 ¥4 多、到手不到 ¥17),
 * 不替别人编小数点。
 *
 * 和原稿不一样:差额原稿写「≈ ¥3」。20% 起步的话差额至少 ¥4.20 − ¥1.05 = ¥3.15,
 * 「约 3 块」往少里说了,改成「¥3 多」(一天 40 单一百多块,这句照旧成立)。 */

// @serif-cjk-begin
const CAPS = [
  '同一单：菜价 ¥21 + 配送费 ¥5 = ¥26。',
  '行业平台：商家总负担普遍 20% 以上。',
  '在这里：只收菜价的 5%，配送费一分不抽。',
  '开店不要钱，卖出去才收 5%。',
]
const ELSE_CUT = '−¥4 多'
const ELSE_GOT = '不到 ¥17'
const GAP = '¥3 多'
// @serif-cjk-end

const CUE = { bill: 0.2, elsewhere: 2.2, here: 6.2, gap: 10.6, close: 12.8 }
const TOTAL = 15.4
/** 减少动态效果时的那一帧:两边都算完、差额和收尾字都已出 */
const STILL = 13.8

/** 抽成刻度:整条轨 = 菜价 ¥21,左右两边同一把尺,比例不失真 */
function Scale({ k, color, label, amount, tone }) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 12.5, color: P.ink2 }}>
        <span style={{ flex: 1 }}>{label}</span>
        <Amount v={amount} size={13.5} color={tone} />
      </div>
      <div style={{ marginTop: 7, height: 10, borderRadius: 999, background: P.alt, overflow: 'hidden', display: 'flex' }}>
        <span style={{ width: `${k * 100}%`, background: color, borderRadius: 999 }} />
      </div>
    </div>
  )
}

function Side({ T, at, title, cap, scale, got, gotColor, bg, border, note }) {
  return (
    <div style={{
      background: bg, border, borderRadius: 12, padding: '18px 20px',
      display: 'flex', flexDirection: 'column', gap: 14, ...enter(T, at),
    }}>
      <div>
        <div style={{ fontSize: 11, letterSpacing: 1.2, color: P.ink2 }}>{title}</div>
        <div style={{ fontSize: 13, color: P.ink2, marginTop: 6, lineHeight: 1.6 }}>{cap}</div>
      </div>
      <Scale {...scale} />
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, borderTop: `1px solid ${P.line}`, paddingTop: 12 }}>
        <span style={{ flex: 1, fontSize: 13.5, color: P.ink2 }}>商家到手</span>
        <Amount v={got} size={26} color={gotColor} />
      </div>
      <div style={{ fontSize: 12, color: P.ink3, lineHeight: 1.6 }}>{note}</div>
    </div>
  )
}

const Dot = ({ color, opacity = 1 }) => (
  <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: 2, background: color, opacity, marginRight: 5 }} />
)

export default function MerchantSplitFilm() {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.6 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 720

  // 别处:20% 的条 + 「¥4 多」「不到 ¥17」
  const kElse = tween(T, { to: 0.2, start: CUE.elsewhere + 0.5, end: CUE.elsewhere + 1.7 })
  const elseCut = T > CUE.elsewhere + 1.0 ? ELSE_CUT : '−¥0'
  const elseGot = T > CUE.elsewhere + 1.9 ? ELSE_GOT : '¥21.00'
  // 这里:5% 的条 + 到手 ¥19.95 滚下来(账本 900ms)
  const kHere = tween(T, { to: 0.05, start: CUE.here + 0.5, end: CUE.here + 1.7 })
  const cutHere = tween(T, { to: 1.05, start: CUE.here + 0.6, end: CUE.here + 1.5 })
  const gotHere = tween(T, { from: 21, to: 19.95, start: CUE.here + 0.9, end: CUE.here + 1.8 })
  // 菜价下划线、分账条(商家 / 骑手半透 / 平台)
  const ul = tween(T, { start: CUE.bill + 1.1, end: CUE.bill + 1.7 })
  const g = tween(T, { start: CUE.here + 1.6, end: CUE.here + 2.5 })
  const capIdx = T >= CUE.close ? 3 : T >= CUE.here ? 2 : T >= CUE.elsewhere ? 1 : 0

  return (
    <Film film={film} label="示例 · 同一笔外卖单" loop="循环 · 15 秒"
      summary="示例动画：同一笔 26 元的外卖单，菜价 21 元、配送费 5 元。行业平台商家总负担普遍 20% 以上，这一单要被拿走 4 元多，商家到手不到 17 元；在这里只收菜价的 5%，也就是 1.05 元，商家到手 19.95 元，配送费一分不抽。同一单差 3 元多。"
      style={{ background: P.card, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      {/* 小票:一单 ¥26 */}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: narrow ? 16 : 28, flexWrap: 'wrap', ...enter(T, CUE.bill) }}>
        <div>
          <div style={{ position: 'relative', display: 'inline-block' }}>
            <Amount v="¥26.00" size={narrow ? 34 : 42} />
            <span style={{ position: 'absolute', left: 0, bottom: -2, height: 2, width: `${ul * 100}%`, background: P.claySoft }} />
          </div>
          <div style={{ fontSize: 12.5, color: P.ink2, marginTop: 4 }}>牛肉面 ×1、卤蛋 ×2 · 菜价 ¥21 + 配送费 ¥5</div>
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ display: 'flex', height: 10, gap: 2, borderRadius: 999, overflow: 'hidden' }}>
            <span style={{ flexGrow: g * 1995, flexBasis: 0, background: P.earn }} />
            <span style={{ flexGrow: g * 500, flexBasis: 0, background: P.earn, opacity: 0.5 }} />
            <span style={{ flexGrow: g * 105, flexBasis: 0, background: P.hold }} />
            <span style={{ flexGrow: (1 - g) * 2600, flexBasis: 0, background: P.line }} />
          </div>
          <div style={{ display: 'flex', gap: 14, marginTop: 8, fontSize: 11.5, color: P.ink2, flexWrap: 'wrap', opacity: g }}>
            <span><Dot color={P.earn} />商家 ¥19.95</span>
            <span><Dot color={P.earn} opacity={0.5} />骑手 ¥5.00</span>
            <span><Dot color={P.hold} />平台 ¥1.05</span>
          </div>
        </div>
      </div>

      {/* 两边同一把尺 */}
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : '1fr 1fr', gap: 14, alignItems: 'stretch' }}>
        <Side T={T} at={CUE.elsewhere} title="行业平台 · 同一单" cap="佣金、推广位、活动摊派，一层层加上去"
          scale={{ k: kElse, color: '#C9C3B4', label: '平台从这一单拿走', amount: elseCut, tone: P.ink2 }}
          got={elseGot} gotColor={P.ink2} bg={P.alt} border="1px solid transparent"
          note="「20%+」是行业普遍口径，不是某一家的实数 —— 我们不替别人编小数点。" />
        <Side T={T} at={CUE.here} title="在这里 · 同一单" cap="只收菜价的 5%，配送费和小费一分不抽"
          scale={{ k: kHere, color: P.hold, label: '平台从这一单拿走', amount: `−${yuan(cutHere)}`, tone: P.hold }}
          got={yuan(gotHere)} gotColor={P.earn} bg={P.card} border={`1px solid ${P.line}`}
          note="没有入驻费、没有推广位；保证金 ¥500 从营收里留存，退店无纠纷全额退。" />
      </div>

      {/* 差额 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
        padding: '12px 16px', borderRadius: 10, background: P.claySoft,
        ...pop(T, CUE.gap), transformOrigin: 'left center',
      }}>
        <Amount v={GAP} size={22} color={P.clay} />
        <span style={{ fontSize: 13.5, color: P.ink, flex: 1, minWidth: 180 }}>
          同一单的差额。一天 40 单，就是一百多块 —— 不是运气，是费率。
        </span>
      </div>

      <Caption title={CAPS[capIdx]} narrow={narrow} minDetail={0}
        detail={<span style={{ opacity: tween(T, { start: CUE.close + 0.3, end: CUE.close + 0.9 }) }}>5% 是上限，不是目标。哪天 3% 能活，就降到 3%。</span>}
        detailColor={P.ink2} />
    </Film>
  )
}
