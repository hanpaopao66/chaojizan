import React from 'react'

import { CHANNELS, STATE_LABEL } from '../SiteChrome.jsx'
import { Caption, Ease, FILL, Film, P, SERIF, clamp, enter, pop, tween, useFilm, useWidth } from './kit.jsx'

/* 首页首屏之下的第一支:一个 App 干完这些事,底下是同一份账。
 * 先说清「这是个什么东西」,再往下才是流程片、费率和账本。
 *
 * 八格 = 六个频道(SiteChrome 的 CHANNELS = channels.dart,打车还在筹备)+ 消息 + 视频。
 * 左边「通常的情形」是常识性的通用描述,不点名、不画任何一家的界面。
 *
 * 开没开照实画(同费率片):频道读 /channels,视频读 /config 的 features ——
 * 都由页面传进来。没开的格子压成弱色、写「暂未开放」;打车写「筹备中」。
 *
 * 和原稿不一样(按代码核过):
 * - 原稿写「同一个钱包」「要充的钱包 6 → 1」。用户端没有钱包、余额,也不能充值:
 *   每单单独付,退款原路退回。这一格换成「要弄懂的规则 6 → 1」(左边那句「六套规则」,
 *   这里是一张费率表加三端公开的规则);
 * - 原稿写「同一条消息流」。住宿、团购的消息不进「消息」tab,不写;
 * - 原稿写「八件事用同一张费率表、同一个公开账本、同一套核账」「换哪个频道下单,
 *   分账条的算法都不变」。消息、视频不收钱,打车没做;跑腿、住宿、团购的分账各走
 *   各的分支,跑腿那 2% 也不在锚点里。能照实说的是:五个频道一张费率表、
 *   每天 04:00 同一套核账。分账条那一行改成标明示例的那一单;
 * - 收拢后的「超级赞」原稿接在六格下面另起一行,出现那一刻片子高 60 多像素 ——
 *   手机上左栏在最上面,整页往下一跳。改成落在六格收拢到的那个位置,片子高度不变。 */

// @serif-cjk-begin
const TITLES = [
  '六件事，六个 App。',
  '一个 App，八件事。',
  '聚合不是把图标堆在一起。',
]
const BRAND = '超级赞'
const EXTRA_GLYPH = { chat: '话', video: '影' }
// @serif-cjk-end

/* 字幕底下那行说明(黑体,不进衬线子集) */
const DETAILS = [
  '各有各的账号、各有各的规则、各有各的客服入口，还有各自看不到的抽成。',
  '六个频道 + 消息 + 视频（打车还在筹备）。一个账号登录，一个地方找客服。',
  '是底下只有一份账 —— 五个频道一张费率表，每天 04:00 同一套核账逐笔核一遍；消息和视频不收钱。',
]

/* 左边:六件事,通常分散在六个地方 */
const SCATTER = ['点外卖', '买菜', '订房', '团购', '跑腿', '打车']

/* 右边频道格子第三行:费率(同费率表) */
const RATE = { food: '5%', retail: '5%', stay: '5%', voucher: '2%', errand: '2%' }

/* 6 → 1。「找客服的地方」:三端「找平台」的入口最后都落到同一个工单页(support_page.dart) */
const COUNTS = [
  ['要装的 App', '个'],
  ['要记的账号', '个'],
  ['要弄懂的规则', '套'],
  ['找客服的地方', '个'],
]

const CUE = { scatter: 0.3, pain: 2.2, collapse: 4.6, app: 5.6, parts: 6.5, counts: 10.0, ledger: 12.6, close: 14.6 }
const TOTAL = 18.6
/** 静帧:收拢完、八格和四个计数都落定、账本那块和收尾那句都已出 */
const STILL = 15.4

const TILE_H = 66
const GAP = 10

/** 缩成单色的品牌标(同 BrandSvg 的 Mark,去掉底板和三道横线) */
const MonoMark = ({ size = 26 }) => (
  <svg width={size} height={size} viewBox="0 0 512 512" aria-hidden="true">
    <rect x="108" y="246" width="64" height="168" rx="22" fill={P.clay} />
    <path d="M 244 300 C 239 258 237 234 233 212 C 229 190 224 174 215 154" fill="none" stroke={P.clay} strokeWidth="68" strokeLinecap="round" strokeLinejoin="round" />
    <rect x="190" y="246" width="204" height="168" rx="36" fill={P.clay} />
  </svg>
)

