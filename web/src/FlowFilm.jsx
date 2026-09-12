import React, { useEffect, useRef, useState } from 'react'

import { Icon, reducedMotion, useReducedMotion } from './SiteChrome.jsx'

/* 首页流程动画:一笔 ¥26 的外卖单,钱是怎么走的。16:9,30 秒一循环。
 *
 * 移植自设计交接包 handoff/motion/sz-flow.jsx(1600×900 画幅)。原稿跑在设计工具的
 * 动画引擎(animations-v3.jsx)里,那个引擎不上线:这里只留原稿用到的三件事 ——
 * 时间 T(秒)、四条缓动、单段补间 tween() —— 外加一个 requestAnimationFrame 时钟。
 * 编排(机位、飞出去的订单卡、商家新单光晕、分账条生长、字幕、收尾卡)照原稿。
 *
 * 和原稿不一样的地方:
 * - 骑手手机是**浅色**的(骑手端定稿选的是纸面 5a/5c,原稿画的是深色 b 案);
 * - 分账面板里骑手那行原来写「22:00 到卡」—— 平台没有定时结算到卡这回事:
 *   订单完成钱进 App 钱包,骑手自己提现,T+1 到卡。改成「完成即进钱包」;
 * - 原稿在分账面板上写了一个账本指纹。这一单是示例,拿真指纹配示例单等于说
 *   「这笔账在链上」,所以不写指纹,写明是示例单;
 * - 画面外面(FlowFilm 底下)多一行分段按钮 + 一句话字幕:手机上画幅缩到
 *   三百来像素宽,画里的字读不清,读得清的那一行在画外。
 *
 * 画面滚出视口、切到别的标签页时停;系统开了「减少动态效果」就只画分账那一帧
 * (三台手机 + 分账条画满),分段按钮换成跳到每一段的结束画面,不播放。 */

const P = {
  paper: '#F0EEE6', card: '#FBFAF6', line: '#E2DED2', ink: '#141413', ink2: '#6B6862',
  ink3: '#9A968C', clay: '#C15F3C', ok: '#4E6B4F', plat: '#A6763E', dark: '#1F1E1B',
  dtext: '#F2F0E8', dmute: '#A8A49A', dok: '#8FB08D', bowl: '#943F2F', run: '#2B5F7A',
}
const SANS = '-apple-system,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif'
const SERIF = "'SzSerif',Georgia,serif"
// 拉丁字母和数字在前(SzSerif),汉字落到 SzSerifCJK —— 同 site.css 的 h1
const CJK = "'SzSerif','SzSerifCJK','PingFang SC',serif"
const FILL = { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }

// @serif-cjk-begin
const TXT = {
  cap0: ['一笔 ', ' 的外卖单，钱是这样走的'],
  cap1: '商家接单 · 只付菜价的 5%',
  cap2: '骑手抢单 · 配送费一分不抽',
  cap3: '送达 · 订单完成才收费',
  ledger: ['这 ', ' 去了哪'],
  close: ['每一分钱去哪了，', '都能查。'],
}
// @serif-cjk-end

// ---------- 时间轴 ----------

/* 六段时长和原稿 OM_SCENES 一致:下单 5 · 商家接单 5 · 骑手抢单 5 · 送达 5 · 分账 7 · 收尾 3 */
const SCENES = [
  { key: 'order', name: '下单', dur: 5 },
  { key: 'merchant', name: '商家接单', dur: 5 },
  { key: 'rider', name: '骑手抢单', dur: 5 },
  { key: 'deliver', name: '送达', dur: 5 },
  { key: 'ledger', name: '分账', dur: 7 },
  { key: 'close', name: '收尾', dur: 3 },
]
const CUE = {}
let acc = 0
for (const s of SCENES) { CUE[s.key] = acc; acc += s.dur }
const TOTAL = acc

/* 减少动态效果时画的那一帧:分账段里,条和数字都已经长满、收尾还没开始 */
const STILL_T = CUE.ledger + 3
/* 还没滚进视口时停在这一帧(第 1 秒:字幕已出、手机已在)。
 * 从 0 开始的话,0–0.6 秒是一层纸色的渐显,没播之前整块画幅是空的 */
