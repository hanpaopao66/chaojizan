import React from 'react'

import { Ease, FILL, Film, MONO, P, SERIF, clamp, tween, useFilm, yuan } from './kit.jsx'

/* 动效规范的六格演示(品牌物料页「动效」一栏)。每格一个小循环,互不对齐。
 *
 * 规范以 packages/shared/lib/src/motion.dart 为准:
 *   时长 120 fast / 220 base / 320 slow / 900 ledger
 *   曲线 standard (.2,.8,.2,1) · spring (.34,1.3,.64,1) · exit (.4,0,1,1)
 *   列表错落 40ms、最多 6 项;骑手端不回弹;消失比出现快
 * 唯一允许的慢动作是账本数字和分账条 —— 因为钱要看清。
 *
 * 和原稿不一样(原稿按设计稿画,这里照三端代码里真实的样子演):
 * - 骨架屏原稿是一道光扫过去(1.2s)。App 里的 SkeletonList 是整块透明度
 *   .35 ↔ .75 呼吸、900ms 往返,照这个演;
 * - 成功态原稿是描一圈再打勾。App 里的 SzSuccessSwap 是按钮 120ms 淡出、
 *   成功块 .8 → 1 弹出来(用户 / 商家 320ms spring,骑手 220ms standard);
 * - 账本数字原稿每圈从 0 滚到 ¥1,846.50,底下却写着「不从 0 重播」。
 *   改成进来一单、从旧值滚到新值;
 * - 状态推进的点原稿是 1 → 1.3 鼓一下。SzProgressRail 是线段先画满(220ms),
 *   终点圆再 .6 → 1(120ms spring);
 * - 每格循环回头时先按 exit 曲线淡出,不是一下子消失。 */

const TOTAL = 9.6 // 2.4 / 3.2 / 4.8 都能整除,六格各自的小循环都对得上

/** 0 → 1 → 0 的三角波,半个周期 half 秒(AnimationController.repeat(reverse: true) 的线性往返) */
const tri = (u, half) => {
  const x = (u / half) % 2
  return x < 1 ? x : 2 - x
}