export default function SuperAppFilm({ stateOf, features }) {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.5 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 820
  // 左栏三列格子的宽:宽屏定宽 96;窄屏按栏宽分(片子左右内边距 16 + 边框 1、左栏内边距 18)
  const tileW = narrow && w > 0 ? Math.max(72, Math.min(96, (w - 34 - 36 - GAP * 2) / 3)) : 96

  const parts = [
    ...CHANNELS.map(ch => {
      const state = ch.coming ? 'coming' : (stateOf ? stateOf(ch.key) : 'open')
      return {
        key: ch.key, glyph: ch.glyph, name: ch.fullName ?? ch.name, color: ch.color, tint: ch.tint,
        off: state !== 'open', sub: state === 'open' ? RATE[ch.key] : STATE_LABEL[state], rate: state === 'open',
      }
    }),
    { key: 'chat', glyph: EXTRA_GLYPH.chat, name: '消息', color: P.clay, tint: 'rgba(193,95,60,.12)',
      off: features?.chat === false, sub: features?.chat === false ? STATE_LABEL.closed : '会话', rate: false },
    { key: 'video', glyph: EXTRA_GLYPH.video, name: '视频', color: P.clay, tint: 'rgba(193,95,60,.12)',
      off: !features?.video, sub: features?.video ? '看了能点' : STATE_LABEL.closed, rate: false },
  ]
  const capIdx = T >= CUE.counts ? 2 : T >= CUE.app ? 1 : 0

  return (
    <Film film={film} label="一个 App 干完这些事" loop="循环 · 19 秒"
      summary="示意动画：点外卖、买菜、订房、团购、跑腿、打车，通常分散在六个 App 里，各有各的账号、规则和客服入口。在这里收进一个 App：六个频道加上消息和视频，打车还在筹备；一个账号，一套规则，一个地方找客服。五个频道底下是同一份账：同一张费率表，每天 04:00 同一套核账；消息和视频不收钱。"
      style={{ background: P.card, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : 'auto minmax(0,1fr)', gap: 20, alignItems: 'start' }}>

        {/* 左:散开的六个,收拢成一个 */}
        <div style={{ background: P.alt, borderRadius: 12, padding: '16px 18px', ...enter(T, CUE.scatter) }}>
          <div style={{ fontSize: 11, letterSpacing: 1.2, color: P.ink2 }}>通常的情形</div>
          <div style={{ position: 'relative', marginTop: 12, display: 'grid', gridTemplateColumns: `repeat(3, ${tileW}px)`, gap: GAP, justifyContent: 'center' }}>
            {/* 收拢后落下的那一个:就落在六格收拢到的位置 */}
            {T >= CUE.app && (
              <div style={{ ...FILL, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 9, padding: '9px 16px', borderRadius: 12, background: P.claySoft, ...pop(T, CUE.app) }}>
                  <MonoMark />
                  <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 17, color: P.clay }}>{BRAND}</span>
                </span>
              </div>
            )}
            {SCATTER.map((s, i) => {
              const col = i % 3
              const row = Math.floor(i / 3)
              const at = CUE.scatter + 0.3 + i * 0.22
              const k = tween(T, { start: at, end: at + 0.3, ease: Ease.spring })
              const c = tween(T, { start: CUE.collapse + i * 0.07, end: CUE.collapse + 0.9 + i * 0.07, ease: Ease.inOut })
              const dx = (1 - col) * (tileW + GAP) * c
              const dy = (0.5 - row) * (TILE_H + GAP) * c
              return (
                <div key={s} style={{
                  height: TILE_H, borderRadius: 10, background: P.card, border: '1px dashed #CFCABD',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 3,
                  opacity: clamp(k * 1.5, 0, 1) * (1 - c),
                  transform: `translate(${dx}px,${dy}px) scale(${(0.88 + 0.12 * k) * (1 - 0.55 * c)})`,
                }}>
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: P.ink2 }}>{s}</span>
                  <span style={{
                    fontSize: 9.5, color: P.ink3, textAlign: 'center', lineHeight: 1.4,
                    opacity: tween(T, { start: CUE.pain + i * 0.12, end: CUE.pain + 0.4 + i * 0.12 }),
                  }}>账号 · 规则 · 客服</span>
                </div>
              )
            })}
          </div>
          <div style={{
            marginTop: 12, fontSize: 11.5, color: P.ink3, lineHeight: 1.6, textAlign: 'center',
            opacity: tween(T, { start: CUE.pain + 0.9, end: CUE.pain + 1.4 }) * (1 - tween(T, { start: CUE.collapse, end: CUE.collapse + 0.6, ease: Ease.exit })),
          }}>
            六套规则，六处抽成，没有一处告诉你抽了多少。
          </div>
        </div>

        {/* 右:八件事 + 计数 + 同一份账 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'repeat(2, minmax(0,1fr))' : 'repeat(4, minmax(0,1fr))', gap: 9 }}>
            {parts.map((p, i) => {
              const at = CUE.parts + i * 0.16
              const k = tween(T, { start: at, end: at + 0.3, ease: Ease.spring })
              return (
                <div key={p.key} style={{
                  border: `1px ${p.off ? 'dashed' : 'solid'} ${p.off ? '#D3CEC2' : P.line}`, borderRadius: 10, padding: '10px 11px',
                  display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0,
                  opacity: clamp(k * 1.5, 0, 1), transform: `scale(${0.9 + 0.1 * k})`,
                }}>
                  <span style={{
                    width: 26, height: 26, borderRadius: 8, background: p.off ? P.alt : p.tint, color: p.off ? P.ink3 : p.color,
                    fontFamily: "'SzSerifCJK','PingFang SC',serif", fontWeight: 600, fontSize: 13, lineHeight: 1,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>{p.glyph}</span>
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: p.off ? P.ink3 : P.ink, lineHeight: 1.35 }}>{p.name}</span>
                  <span style={{
                    fontSize: 11, color: p.off ? P.ink3 : P.hold,
                    fontFamily: p.rate ? SERIF : undefined, fontWeight: p.rate ? 600 : 400,
                  }}>{p.sub}</span>
                </div>
              )
            })}
          </div>

          {/* 计数 6 → 1 */}
          <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'repeat(2, minmax(0,1fr))' : 'repeat(4, minmax(0,1fr))', gap: 9 }}>
            {COUNTS.map(([label, unit], i) => {
              const at = CUE.counts + i * 0.3
              const v = tween(T, { from: 6, to: 1, start: at, end: at + 0.9 })
              return (
                <div key={label} style={{ background: P.alt, borderRadius: 10, padding: '11px 12px', ...enter(T, at - 0.2, 0.28) }}>
                  <div style={{ fontSize: 11, color: P.ink2 }}>{label}</div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 2 }}>
                    <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 26, fontVariantNumeric: 'tabular-nums', color: T >= at + 0.9 ? P.clay : P.ink2 }}>{Math.round(v)}</span>
                    <span style={{ fontSize: 12, color: P.ink2 }}>{unit}</span>
                  </div>
                </div>
              )
            })}
          </div>

          {/* 同一份账 */}
          <div style={{ background: P.ledger, borderRadius: 12, padding: '15px 17px', ...enter(T, CUE.ledger) }}>
            <div style={{ fontSize: 10.5, letterSpacing: 1, color: P.dmute }}>五个频道，底下是同一份账</div>
            <div style={{ display: 'flex', gap: 16, marginTop: 9, flexWrap: 'wrap' }}>
              {[['一张费率表', '/rates'], ['一套核账', '每天 04:00'], ['一个透明中心', '/transparency']].map(([t, d], i) => (
                <span key={t} style={{
                  display: 'flex', flexDirection: 'column', gap: 2,
                  opacity: tween(T, { start: CUE.ledger + 0.3 + i * 0.25, end: CUE.ledger + 0.7 + i * 0.25 }),
                }}>
                  <span style={{ fontSize: 13.5, color: P.dtext, fontWeight: 600 }}>{t}</span>
                  <span style={{ fontSize: 11, color: P.dmute, fontFamily: SERIF }}>{d}</span>
                </span>
              ))}
            </div>
            <div style={{
              display: 'flex', height: 8, gap: 3, marginTop: 13, borderRadius: 999, overflow: 'hidden',
              opacity: tween(T, { start: CUE.ledger + 0.9, end: CUE.ledger + 1.5 }),
            }}>
              <span style={{ flexGrow: 1995, flexBasis: 0, background: P.dearn }} />
              <span style={{ flexGrow: 500, flexBasis: 0, background: P.dearn, opacity: 0.5 }} />
              <span style={{ flexGrow: 105, flexBasis: 0, background: P.dgold }} />
            </div>
            <div style={{ fontSize: 11.5, color: P.dmute, marginTop: 7, opacity: tween(T, { start: CUE.ledger + 1.1, end: CUE.ledger + 1.7 }) }}>
              示例一单 ¥26：商家 ¥19.95 · 骑手 ¥5.00 · 平台 ¥1.05，每一段都能自己算出来。
            </div>
          </div>
        </div>
      </div>

      <Caption titles={TITLES} details={DETAILS} index={capIdx} narrow={narrow} detailColor={P.ink2}>
        <div style={{ fontSize: 12.5, color: P.ink2, marginTop: 2, opacity: tween(T, { start: CUE.close, end: CUE.close + 0.6 }) }}>
          打车标着「筹备中」—— 计价规则公开之前，我们不说它开着。
        </div>
      </Caption>
    </Film>
  )
}