const POSTER_T = 1

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
const Ease = {
  outCubic: t => 1 - Math.pow(1 - t, 3),
  inCubic: t => t * t * t,
  inOutCubic: t => (t < 0.5 ? 4 * t * t * t : (t - 1) * (2 * t - 2) * (2 * t - 2) + 1),
  outBack: t => { const c1 = 1.70158; const c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2) },
}
/** 单段补间:start 之前是 from,end 之后是 to */
function tween(T, { from = 0, to = 1, start, end, ease = Ease.inOutCubic }) {
  if (T <= start) return from
  if (T >= end) return to
  return from + (to - from) * ease((T - start) / (end - start))
}

/* 全片只用三种动效(同原稿 MOTION) */
const enter = (T, start, dur = 0.32) => {
  const k = tween(T, { start, end: start + dur, ease: Ease.outCubic })
  return { opacity: k, transform: `translateY(${(1 - k) * 14}px)` }
}
const draw = (T, start, dur = 0.9) => tween(T, { start, end: start + dur, ease: Ease.outCubic })
const pop = (T, start, dur = 0.32) => {
  const k = tween(T, { start, end: start + dur, ease: Ease.outBack })
  return { opacity: clamp(k * 3, 0, 1), transform: `scale(${0.8 + 0.2 * k})` }
}
const press = (T, at) => (T > at && T < at + 0.24 ? 'scale(.97)' : 'scale(1)')
const step = (T, at) => (T >= at ? 1 : 0)

// ---------- 零件 ----------

function Phone({ x, y, children, header }) {
  return (
    <div style={{
      position: 'absolute', left: x - 160, top: y - 330, width: 320, height: 660, borderRadius: 34,
      background: P.paper, border: '1px solid #D8D4C8', boxShadow: '0 24px 60px rgba(20,20,19,.12)',
      overflow: 'hidden', color: P.ink, fontFamily: SANS, lineHeight: 1.4,
    }}>
      <div style={{ height: 40, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 22px', fontSize: 12, fontWeight: 600 }}>
        <span>12:0{header.min}</span>
        <span style={{ width: 22, height: 10, borderRadius: 3, border: `1.5px solid ${P.ink}` }} />
      </div>
      <div style={{ height: 44, display: 'flex', alignItems: 'center', padding: '0 18px', fontSize: 15, fontWeight: 600, gap: 8 }}>
        <span style={{ flex: 1 }}>{header.title}</span>{header.right}
      </div>
      {children}
    </div>
  )
}

const Card = ({ color, children, style }) => (
  <div style={{ background: P.card, border: `1px solid ${P.line}`, borderRadius: 12, overflow: 'hidden', ...style }}>
    {color && <div style={{ height: 3, background: color }} />}
    <div style={{ padding: '12px 14px' }}>{children}</div>
  </div>
)
const Btn = ({ bg, fg, children, style }) => (
  <div style={{ height: 44, borderRadius: 10, background: bg, color: fg, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, fontWeight: 600, ...style }}>{children}</div>
)
const Money = ({ v, size = 15, color, style }) => (
  <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: size, color, fontVariantNumeric: 'tabular-nums', ...style }}>{v}</span>
)
const Pill = ({ children }) => (
  <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, padding: '3px 8px', borderRadius: 999, background: 'rgba(78,107,79,.12)', color: P.ok, fontWeight: 600 }}>
    <span style={{ width: 6, height: 6, borderRadius: 3, background: P.ok }} />{children}
  </span>
)

// ---------- 用户端 ----------

