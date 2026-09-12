import React from 'react'

import { Amount, Caption, Ease, FILL, Film, P, enter, pop, tween, useFilm, useWidth, yuan } from './kit.jsx'

/* 首页「下载」那一段的片子:一笔单,三端各看到什么。放在三张下载卡上面。
 *
 * 三台手机都是浅色的(三端定稿都是骨白纸面,骑手端也是 5a/5c 纸面案)。
 * 同一单还是首页流程片那一单:菜价 ¥21 + 配送费 ¥5 = ¥26,
 * 商家 ¥19.95 / 骑手 ¥5.00 / 平台 ¥1.05。不写版本号 —— 版本一升片子就过时。
 *
 * 和原稿不一样(原稿按设计稿画,这里按三端代码里真显示的字改):
 * - 用户端的状态是 App 里的状态名:待接单 → 制作中 → 配送中 · 约 N 分钟 → 已送达;
 * - 商家端接单按钮是「接单 · 12 分出餐」(merchant_ui.dart);
 * - 骑手大厅没有「只看顺路」开关(顺路是五种排序之一),头上改成「在线」;
 *   配送费也不拆「距离费 / 楼层费」—— 拆分项的名字是服务端下发的
 *   「基础配送费 / 上门难度…」,大厅卡片上写的是全程分钟数和折合时薪;
 * - 底部原稿有三个「下载 APK」字样的块,不是链接,又正好压在真的三张下载卡上面,删了;
 * - 原稿底下那行「不收集后台定位 / 设备识别码 / 装机列表」不对:骑手端接单期间
 *   锁屏也在定位(前台服务),极光推送会读设备标识(隐私政策的第三方 SDK 表里写着)。
 *   只留查得到的:应用内更新先校验 SHA-256 再装。 */

// @serif-cjk-begin
// 字幕大字(衬线显示,这个圈里的字才会进官网的衬线子集)
const TITLES = [
  '一笔单，三端各看到什么。',
  '商家看到的是「实收」。',
  '骑手看到的是「到手」。',
  '三端对的是同一份账。',
]
// @serif-cjk-end

/* 字幕底下那行说明(黑体,不进衬线子集) */
const DETAILS = [
  '同一个订单号，三个身份，三种界面 —— 底下是同一份账。',
  '菜价 ¥21 − 5%，到手 ¥19.95，不用自己算。',
  '配送费 ¥5.00 全额；接单前就看得到路程、全程分钟数和折合时薪。',
  '用户点开「钱去哪了」，看到的和商家、骑手看到的一分不差。',
]

const CUE = { phones: 0.3, order: 1.8, glow: 3.2, accept: 4.6, hall: 5.8, grab: 7.2, deliver: 9.2, split: 10.8, close: 13.4 }
const TOTAL = 16.2
const STILL = 12.2

const step = (T, at) => T >= at

/** 一台浅色手机。density 1 是用户端,1.06 是商家端 / 骑手端(字大一档、留白松一档) */
function Phone({ title, right, children, style, density = 1, who }) {
  return (
    <div style={{
      borderRadius: 26, background: P.paper, border: `1px solid ${P.edge}`, overflow: 'hidden',
      boxShadow: '0 14px 34px rgba(20,20,19,.10)', lineHeight: 1.45,
      display: 'flex', flexDirection: 'column', ...style,
    }}>
      <div style={{ height: 26, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 14px', fontSize: 10, fontWeight: 600, color: P.ink2 }}>
        <span>12:04</span>
        <span style={{ width: 18, height: 8, borderRadius: 2, border: `1.2px solid ${P.ink3}` }} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '0 12px 8px', fontSize: 12.5 * density, fontWeight: 600 }}>
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</span>
        {right}
      </div>
      <div style={{ padding: '0 12px 14px', display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
        {children}
        <div style={{ marginTop: 'auto', fontSize: 10, color: P.ink3, textAlign: 'center' }}>{who}</div>
      </div>
    </div>
  )
}

const Card = ({ bar, children, style }) => (
  <div style={{ background: P.card, border: `1px solid ${P.line}`, borderRadius: 10, overflow: 'hidden', ...style }}>
    {bar && <div style={{ height: 3, background: bar }} />}
    <div style={{ padding: '9px 11px' }}>{children}</div>
  </div>
)

const Row = ({ k, v, size = 11.5, color, style }) => (
  <div style={{ display: 'flex', fontSize: size, ...style }}>
    <span style={{ flex: 1 }}>{k}</span><Amount v={v} size={size} color={color} />
  </div>
)

const Btn = ({ children, bg, style }) => (
  <div style={{
    height: 34, borderRadius: 9, display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 12.5, fontWeight: 600, background: bg, color: P.card, ...style,
  }}>{children}</div>
)

const Pill = ({ children }) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 9.5, padding: '2px 7px', borderRadius: 999, background: 'rgba(78,107,79,.12)', color: P.earn, fontWeight: 600 }}>
    <span style={{ width: 5, height: 5, borderRadius: 3, background: P.earn }} />{children}
  </span>
)

