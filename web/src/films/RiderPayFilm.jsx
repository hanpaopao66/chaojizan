import React from 'react'

import { Amount, Caption, Ease, Film, P, SERIF, enter, tween, useFilm, useWidth, yuan } from './kit.jsx'

/* 骑手加入页(/join/rider)的到账片:用户付的配送费,一分不少到你手里。
 * 放在三条规矩上面,原来右边那张「示例 · 一位骑手的午高峰」由它接管。
 *
 * 口径同骑手页:配送费与小费 100% 归骑手,平台不抽;只有帮我送 / 帮我买
 * 收跑腿费的 2%(账单单列一行)。示例账那四单就是原来那张卡上的四单:
 *   11:52 ¥5.00 · 12:10 ¥6.00 · 12:31 帮我送 ¥12 − 2% = ¥11.76 · 12:55 ¥5.00,合计 ¥27.76
 * 订单完成钱进 App 钱包,骑手自己提现(最低 ¥10),T+1 到卡、零手续费 ——
 * 没有「当天 22:00 结到卡」这回事。 */

// @serif-cjk-begin
const CAPS = [
  '顾客付了 ¥5 配送费。',
  '经过平台 —— 一分不少。',
  '订单完成就进你的钱包。',
  '用户付的配送费，一分不少到你手里。',
]
// @serif-cjk-end

const CUE = { pay: 0.3, fly: 1.6, land: 5.4, day: 6.0, cash: 10.8, close: 13.2 }
const TOTAL = 15.6
const STILL = 14.2

/* 分 → 行。第四列是那一单底下补的小字 */
const DAY = [
  ['11:52', '张记面馆 → 高新路 · 1.8km', 500, null],
  ['12:10', '李婶砂锅粥 → 阳光花园 · 2.4km', 600, null],
  ['12:31', '帮我送 · 文件 · 3.2km', 1176, '跑腿费 ¥12.00 − 2% ¥0.24，账单上单列一行'],
  ['12:55', '川香居 → 学府街 · 1.1km', 500, null],
]
const DAY_TOTAL = DAY.reduce((s, r) => s + r[2], 0) / 100