function UserPhone({ T }) {
  const ordered = step(T, CUE.order + 3.4)
  const st = T >= CUE.deliver + 3.5 ? 3 : T >= CUE.deliver + 1.2 ? 2 : T >= CUE.rider + 3.6 ? 1 : 0
  const names = ['已接单', '已取餐', '配送中', '送达']
  const stText = ordered
    ? ['等商家接单', '商家接单 · 12 分出餐', '骑手已取餐', '配送中 · 约 8 分钟', '已送达'][T >= CUE.merchant + 3.4 ? st + 1 : 0]
    : ''
  const railIn = enter(T, CUE.order + 3.6)
  return (
    <Phone x={400} y={470} header={{ min: 0, title: '张记面馆', right: <span style={{ fontSize: 11, color: P.ink2, fontWeight: 400 }}>210m · 4.8 分</span> }}>
      <div style={{ padding: '4px 18px 0', display: 'flex', flexDirection: 'column', gap: 9 }}>
        <Card color={P.bowl}>
          <div style={{ display: 'flex', fontSize: 14, fontWeight: 600 }}><span style={{ flex: 1 }}>牛肉面</span><span style={{ color: P.ink2, fontWeight: 400, marginRight: 10 }}>×1</span><Money v="¥16.00" size={14} /></div>
          <div style={{ display: 'flex', fontSize: 14, fontWeight: 600, marginTop: 8 }}><span style={{ flex: 1 }}>卤蛋</span><span style={{ color: P.ink2, fontWeight: 400, marginRight: 10 }}>×2</span><Money v="¥5.00" size={14} /></div>
          <div style={{ display: 'flex', fontSize: 12.5, color: P.ink2, marginTop: 10, paddingTop: 10, borderTop: `1px solid ${P.line}` }}><span style={{ flex: 1 }}>配送费 · 全额给骑手</span><Money v="¥5.00" size={12.5} color={P.ok} /></div>
          <div style={{ display: 'flex', fontSize: 12.5, color: P.ink2, marginTop: 6 }}><span style={{ flex: 1 }}>平台服务费 · 用户侧</span><Money v="¥0" size={12.5} /></div>
        </Card>
        <div style={{ position: 'relative', height: 44 }}>
          <Btn bg={P.clay} fg={P.card} style={{ ...FILL, transform: press(T, CUE.order + 3), opacity: 1 - ordered }}>下单 · <Money v="¥26.00" size={15} color={P.card} style={{ marginLeft: 6 }} /></Btn>
          <Btn bg={P.ok} fg={P.card} style={{ ...FILL, ...pop(T, CUE.order + 3.4), visibility: ordered ? 'visible' : 'hidden' }}>已下单 · <Money v="¥26.00" size={15} color={P.card} style={{ marginLeft: 6 }} /></Btn>
        </div>
        <Card color={P.bowl} style={railIn}>
          <div style={{ display: 'flex', alignItems: 'center', fontSize: 13 }}>
            <span style={{ flex: 1, fontWeight: 600 }}>订单 #44</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: st === 3 ? P.ok : P.clay }}>{stText}</span>
          </div>
          <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', fontSize: 10.5, color: P.ink3 }}>
            {names.map((n, i) => {
              const done = i < st
              const cur = i === st && T >= CUE.merchant + 3.4
              const at = [CUE.merchant + 3.4, CUE.rider + 3.6, CUE.deliver + 1.2, CUE.deliver + 3.5][i]
              const dotK = tween(T, { start: at, end: at + 0.3, ease: Ease.outBack })
              return (
                <React.Fragment key={n}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: done ? P.ok : cur ? P.clay : P.ink3, fontWeight: cur ? 600 : 400 }}>
                    <span style={{ width: 7, height: 7, borderRadius: 4, background: done ? P.ok : cur ? P.clay : P.line, transform: `scale(${cur ? 1 + 0.3 * dotK : 1})` }} />{n}
                  </span>
                  {i < 3 && (
                    <span style={{ flex: 1, height: 2, background: P.line, margin: '0 5px', position: 'relative', overflow: 'hidden' }}>
                      <span style={{ ...FILL, background: P.ok, transformOrigin: 'left', transform: `scaleX(${draw(T, [CUE.rider + 3.3, CUE.deliver + 0.9, CUE.deliver + 3.2][i], 0.3)})` }} />
                    </span>
                  )}
                </React.Fragment>
              )
            })}
          </div>
        </Card>
      </div>
    </Phone>
  )
}

// ---------- 商家端 ----------