function Tile({ title, spec, children }) {
  return (
    <div style={{ background: P.card, border: `1px solid ${P.line}`, borderRadius: 12, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div aria-hidden="true" style={{ background: P.paper, padding: 16, minHeight: 132, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        {children}
      </div>
      <div style={{ padding: '11px 14px', borderTop: `1px solid ${P.line}` }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{title}</div>
        <div style={{ fontFamily: MONO, fontSize: 11.5, color: P.ink3, whiteSpace: 'pre-line', marginTop: 2, lineHeight: 1.5 }}>{spec}</div>
      </div>
    </div>
  )
}

const STEPS = ['已接单', '已取餐', '配送中', '送达']
const STEP_AT = [0.5, 1.4, 2.3, 3.2]
const STEP_TEXT = ['已接单', '已取餐', '配送中 · 约 8 分钟', '已送达']

export default function SzMicroKit() {
  const film = useFilm(TOTAL, { still: 0, poster: 0.2 })
  const { T, reduced } = film
  /** 这一格此刻的相位。减少动态效果时停在各自的「结果」那一刻 */
  const at = (cycle, off, still) => (reduced ? still : (T + off) % cycle)

  // 1 卡片入场:透明度 standard、位移 spring,220ms,错落 40ms
  const u1 = at(3.2, 0, 2.4)
  const out1 = tween(u1, { start: 2.9, end: 3.03, ease: Ease.exit })
  // 2 骨架 → 内容
  const u2 = at(4.8, 1.1, 4.0)
  const skel = u2 < 2.7
  const k2 = tween(u2, { start: 2.7, end: 2.92 })
  const out2 = tween(u2, { start: 4.65, end: 4.78, ease: Ease.exit })
  // 3 成功态:按下 .97(120ms)→ 按钮淡出(120ms)→ 成功块 .8→1(320ms spring)
  const u3 = at(2.4, 0.6, 1.8)
  const btn3 = tween(u3, { start: 0, end: 0.12 }) * (1 - tween(u3, { start: 0.62, end: 0.74 }))
  const k3 = tween(u3, { start: 0.62, end: 0.94, ease: Ease.spring })
  const out3 = tween(u3, { start: 2.22, end: 2.35, ease: Ease.exit })
  // 4 账本数字:进来一单,从旧值滚到新值,900ms standard
  const u4 = at(3.2, 1.6, 2.6)
  const n4 = tween(u4, { from: 1826.55, to: 1846.5, start: 0.4, end: 1.3 })
  const vis4 = tween(u4, { start: 0, end: 0.12 }) * (1 - tween(u4, { start: 3.07, end: 3.2, ease: Ease.exit }))
  // 5 分账条:900ms standard,段间 120ms
  const u5 = at(4.8, 2.4, 3.6)
  const g5 = i => tween(u5, { start: 0.4 + i * 0.12, end: 1.3 + i * 0.12 })
  const out5 = tween(u5, { start: 4.62, end: 4.75, ease: Ease.exit })
  // 6 状态推进:线 220ms standard → 终点圆 .6→1 120ms spring
  const u6 = at(4.8, 0.3, 4.2)
  const cur6 = STEP_AT.reduce((c, a, i) => (u6 >= a ? i : c), -1)
  const out6 = tween(u6, { start: 4.62, end: 4.75, ease: Ease.exit })
  const text6 = cur6 < 0 ? 0 : tween(u6, { start: STEP_AT[cur6], end: STEP_AT[cur6] + 0.22 })

  return (
    <Film film={film} label="三端动效规范 · 六格演示" loop="各自循环" gap={14}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 12 }}>

        <Tile title="卡片入场 / 页面切换" spec={'220ms · 位移 spring、透明度 standard\n错落 40ms，最多 6 项；骑手端不回弹'}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7, opacity: 1 - out1 }}>
            {[[P.bowl, '点外卖', '5%'], [P.run, '帮我送', '2%'], [P.voucher, '超值团购', '2%']].map((c, i) => {
              const s = 0.3 + i * 0.04
              const op = tween(u1, { start: s, end: s + 0.22 })
              const y = tween(u1, { start: s, end: s + 0.22, ease: Ease.spring })
              return (
                <div key={c[1]} style={{
                  background: P.card, border: `1px solid ${P.line}`, borderRadius: 10, overflow: 'hidden',
                  opacity: op, transform: `translateY(${(1 - y) * 12}px)`,
                }}>
                  <div style={{ height: 3, background: c[0] }} />
                  <div style={{ padding: '7px 10px', display: 'flex', fontSize: 12 }}>
                    <span style={{ flex: 1, fontWeight: 600 }}>{c[1]}</span>
                    <span style={{ fontFamily: SERIF, fontWeight: 600, color: P.hold }}>{c[2]}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </Tile>

        <Tile title="骨架加载 → 内容" spec={'骨架 .35 ↔ .75 呼吸，900ms 往返\n内容进场 220ms standard'}>
          <div style={{ background: P.card, border: `1px solid ${P.line}`, borderRadius: 10, padding: '11px 12px', minHeight: 84 }}>
            {skel ? (
              <div style={{ display: 'flex', gap: 10, opacity: 0.35 + 0.4 * tri(u2, 0.9) }}>
                <div style={{ width: 44, height: 44, borderRadius: 8, background: P.line, flex: 'none' }} />
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8, paddingTop: 2 }}>
                  {[70, 100, 45].map(wd => (
                    <div key={wd} style={{ height: 10, width: `${wd}%`, borderRadius: 3, background: P.line }} />
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 10, opacity: k2 * (1 - out2), transform: `translateY(${(1 - k2) * 6}px)` }}>
                <div style={{ width: 44, height: 44, borderRadius: 8, background: 'rgba(148,63,47,.12)', color: P.bowl, flex: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: "'SzSerifCJK','PingFang SC',serif", fontWeight: 600, fontSize: 18 }}>碗</div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>张记面馆</div>
                  <div style={{ fontSize: 11.5, color: P.ink2, marginTop: 2 }}>210m · 4.8 分 · 配送费 ¥5</div>
                  <div style={{ fontSize: 11.5, color: P.earn, marginTop: 4 }}>本店仅被抽成 5%</div>
                </div>
              </div>
            )}
          </div>
        </Tile>

        <Tile title="成功态" spec={'按钮 120ms 淡出 → 成功块 .8 → 1\n320ms spring；骑手端 220ms standard'}>
          <div style={{ position: 'relative', height: 56, opacity: 1 - out3 }}>
            <div style={{
              ...FILL, borderRadius: 10, background: P.clay, color: P.card,
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 600,
              opacity: btn3, transform: u3 > 0.5 && u3 < 0.62 ? 'scale(.97)' : 'scale(1)',
            }}>提现 {yuan(180)}</div>
            <div style={{
              ...FILL, borderRadius: 10, background: 'rgba(78,107,79,.12)',
              display: 'flex', alignItems: 'center', gap: 12, padding: '0 14px',
              opacity: clamp(k3 * 2, 0, 1), transform: `scale(${0.8 + 0.2 * k3})`,
            }}>
              <span style={{ width: 26, height: 26, borderRadius: '50%', background: P.earn, color: P.card, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, flex: 'none' }}>✓</span>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: P.earn }}>提现已提交</div>
                <div style={{ fontSize: 11.5, color: P.ink2 }}>T+1 到卡 · 零手续费</div>
              </div>
            </div>
          </div>
        </Tile>

        <Tile title="账本数字滚动" spec={'900ms standard\n等宽数字，滚动时不跳宽'}>
          <div style={{ opacity: vis4 }}>
            <div style={{ fontSize: 11, letterSpacing: 1.2, color: P.ink2 }}>今日实收 · 菜价 − 5%</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 32, fontVariantNumeric: 'tabular-nums', lineHeight: 1.25 }}>{yuan(n4)}</span>
              <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 13, color: P.earn, opacity: tween(u4, { start: 0.3, end: 0.5 }) }}>+¥19.95</span>
            </div>
            <div style={{ fontSize: 11.5, color: P.ink3 }}>进来一单，从旧值滚到新值，不从 0 重播</div>
          </div>
        </Tile>

        <Tile title="分账条生长" spec={'900ms standard\n段间错开 120ms'}>
          <div style={{ opacity: 1 - out5 }}>
            <div style={{ display: 'flex', height: 12, gap: 3, borderRadius: 999, overflow: 'hidden' }}>
              <span style={{ flexGrow: g5(0) * 1995, flexBasis: 0, background: P.earn }} />
              <span style={{ flexGrow: g5(1) * 500, flexBasis: 0, background: P.earn, opacity: 0.5 }} />
              <span style={{ flexGrow: g5(2) * 105, flexBasis: 0, background: P.hold }} />
              <span style={{ flexGrow: 2600 - g5(0) * 1995 - g5(1) * 500 - g5(2) * 105, flexBasis: 0, background: P.line }} />
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: 9, fontSize: 11.5, color: P.ink2, flexWrap: 'wrap' }}>
              <span>商家 ¥19.95</span><span>骑手 ¥5.00</span><span>平台 ¥1.05</span>
            </div>
            <div style={{ fontSize: 11, color: P.ink3, marginTop: 4 }}>段宽直接用金额，不做「最小可见宽度」</div>
          </div>
        </Tile>

        <Tile title="订单状态推进" spec={'线 220ms standard → 点 .6 → 1\n120ms spring；文字交叉淡入 220ms'}>
          <div style={{ opacity: 1 - out6 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: cur6 === 3 ? P.earn : P.clay, minHeight: 20, opacity: text6 }}>
              {cur6 < 0 ? '' : STEP_TEXT[cur6]}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', fontSize: 11, color: P.ink3, marginTop: 10 }}>
              {STEPS.map((n, i) => {
                const reached = u6 >= STEP_AT[i]
                const cur = i === cur6
                const line = i > 0 ? tween(u6, { start: STEP_AT[i], end: STEP_AT[i] + 0.22 }) : 1
                const dotAt = STEP_AT[i] + (i > 0 ? 0.22 : 0)
                const dot = reached ? 0.6 + 0.4 * tween(u6, { start: dotAt, end: dotAt + 0.12, ease: Ease.spring }) : 1
                const lit = reached && u6 >= dotAt
                return (
                  <React.Fragment key={n}>
                    {i > 0 && (
                      <span style={{ flex: 1, height: 2, background: P.line, margin: '0 5px', position: 'relative', overflow: 'hidden' }}>
                        <span style={{ ...FILL, background: P.earn, transformOrigin: 'left', transform: `scaleX(${reached ? line : 0})` }} />
                      </span>
                    )}
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: lit ? (cur ? P.clay : P.earn) : P.ink3, fontWeight: lit && cur ? 600 : 400 }}>
                      <span style={{
                        width: 7, height: 7, borderRadius: 4, background: lit ? (cur ? P.clay : P.earn) : P.line,
                        transform: `scale(${lit ? dot : 1})`,
                      }} />{n}
                    </span>
                  </React.Fragment>
                )
              })}
            </div>
          </div>
        </Tile>

      </div>
    </Film>
  )
}