export default function RiderPayFilm() {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.6 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 760

  // ¥5 沿虚线从「顾客付」走到「你的钱包」,中途过平台闸口,金额不变
  const k = tween(T, { start: CUE.fly, end: CUE.fly + 3.2, ease: Ease.inOut })
  const atGate = k > 0.42 && k < 0.62
  const landed = T >= CUE.land
  const wallet = tween(T, { to: 5, start: CUE.land, end: CUE.land + 0.9 })
  const total = T >= CUE.day + 1.6
    ? tween(T, { from: 5, to: DAY_TOTAL, start: CUE.day + 1.6, end: CUE.day + 2.5 })
    : wallet
  const capIdx = T >= CUE.close ? 3 : T >= CUE.land ? 2 : T >= CUE.fly + 1.2 ? 1 : 0

  return (
    <Film film={film} label="示例 · 一笔配送费的全程" loop="循环 · 15 秒"
      summary={`示例动画：顾客付的 5 元配送费经过平台，平台抽成 0%，订单完成后 5 元全部进骑手钱包。示例的午高峰四单合计 ${DAY_TOTAL.toFixed(2)} 元，其中帮我送那单跑腿费 12 元、平台收 2% 即 0.24 元。提现最低 10 元，T+1 到卡，零手续费；晚到不罚钱。`}
      style={{ background: P.card, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      {/* 轨道:顾客付 → 平台闸口 → 你的钱包 */}
      <div style={{ position: 'relative', height: 96, ...enter(T, CUE.pay) }}>
        <div style={{
          position: 'absolute', left: 0, right: 0, top: 52, height: 2,
          background: `repeating-linear-gradient(90deg,${P.line} 0 6px,transparent 6px 12px)`,
        }} />
        <div style={{
          position: 'absolute', left: '50%', top: 20, transform: 'translateX(-50%)',
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
        }}>
          <div style={{
            padding: '5px 12px', borderRadius: 8, border: `1px solid ${atGate ? P.clay : P.line}`,
            background: P.card, fontSize: 12, color: atGate ? P.clay : P.ink2,
            fontWeight: atGate ? 600 : 400, whiteSpace: 'nowrap',
          }}>平台 · 抽成 0%</div>
          <div style={{ width: 1, height: 22, background: P.line }} />
          <Amount v="−¥0.00" size={12.5} color={P.ink3} weight={400} />
        </div>
        <div style={{ position: 'absolute', left: 0, top: 66, fontSize: 12, color: P.ink2 }}>顾客付 · 配送费</div>
        <div style={{ position: 'absolute', right: 0, top: 66, fontSize: 12, color: P.ink2, textAlign: 'right' }}>你的钱包</div>
        {/* 走在轨道上的金额(74 ≈ 这颗胶囊的宽度,走到头时右边贴齐) */}
        <div style={{
          position: 'absolute', top: 36, left: `calc(${k * 100}% - ${k * 74}px)`,
          padding: '5px 12px', borderRadius: 999, background: P.earn, color: P.card,
          fontSize: 14, fontWeight: 600, fontFamily: SERIF, fontVariantNumeric: 'tabular-nums',
          boxShadow: '0 6px 18px rgba(78,107,79,.22)', opacity: landed ? 0 : 1,
        }}>¥5.00</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : 'minmax(0,1fr) 300px', gap: 16, alignItems: 'start' }}>
        {/* 一天的示例账 */}
        <div style={{ border: `1px solid ${P.line}`, borderRadius: 12, overflow: 'hidden', background: P.card, ...enter(T, CUE.day - 0.4) }}>
          <div style={{ height: 3, background: P.run }} />
          <div style={{ padding: '14px 16px' }}>
            <div style={{ fontSize: 11, letterSpacing: 1.2, color: P.ink2 }}>示例 · 一位骑手的午高峰（四单，不是真实账单）</div>
            <div style={{ display: 'flex', flexDirection: 'column', fontSize: 13.5, marginTop: 6 }}>
              {DAY.map((r, i) => {
                const at = CUE.day + 0.2 + i * 0.34
                return (
                  <div key={r[0]} style={{ borderTop: `1px solid ${P.line}`, padding: '9px 0', ...enter(T, at, 0.22) }}>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
                      <span style={{ width: 42, flex: 'none', color: P.ink2, fontSize: 12.5 }}>{r[0]}</span>
                      <span style={{ flex: 1, minWidth: 0 }}>{r[1]}</span>
                      <Amount v={yuan(r[2] / 100)} size={14} color={P.earn} />
                    </div>
                    {r[3] && (
                      <div style={{ fontSize: 12, color: P.ink3, marginLeft: 52, marginTop: 3, opacity: tween(T, { start: at + 0.4, end: at + 0.9 }) }}>
                        {r[3]}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* 钱包 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ background: P.ledger, color: P.dtext, borderRadius: 12, padding: '16px 18px' }}>
            <div style={{ fontSize: 10.5, letterSpacing: 1, color: P.dmute }}>钱包 · 今日所得</div>
            <div style={{ marginTop: 4 }}>
              <Amount v={yuan(total)} size={34} color={total > 0 ? P.dearn : P.dmute} weight={total > 0 ? 600 : 400} />
            </div>
            <div style={{ fontSize: 12, color: P.dmute, marginTop: 6, lineHeight: 1.6 }}>配送费与小费 100% 归你 · 平台不抽</div>
          </div>
          <div style={{
            border: `1px solid ${P.line}`, borderRadius: 12, padding: '14px 16px',
            fontSize: 12.5, color: P.ink2, lineHeight: 1.7, ...enter(T, CUE.cash),
          }}>
            <div style={{ color: P.ink, fontSize: 13.5, fontWeight: 600, marginBottom: 4 }}>提现</div>
            最低 ¥10，自己点提现 · T+1 到卡 · 零手续费
            <div style={{ color: P.ink, fontSize: 13.5, fontWeight: 600, margin: '10px 0 4px' }}>超时不罚钱</div>
            晚到超过 15 分钟，平台自己给顾客发 ¥3 券，不扣你的钱
          </div>
        </div>
      </div>

      <Caption title={CAPS[capIdx]} narrow={narrow} minDetail={0} detailColor={P.ink2}
        detail={<span style={{ opacity: tween(T, { start: CUE.close + 0.3, end: CUE.close + 0.9 }) }}>抢单不派单，不接不扣分。每一单在透明中心的「今日逐单」里都有一行（脱敏）。</span>} />
    </Film>
  )
}