function MerchantPhone({ T }) {
  const arrive = CUE.merchant + 0.6
  const accepted = step(T, CUE.merchant + 3.4)
  // 新单光晕 0→6px,600ms 一次,闪三次(动效规范 07)
  const pulse = T > arrive && T < arrive + 1.8 ? Math.abs(Math.sin(((T - arrive) / 0.6) * Math.PI)) : 0
  return (
    <Phone x={800} y={470} header={{ min: 1, title: '张记面馆 · 商家', right: <Pill>营业中</Pill> }}>
      <div style={{ padding: '4px 18px 0', display: 'flex', flexDirection: 'column', gap: 9 }}>
        <div style={{ background: P.dark, color: P.dtext, borderRadius: 12, padding: '12px 14px' }}>
          <div style={{ fontSize: 10.5, letterSpacing: 1, color: P.dmute }}>今日实收 · 菜价 − 5%</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <Money v={accepted ? '¥1,226.30' : '¥1,206.35'} size={26} color={P.dok} />
            <span style={{ fontSize: 11, color: P.dmute }}>{accepted ? 48 : 47} 单 · 配送费从你这抽 ¥0</span>
          </div>
        </div>
        <div style={{ fontSize: 11, letterSpacing: 1, color: P.ink2, display: 'flex' }}>
          <span style={{ flex: 1 }}>待接单</span>
          <span style={{ color: P.clay, fontWeight: 600, opacity: step(T, arrive) - accepted }}>1 新单</span>
        </div>
        <Card color={P.clay} style={{ ...pop(T, arrive), boxShadow: `0 0 0 ${pulse * 6}px rgba(193,95,60,.28)` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Money v="#44" size={20} />
            {/* 汉字在 flex 里默认能缩到一个字宽,不 nowrap 的话这一行会折成两行 */}
            <span style={{ fontSize: 11.5, color: P.ink2, whiteSpace: 'nowrap' }}>刚刚 · 尾号 3382</span>
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 12, fontWeight: 600, color: accepted ? P.ok : P.clay, whiteSpace: 'nowrap' }}>{accepted ? '制作中 · 12 分出餐' : '新单'}</span>
          </div>
          <div style={{ marginTop: 6, fontSize: 13.5 }}>牛肉面 ×1、卤蛋 ×2</div>
          <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
            <Money v="¥19.95" size={15} color={P.ok} /><span style={{ fontSize: 11, color: P.ink3 }}>菜价 ¥21 − 5% ¥1.05</span>
          </div>
          <div style={{ position: 'relative', height: 40, marginTop: 10 }}>
            <div style={{ ...FILL, display: 'flex', gap: 8, opacity: 1 - accepted }}>
              <Btn bg="transparent" fg={P.ink} style={{ height: 40, padding: '0 14px', border: `1px solid ${P.line}`, fontSize: 13, fontWeight: 500 }}>拒单</Btn>
              <Btn bg={P.bowl} fg={P.card} style={{ height: 40, flex: 1, fontSize: 14, transform: press(T, CUE.merchant + 3) }}>接单 · 12 分钟出餐</Btn>
            </div>
            <Btn bg={P.ok} fg={P.card} style={{ ...FILL, height: 40, fontSize: 14, ...pop(T, CUE.merchant + 3.4), visibility: accepted ? 'visible' : 'hidden' }}>✓ 已接单 · 小票已打印</Btn>
          </div>
        </Card>
        <Card style={{ opacity: 0.55 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Money v="#43" size={18} /><span style={{ flex: 1, fontSize: 13 }}>酸辣粉 ×2 · 制作中</span><span style={{ fontSize: 11.5, color: P.ink2 }}>12:03 出餐</span>
          </div>
        </Card>
      </div>
    </Phone>
  )
}

// ---------- 骑手端(浅色,同骑手端定稿 5a 大厅 / 5c 新单抽屉) ----------

function RiderPhone({ T }) {
  const sheetAt = CUE.rider + 0.5
  const grabbed = step(T, CUE.rider + 3.4)
  // 抽屉 260ms standard 上来,不回弹(骑手端一律不用 spring)
  const sheetK = tween(T, { from: 1, to: 0, start: sheetAt, end: sheetAt + 0.26, ease: Ease.outCubic })
  const cd = clamp(1 - (T - (sheetAt + 0.3)) / 15, 0, 1)
  // 倒计时 15 秒:抽屉刚冒头那 0.3 秒里也写 15,不是 16(原稿这里会闪一下 16)
  const cdN = clamp(Math.ceil(15 - (T - (sheetAt + 0.3))), 0, 15)
  const hall = [
    ['¥11.76', '4.3km · 帮我送', '阳光花园 → 创业大厦', P.run],
    ['¥6.00', '3.0km', '李婶砂锅粥 → 阳光花园', P.bowl],
  ]
  return (
    <Phone x={1200} y={470} header={{ min: 1, title: '接单大厅', right: <Pill>在线</Pill> }}>
      <div style={{ padding: '4px 18px 0', display: 'flex', flexDirection: 'column', gap: 9 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 11, color: P.ink2 }}>今日</span>
          <Money v={grabbed ? '¥63.76' : '¥58.76'} size={24} color={P.ok} />
          <span style={{ fontSize: 11, color: P.ink2 }}>{grabbed ? 10 : 9} 单 · 全额到手</span>
        </div>
        {hall.map(([f, m, r, c]) => (
          <Card key={r} color={c}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}><Money v={f} size={24} color={P.ok} /><span style={{ fontSize: 11.5, color: P.ink2 }}>{m}</span></div>
            <div style={{ fontSize: 13, marginTop: 6 }}>{r}</div>
          </Card>
        ))}
      </div>
      {/* 抽屉上来时大厅压暗一层(5c) */}
      <div style={{ ...FILL, background: 'rgba(20,20,19,.24)', opacity: 1 - sheetK }} />
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0, background: P.card, borderTop: `1px solid ${P.line}`,
        borderRadius: '20px 20px 0 0', padding: '10px 18px 22px', transform: `translateY(${sheetK * 100}%)`,
        boxShadow: '0 -10px 30px rgba(20,20,19,.08)',
      }}>
        <div style={{ width: 36, height: 4, borderRadius: 2, background: P.line, margin: '0 auto 12px' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5, color: P.ink2, height: 18 }}>
          <span style={{ flex: 1 }}>新单 · 张记面馆</span>
          {!grabbed && (
            <>
              <span style={{ width: 40, height: 4, borderRadius: 2, background: P.line, overflow: 'hidden', display: 'block' }}>
                <span style={{ display: 'block', height: '100%', background: P.clay, transformOrigin: 'left', transform: `scaleX(${cd})` }} />
              </span>
              <span>还有 <Money v={cdN} size={13} color={P.ink} /> 秒可抢</span>
            </>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 12 }}>
          <Money v="¥5.00" size={38} color={P.ok} style={{ lineHeight: 1 }} />
          <span style={{ fontSize: 12, color: P.ink2 }}>配送费全额 · 平台不抽</span>
        </div>
        <div style={{ marginTop: 12, background: P.paper, borderRadius: 10, padding: '9px 12px', fontSize: 12.5, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ width: 7, height: 7, borderRadius: 4, border: `1.5px solid ${P.ink}` }} />
            <span style={{ flex: 1 }}>张记面馆 · 学府街 12 号</span><span style={{ color: P.ink2, fontSize: 11.5 }}>距你 380m</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ width: 7, height: 7, borderRadius: 4, background: P.clay }} />
            <span style={{ flex: 1 }}>高新路 88 号 3 栋</span><span style={{ color: P.ink2, fontSize: 11.5 }}>送程 1.8km</span>
          </div>
        </div>
        <div style={{ position: 'relative', height: 48, marginTop: 14 }}>
          <div style={{ ...FILL, display: 'flex', gap: 8, opacity: 1 - grabbed }}>
            <Btn bg="transparent" fg={P.ink} style={{ height: 48, padding: '0 16px', border: `1px solid ${P.line}`, fontSize: 13, fontWeight: 500 }}>不接</Btn>
            <Btn bg={P.run} fg={P.card} style={{ height: 48, flex: 1, fontSize: 16, transform: press(T, CUE.rider + 3) }}>抢单</Btn>
          </div>
          <Btn bg={P.ok} fg={P.card} style={{ ...FILL, height: 48, fontSize: 16, opacity: grabbed, transform: `scale(${0.8 + 0.2 * draw(T, CUE.rider + 3.4, 0.22)})` }}>✓ 已抢到 · 去取餐</Btn>
        </div>
      </div>
    </Phone>
  )
}