const press = (T, at) => (T > at - 0.2 && T < at + 0.1 ? 'scale(.97)' : 'scale(1)')

export default function ThreeAppsFilm() {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.5 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 700

  const ordered = step(T, CUE.order + 0.5)
  const accepted = step(T, CUE.accept)
  const grabbed = step(T, CUE.grab)
  const delivered = step(T, CUE.deliver)
  const split = step(T, CUE.split)
  // 商家新单光晕 0→6px→0,600ms 一次,闪三次(动效规范 07)
  const glow = T > CUE.glow && T < CUE.glow + 1.8 ? Math.abs(Math.sin(((T - CUE.glow) / 0.6) * Math.PI)) : 0
  const state = delivered ? '已送达' : grabbed ? '配送中 · 约 8 分钟' : accepted ? '制作中' : '待接单'
  const capIdx = split ? 3 : T >= CUE.hall ? 2 : T >= CUE.glow ? 1 : 0
  const phone = { flex: '1 1 190px', minWidth: 0, maxWidth: narrow ? 'none' : 240, minHeight: 300 }

  return (
    <Film film={film} label="示例 · 订单 #44 · 三端同时" loop="循环 · 16 秒"
      summary="示例动画：同一笔 26 元的外卖单在三端同时发生。用户端下单，商家端看到这一单实收 19.95 元并接单，骑手端在大厅看到 5 元配送费全额并抢单，送达后 5 元进骑手钱包。三端对的是同一份账：商家 19.95 元、骑手 5 元、平台 1.05 元。"
      style={{ background: P.alt, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      <div style={{ display: 'flex', gap: narrow ? 12 : 18, flexWrap: 'wrap', justifyContent: 'center' }}>
        {/* 用户端 */}
        <Phone title="张记面馆" who="用户端" style={{ ...phone, ...enter(T, CUE.phones) }}
          right={<span style={{ fontSize: 10, color: P.ink2, fontWeight: 400 }}>210m</span>}>
          <Card bar={P.bowl}>
            <Row k="牛肉面" v="¥16.00" style={{ fontWeight: 600 }} />
            <Row k="卤蛋 ×2" v="¥5.00" style={{ fontWeight: 600, marginTop: 5 }} />
            <Row k="配送费 · 全额给骑手" v="¥5.00" size={10.5} color={P.earn}
              style={{ color: P.ink2, marginTop: 7, paddingTop: 7, borderTop: `1px solid ${P.line}` }} />
          </Card>
          <div style={{ position: 'relative', height: 34 }}>
            <Btn bg={P.clay} style={{ ...FILL, opacity: ordered ? 0 : 1, transform: press(T, CUE.order + 0.2) }}>下单 · ¥26.00</Btn>
            <Btn bg={P.earn} style={{ ...FILL, ...pop(T, CUE.order + 0.5), visibility: ordered ? 'visible' : 'hidden' }}>已下单 · ¥26.00</Btn>
          </div>
          {ordered && (
            <Card bar={P.bowl} style={enter(T, CUE.order + 0.7)}>
              <div style={{ display: 'flex', fontSize: 11.5, alignItems: 'center' }}>
                <span style={{ flex: 1, fontWeight: 600 }}>订单 #44</span>
                <span style={{ fontSize: 11, fontWeight: 600, color: delivered ? P.earn : P.clay }}>{state}</span>
              </div>
              {/* 状态推进:线 220ms → 点 spring(动效规范 04) */}
              <div style={{ marginTop: 9, display: 'flex', alignItems: 'center', gap: 4 }}>
                {[CUE.accept, CUE.grab, CUE.deliver].map((at, i) => (
                  <React.Fragment key={at}>
                    <span style={{
                      width: 6, height: 6, borderRadius: 3, flex: 'none', background: T >= at ? P.earn : P.line,
                      transform: `scale(${1 + 0.3 * tween(T, { start: at, end: at + 0.3, ease: Ease.spring })})`,
                    }} />
                    <span style={{ flex: 1, height: 2, background: P.line, position: 'relative', overflow: 'hidden' }}>
                      <span style={{
                        ...FILL, background: P.earn, transformOrigin: 'left',
                        transform: `scaleX(${tween(T, { start: at, end: at + 0.4 })})`,
                      }} />
                    </span>
                  </React.Fragment>
                ))}
                <span style={{ width: 6, height: 6, borderRadius: 3, background: delivered ? P.earn : P.line, flex: 'none' }} />
              </div>
            </Card>
          )}
          {split && (
            <div style={{ background: P.ledger, borderRadius: 10, padding: '9px 11px', ...enter(T, CUE.split) }}>
              <div style={{ fontSize: 9.5, letterSpacing: 0.8, color: P.dmute }}>这 ¥26 去了哪</div>
              <Row k="商家" v="¥19.95" size={10.5} color={P.dearn} style={{ color: P.dtext, marginTop: 5 }} />
              <Row k="骑手" v="¥5.00" size={10.5} color={P.dearn} style={{ color: P.dtext, marginTop: 3 }} />
              <Row k="平台" v="¥1.05" size={10.5} color={P.dgold} style={{ color: P.dtext, marginTop: 3 }} />
            </div>
          )}
        </Phone>

        {/* 商家端 */}
        <Phone density={1.06} title="张记面馆 · 商家" who="商家端" right={<Pill>营业中</Pill>}
          style={{ ...phone, ...enter(T, CUE.phones + 0.15) }}>
          <div style={{ background: P.ledger, borderRadius: 10, padding: '10px 12px' }}>
            <div style={{ fontSize: 9.5, letterSpacing: 0.8, color: P.dmute }}>今日实收 · 菜价 − 5%</div>
            {/* 账本数字:从旧值滚到新值,900ms */}
            <Amount v={yuan(tween(T, { from: 1846.55, to: 1866.5, start: CUE.accept, end: CUE.accept + 0.9 }))} size={22} color={P.dtext} />
          </div>
          <Card bar={P.bowl} style={{ boxShadow: glow ? `0 0 0 ${glow * 6}px rgba(193,95,60,.22)` : 'none', opacity: T >= CUE.glow ? 1 : 0.35 }}>
            <Row k={<b style={{ fontWeight: 600 }}>新单 #44</b>} v="¥21.00" size={12} />
            <div style={{ fontSize: 10.5, color: P.ink2, marginTop: 4 }}>牛肉面 ×1、卤蛋 ×2</div>
            <Row k="佣金 5%" v="−¥1.05" size={10.5} color={P.hold}
              style={{ color: P.ink2, marginTop: 7, paddingTop: 7, borderTop: `1px solid ${P.line}` }} />
            <Row k={<b style={{ fontWeight: 600 }}>本单实收</b>} v="¥19.95" size={11.5} color={P.earn} style={{ marginTop: 4 }} />
          </Card>
          <Btn bg={accepted ? P.earn : P.bowl} style={{ transform: press(T, CUE.accept), opacity: T >= CUE.glow ? 1 : 0.35 }}>
            {accepted ? '已接单 · 制作中' : '接单 · 12 分出餐'}
          </Btn>
        </Phone>

        {/* 骑手端 */}
        <Phone density={1.06} title="接单大厅" who="骑手端" right={<Pill>在线</Pill>}
          style={{ ...phone, ...enter(T, CUE.phones + 0.3) }}>
          <Card bar={P.run} style={{ opacity: T >= CUE.hall ? 1 : 0.35 }}>
            <div style={{ display: 'flex', alignItems: 'baseline' }}>
              <span style={{ flex: 1, fontSize: 12, fontWeight: 600 }}>张记面馆 → 高新路</span>
              <Amount v="¥5.00" size={14} color={P.earn} />
            </div>
            <div style={{ fontSize: 10.5, color: P.ink2, marginTop: 4 }}>1.8km · 全程约 14 分钟 · ≈¥21/小时</div>
            <div style={{ fontSize: 10, color: P.ink3, marginTop: 3 }}>配送费全额 · 平台不抽</div>
          </Card>
          <Btn bg={grabbed ? P.earn : P.run} style={{ opacity: T >= CUE.hall ? 1 : 0.35, transform: press(T, CUE.grab) }}>
            {grabbed ? (delivered ? '已送达' : '去取餐') : '抢单'}
          </Btn>
          {grabbed && (
            <div style={{ background: P.ledger, borderRadius: 10, padding: '10px 12px', ...enter(T, CUE.grab + 0.2) }}>
              <div style={{ fontSize: 9.5, letterSpacing: 0.8, color: P.dmute }}>钱包 · 这一单</div>
              {delivered
                ? <Amount v={`+${yuan(tween(T, { to: 5, start: CUE.deliver, end: CUE.deliver + 0.9 }))}`} size={20} color={P.dearn} />
                : <Amount v="¥5.00" size={20} color={P.dmute} weight={400} />}
              <div style={{ fontSize: 10, color: P.dmute, marginTop: 3 }}>{delivered ? '平台抽成 ¥0 · 订单完成即入账' : '订单完成后入账 · 平台抽成 ¥0'}</div>
            </div>
          )}
        </Phone>
      </div>

      <Caption title={TITLES[capIdx]} detail={DETAILS[capIdx]} narrow={narrow} minDetail={22} detailColor={P.ink2}>
        <div style={{ fontSize: 12, color: P.ink3, marginTop: 8 }}>Android arm64 · 内置更新检查 · 应用内更新先校验 SHA-256 再安装</div>
      </Caption>
    </Film>
  )
}