// ---------- 分账面板 ----------

function Ledger({ T }) {
  // 账本数字与分账条:900ms standard,段间 120ms(动效规范 09)
  const k = draw(T, CUE.ledger + 0.6, 0.9)
  const v = n => (n * k).toFixed(2)
  const rows = [
    ['商家 · 张记面馆', '菜价 ¥21.00 − 5%', 19.95, P.ok],
    ['骑手 · 王师傅', '配送费全额 · 完成即进钱包', 5, P.ok],
    ['平台', '菜价 5% · 服务器、客服、核账', 1.05, P.plat],
  ]
  return (
    <div style={{ position: 'absolute', left: 200, right: 200, top: 630, ...enter(T, CUE.ledger + 0.3), fontFamily: SANS, color: P.ink }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
        <span style={{ fontFamily: CJK, fontSize: 30, fontWeight: 600 }}>{TXT.ledger[0]}<Money v="¥26.00" size={30} />{TXT.ledger[1]}</span>
        <span style={{ fontSize: 14, color: P.ink2 }}>示例单 · 用户、商家、骑手看到的是同一份账</span>
      </div>
      <div style={{ display: 'flex', height: 14, borderRadius: 999, overflow: 'hidden', gap: 3, marginTop: 16, background: 'rgba(20,20,19,.06)' }}>
        {rows.map(([n, , val, c], i) => (
          <span key={n} style={{ width: `${(val / 26) * 100 * draw(T, CUE.ledger + 0.6 + i * 0.12, 0.9)}%`, background: c, opacity: i === 1 ? 0.55 : 1 }} />
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 16 }}>
        {rows.map(([n, d, val, c], i) => (
          <div key={n} style={{ background: P.card, border: `1px solid ${P.line}`, borderRadius: 12, padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12, ...enter(T, CUE.ledger + 0.9 + i * 0.12) }}>
            <span style={{ width: 6, height: 38, borderRadius: 2, background: c, opacity: i === 1 ? 0.55 : 1 }} />
            <div style={{ flex: 1, lineHeight: 1.45 }}><div style={{ fontSize: 15, fontWeight: 600 }}>{n}</div><div style={{ fontSize: 12, color: P.ink2 }}>{d}</div></div>
            <Money v={`¥${v(val)}`} size={26} color={c} />
          </div>
        ))}
      </div>
    </div>
  )
}

function Caption({ T, items }) {
  const cur = items.filter(i => T >= i.at).pop()
  if (!cur || !cur.text) return null
  const s = enter(T, cur.at, 0.4)
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, top: 56, textAlign: 'center', fontFamily: CJK, fontSize: 34, fontWeight: 600, color: P.ink, lineHeight: 1.3, ...s }}>
      {cur.text}
    </div>
  )
}

/** 整个画面,纯函数:给一个时刻 T(0–30 秒),画那一帧 */
function Piece({ T }) {
  // 镜头:每段一个机位,机位在段首 0.9s 内滑过去
  const kf = [
    { t: 0, s: 0.95, x: 400, y: 490 }, { t: CUE.merchant, s: 0.95, x: 800, y: 490 },
    { t: CUE.rider, s: 0.95, x: 1200, y: 490 }, { t: CUE.deliver, s: 0.95, x: 400, y: 490 },
    { t: CUE.ledger, s: 0.58, x: 800, y: 590 },
  ]
  let cam = { ...kf[0] }
  for (let i = 1; i < kf.length; i++) {
    const e = { ease: Ease.inOutCubic, start: kf[i].t - 0.15, end: kf[i].t + 0.75 }
    cam = {
      s: tween(T, { from: cam.s, to: kf[i].s, ...e }),
      x: tween(T, { from: cam.x, to: kf[i].x, ...e }),
      y: tween(T, { from: cam.y, to: kf[i].y, ...e }),
    }
  }
  // 飞行的订单卡:用户 → 商家
  const fly = tween(T, { start: CUE.merchant - 0.3, end: CUE.merchant + 0.6, ease: Ease.inOutCubic })
  const flyVis = T > CUE.merchant - 0.3 && T < CUE.merchant + 0.6
  const vignette = tween(T, { from: 1, to: 0, start: 0, end: 0.6, ease: Ease.outCubic })
    + tween(T, { from: 0, to: 1, start: TOTAL - 0.6, end: TOTAL, ease: Ease.inCubic })
  const closeK = draw(T, CUE.close + 0.2, 0.6)
  const ledgerOn = T >= CUE.ledger && T < CUE.close + 0.8
  return (
    <div style={{ ...FILL, background: P.paper, overflow: 'hidden', fontFamily: SANS }}>
      <div style={{ ...FILL, opacity: 1 - closeK, transformOrigin: '0 0', transform: `translate(800px,450px) scale(${cam.s}) translate(${-cam.x}px,${-cam.y}px)` }}>
        <UserPhone T={T} /><MerchantPhone T={T} /><RiderPhone T={T} />
        {flyVis && (
          <div style={{
            position: 'absolute', left: 400 + 400 * fly - 120, top: 420 - Math.sin(fly * Math.PI) * 140 - 30, width: 240,
            background: P.card, border: `1px solid ${P.line}`, borderRadius: 12, padding: '10px 14px',
            boxShadow: '0 12px 30px rgba(20,20,19,.15)', display: 'flex', alignItems: 'center', gap: 8, opacity: Math.sin(fly * Math.PI),
          }}>
            <Money v="#44" size={18} /><span style={{ flex: 1, fontSize: 13 }}>牛肉面 ×1、卤蛋 ×2</span><Money v="¥26.00" size={15} />
          </div>
        )}
      </div>
      <div style={{ ...FILL, opacity: 1 - closeK }}>
        {ledgerOn && <Ledger T={T} />}
        <Caption T={T} items={[
          { at: 0.4, text: <span>{TXT.cap0[0]}<Money v="¥26" size={34} />{TXT.cap0[1]}</span> },
          { at: CUE.merchant + 0.2, text: TXT.cap1 },
          { at: CUE.rider + 0.2, text: TXT.cap2 },
          { at: CUE.deliver + 0.2, text: TXT.cap3 },
          { at: CUE.ledger + 0.2, text: '' },
        ]} />
      </div>
      <div style={{ ...FILL, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 18, opacity: closeK, pointerEvents: 'none' }}>
        <div style={{ fontFamily: CJK, fontSize: 60, fontWeight: 600, lineHeight: 1.2, textAlign: 'center', color: P.ink, ...enter(T, CUE.close + 0.5, 0.6) }}>{TXT.close[0]}<br />{TXT.close[1]}</div>
        <div style={{ fontSize: 18, color: P.ink2, ...enter(T, CUE.close + 1.0, 0.6) }}>超级赞 · 一个 App，装下所有不吸血的服务</div>
      </div>
      <div style={{ ...FILL, background: P.paper, opacity: clamp(vignette, 0, 1), pointerEvents: 'none' }} />
    </div>
  )
}

// ---------- 画外:分段按钮 + 读得清的一句话 ----------

/* 每段一句。画面缩小以后画里的字读不清(手机上整幅只有三百来像素宽),
 * 这一句在画外、正常字号,也是读屏软件读到的那句。数字和画面里一致 */
const STEPS = [
  { key: 'order', name: '下单', line: '用户下单：牛肉面 ×1、卤蛋 ×2 共 ¥21，配送费 ¥5，一共付 ¥26；用户这边不收平台服务费。', settle: 4.5 },
  { key: 'merchant', name: '商家接单', line: '商家接单：平台收菜价的 5%，也就是 ¥1.05，商家实收 ¥19.95。', settle: 9.5 },
  { key: 'rider', name: '骑手抢单', line: '骑手在大厅里自己抢单：¥5 配送费全额归骑手，平台不抽；不接也没有任何代价。', settle: 14.5 },
  { key: 'deliver', name: '送达', line: '送达、订单完成，这时才记佣金；取消的单不收。', settle: 19.5 },
  { key: 'ledger', name: '分账', line: '最后的账：商家 ¥19.95、骑手 ¥5.00、平台 ¥1.05，加起来正好是用户付的 ¥26。', settle: STILL_T },
]
const stepIndex = T => {
  let idx = 0
  STEPS.forEach((s, i) => { if (T >= CUE[s.key]) idx = i })
  return idx
}
const stepSpan = i => {
  const start = CUE[STEPS[i].key]
  const end = i + 1 < STEPS.length ? CUE[STEPS[i + 1].key] : TOTAL
  return [start, end]
}

export default function FlowFilm() {
  const reduced = useReducedMotion()
  const wrapRef = useRef(null)
  const [w, setW] = useState(0)
  const [T, setT] = useState(() => (reducedMotion() ? STILL_T : POSTER_T))
  const [paused, setPaused] = useState(false)
  const [inView, setInView] = useState(false)
  const [hidden, setHidden] = useState(() => typeof document !== 'undefined' && document.hidden)
  const running = !reduced && !paused && inView && !hidden

  // 画幅按容器宽度缩放(1600×900 → 容器宽)
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return undefined
    const measure = () => setW(el.clientWidth)
    measure()
    if (typeof ResizeObserver === 'function') {
      const ro = new ResizeObserver(measure)
      ro.observe(el)
      return () => ro.disconnect()
    }
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  // 滚出视口就停,滚回来接着播
  useEffect(() => {
    const el = wrapRef.current
    if (!el || typeof IntersectionObserver !== 'function') { setInView(true); return undefined }
    const io = new IntersectionObserver(([e]) => setInView(e.isIntersecting), { threshold: 0.15 })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  // 切到别的标签页就停
  useEffect(() => {
    const on = () => setHidden(document.hidden)
    document.addEventListener('visibilitychange', on)
    return () => document.removeEventListener('visibilitychange', on)
  }, [])

  useEffect(() => { if (reduced) setT(STILL_T) }, [reduced])

  // 时钟:只在真正播放时跑 requestAnimationFrame
  useEffect(() => {
    if (!running) return undefined
    let raf = 0
    let last = null
    const tick = now => {
      if (last != null) {
        const dt = Math.min(0.1, (now - last) / 1000)
        setT(t => (t + dt) % TOTAL)
      }
      last = now
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [running])

  const cur = stepIndex(T)
  const scale = w / 1600
  const seek = i => setT(reduced || paused ? STEPS[i].settle : CUE[STEPS[i].key] + 0.001)

  return (
    <div className="h3-film">
      <div className="stage" ref={wrapRef} role="img"
        aria-label="示例动画：一笔 26 元的外卖单。用户下单，商家接单，骑手抢单，送达，最后分账：商家 19.95 元，骑手 5 元，平台 1.05 元。">
        {w > 0 && (
          <div className="frame" aria-hidden="true" style={{ transform: `scale(${scale})` }}>
            <Piece T={T} />
          </div>
        )}
      </div>
      <div className="bar">
        {!reduced && (
          <button type="button" className="pp" onClick={() => setPaused(p => !p)}
            aria-label={paused ? '播放动画' : '暂停动画'}>
            <Icon name={paused ? 'play' : 'pause'} size={14} />
          </button>
        )}
        <div className="steps">
          {STEPS.map((s, i) => {
            const [a, b] = stepSpan(i)
            const fill = i < cur ? 1 : i > cur ? 0 : (reduced ? 1 : clamp((T - a) / (b - a), 0, 1))
            return (
              <button key={s.key} type="button" className={i === cur ? 'on' : ''}
                aria-current={i === cur ? 'step' : undefined} onClick={() => seek(i)}>
                <span className="nm">{s.name}</span>
                <span className="track"><span style={{ transform: `scaleX(${fill})` }} /></span>
              </button>
            )
          })}
        </div>
      </div>
      <p className="line">{STEPS[cur].line}</p>
    </div>
  )
}
