import React from 'react'

import { Caption, Film, P, SERIF, enter, pop, tween, useFilm, useWidth, yuan } from './kit.jsx'

/* 功能页「视频」一节的片子:看见的那家,就是能点的那家。
 *
 * 讲的是用户端 video/ 的做法(DEV-PROMPTS-40 #357–#367、D13、D16):
 * - 探店视频可以挂一家本平台的店;挂了店 UP 主必须声明有无合作,有合作标「合作」,
 *   平台不收推广费,挂不挂店不影响推荐;
 * - 视频详情里那张店铺卡点「去点单」直接进店,卡上写这家店离你多远、被抽多少
 *   (读这家店真实的费率 —— 5% 是上限,片子里的 5% 是示例那一家的);
 * - 从视频进来的单和从首页进来的一样:同一张费率表,配送费一分不抽;
 * - 硬币:每天第一次打开「视频」领 1 枚,投稿过审得 2 枚;只能投给视频,
 *   不能充值、提现、兑换。
 * 分账数字和首页流程片同一单:菜价 ¥21 + 配送费 ¥5 = ¥26。
 *
 * 视频要拿到《信息网络传播视听节目许可证》才对外开放,生产上缺省关着:
 * open 由页面读 /config 的 features.video 传进来,关着时头上写明「暂未开放」。
 *
 * 和原稿不一样:
 * - 原稿字幕写「菜价的 5%」,5% 是费率上限,单量上去会降档,不是每家都一样 ——
 *   改成「同一张费率表」;
 * - 原稿写「每天第一次看视频领 1 枚」。实际是每天第一次打开「视频」就领;
 * - 原稿写「不感兴趣」「为什么推荐给我」都在长按菜单里。关注、热门两页长按只有
 *   「稍后再看」,这两项只在推荐和竖屏里。 */

// @serif-cjk-begin
const TITLES = [
  '看的和买的，不在两个 App 里。',
  '点一下，直接进店。',
  '账还是那本账。',
]
const STEPS_COUNT = ['5 步', '2 步']
// @serif-cjk-end

/* 字幕底下那行说明(黑体,不进衬线子集) */
const DETAILS = [
  '视频可以挂上视频里那家店 —— 就是屏幕上正在拍的这一家，不是广告位买来的另一家。',
  '不用记店名、不用切 App、不用重新搜一遍再挑一遍。',
  '从视频进来的单子，和从首页进来的一模一样：同一张费率表，配送费一分不抽。',
]

const CUE = { play: 0.3, shop: 2.6, tap: 5.0, cart: 5.8, split: 7.6, steps: 9.8, coin: 12.6, close: 14.4 }
const TOTAL = 17.6
/** 静帧:已进店、购物车和分账条都在、两边步数和硬币那条都出了、收尾那句也在 */
const STILL = 15.2

/* 别处:从看见到吃上,中间隔着几步(通用描述,不点名) */
const AWAY = ['看到一家想吃的', '记住店名', '切到另一个 App', '搜索，可能搜不到', '重新挑一遍']
const HERE = ['看到一家想吃的', '点一下「去点单」']

const Dot = ({ color, opacity = 1 }) => (
  <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: 2, background: color, opacity, marginRight: 5 }} />
)

export default function VideoToOrderFilm({ open = true }) {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.5 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 780

  const tapped = T >= CUE.tap
  // 「去点单」被按下的那一瞬(按压 .96,120ms)
  const press = T > CUE.tap - 0.18 && T < CUE.tap + 0.06
  // 购物车金额:账本数字 900ms 滚上来
  const cart = tween(T, { to: 26, start: CUE.cart, end: CUE.cart + 0.9 })
  const g = tween(T, { start: CUE.split, end: CUE.split + 0.9 })
  const capIdx = T >= CUE.split ? 2 : T >= CUE.tap ? 1 : 0

  return (
    <Film film={film} loop="循环 · 18 秒"
      label={open ? '示例 · 从一条视频到一笔单' : '示例 · 视频暂未开放，下面是开放以后的样子'}
      summary={`示例动画：${open ? '' : '视频功能暂未开放，这是开放以后的样子。'}一条跟拍张记面馆熬汤的探店视频，下面挂着视频里这家店，标着「合作」。点一下「去点单」直接进店，购物车里牛肉面和卤蛋，菜价 21 元加配送费 5 元一共 26 元：商家 19.95 元、骑手 5 元、平台 1.05 元，和从首页进店下的单一样。别处从看到到进店要五步，这里两步。每天第一次打开视频领 1 枚硬币，硬币只能投给视频，不能充值、提现、兑换。`}
      style={{ background: P.card, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : '300px minmax(0,1fr)', gap: 18, alignItems: 'start' }}>

        {/* 视频详情:播放器 + 标题 + 挂的店 */}
        <div style={{ borderRadius: 12, overflow: 'hidden', background: P.ledger, ...enter(T, CUE.play) }}>
          <div style={{ position: 'relative', height: 168, background: '#0B0B0A' }}>
            <span style={{
              position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)',
              width: 44, height: 44, borderRadius: '50%', background: 'rgba(255,255,255,.16)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff',
            }}>
              <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor" /></svg>
            </span>
            {/* 两条弹幕 */}
            <span style={{ position: 'absolute', top: 10, left: 12, fontSize: 11, color: 'rgba(255,255,255,.85)', opacity: tween(T, { start: CUE.play + 0.8, end: CUE.play + 1.2 }) }}>这锅汤真的熬了六小时</span>
            <span style={{ position: 'absolute', top: 32, right: 14, fontSize: 11, color: 'rgba(255,255,255,.7)', opacity: tween(T, { start: CUE.play + 1.4, end: CUE.play + 1.8 }) }}>封签这段我服</span>
            <span style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 2.5, background: 'rgba(255,255,255,.22)' }}>
              <span style={{ display: 'block', height: '100%', width: `${tween(T, { from: 4, to: 82, start: CUE.play, end: CUE.split, ease: t => t })}%`, background: '#fff' }} />
            </span>
          </div>
          <div style={{ padding: '11px 13px' }}>
            <div style={{ fontSize: 13, color: P.dtext, lineHeight: 1.4 }}>凌晨四点的牛骨汤：跟拍张记面馆一整锅是怎么熬出来的</div>
            <div style={{ fontSize: 11, color: P.dmute, marginTop: 4, fontVariantNumeric: 'tabular-nums' }}>城南食记 · 2.4万 播放 · 312 弹幕</div>
          </div>

          {/* 挂的店:视频里那家 */}
          <div style={{ margin: '0 11px 12px', borderRadius: 10, background: P.card, overflow: 'hidden', ...enter(T, CUE.shop) }}>
            <div style={{ height: 3, background: P.bowl }} />
            <div style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 34, height: 34, borderRadius: 8, background: '#E6E3DA', flex: 'none' }} />
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ fontSize: 13.5, fontWeight: 600 }}>张记面馆</span>
                  <span style={{ padding: '1px 5px', borderRadius: 4, background: P.hold, color: P.card, fontSize: 10, lineHeight: 1.5 }}>合作</span>
                </span>
                <span style={{ display: 'block', fontSize: 11, color: P.ink2, marginTop: 1 }}>视频里这家 · 210m · 只被抽 5%</span>
              </span>
              <span style={{
                flex: 'none', height: 30, padding: '0 12px', borderRadius: 8,
                background: tapped ? P.earn : P.clay, color: P.card, fontSize: 12.5, fontWeight: 600,
                display: 'flex', alignItems: 'center', whiteSpace: 'nowrap', transform: press ? 'scale(.96)' : 'scale(1)',
              }}>{tapped ? '已进店' : '去点单'}</span>
            </div>
          </div>
        </div>

        {/* 右:购物车 + 分账 + 步数 + 硬币 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
          <div style={{ border: `1px solid ${P.line}`, borderRadius: 12, padding: '14px 16px', ...enter(T, CUE.cart - 0.3) }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{ flex: 1, fontSize: 13.5, fontWeight: 600 }}>购物车 · 张记面馆</span>
              <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 22, fontVariantNumeric: 'tabular-nums' }}>{yuan(cart)}</span>
            </div>
            <div style={{ fontSize: 12, color: P.ink2, marginTop: 3 }}>牛肉面 ×1、卤蛋 ×2 · 菜价 ¥21 + 配送费 ¥5</div>
            <div style={{ display: 'flex', height: 10, gap: 3, marginTop: 11, borderRadius: 999, overflow: 'hidden' }}>
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

          {/* 几步 */}
          <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : '1fr 1fr', gap: 12 }}>
            <div style={{ background: P.alt, borderRadius: 12, padding: '13px 14px', ...enter(T, CUE.steps) }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ flex: 1, fontSize: 11, letterSpacing: 1.2, color: P.ink2 }}>别处</span>
                <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 15, color: P.ink2 }}>{STEPS_COUNT[0]}</span>
              </div>
              <div style={{ marginTop: 7, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {AWAY.map((s, i) => (
                  <div key={s} style={{
                    fontSize: 12, color: P.ink2, display: 'flex', gap: 7,
                    opacity: tween(T, { start: CUE.steps + 0.2 + i * 0.18, end: CUE.steps + 0.5 + i * 0.18 }),
                  }}>
                    <span style={{ fontFamily: SERIF, color: P.ink3, flex: 'none' }}>{i + 1}</span>{s}
                  </div>
                ))}
              </div>
            </div>
            <div style={{ border: `1px solid ${P.line}`, borderRadius: 12, padding: '13px 14px', ...enter(T, CUE.steps + 0.5) }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ flex: 1, fontSize: 11, letterSpacing: 1.2, color: P.clay }}>这里</span>
                <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 15, color: P.clay }}>{STEPS_COUNT[1]}</span>
              </div>
              <div style={{ marginTop: 7, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {HERE.map((s, i) => (
                  <div key={s} style={{
                    fontSize: 12, display: 'flex', gap: 7,
                    opacity: tween(T, { start: CUE.steps + 0.7 + i * 0.22, end: CUE.steps + 1.0 + i * 0.22 }),
                  }}>
                    <span style={{ fontFamily: SERIF, color: P.clay, flex: 'none' }}>{i + 1}</span>{s}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 硬币 */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '11px 14px', borderRadius: 10,
            background: 'rgba(166,118,62,.10)', ...enter(T, CUE.coin),
          }}>
            <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 17, color: P.hold, flex: 'none', ...pop(T, CUE.coin + 0.2) }}>+1</span>
            <span style={{ flex: 1, minWidth: 0, fontSize: 12.5, lineHeight: 1.6 }}>
              每天第一次打开「视频」领 1 枚硬币，投稿过审再得 2 枚。硬币只能投给视频 —— <b style={{ fontWeight: 600 }}>不能充值、不能提现、不能兑换</b>。它不是钱，是一句「这条值得」。
            </span>
          </div>
        </div>
      </div>

      <Caption titles={TITLES} details={DETAILS} index={capIdx} narrow={narrow} detailColor={P.ink2}>
        <div style={{ fontSize: 12.5, color: P.ink2, marginTop: 2, opacity: tween(T, { start: CUE.close, end: CUE.close + 0.6 }) }}>
          关注 / 推荐 / 热门 / 竖屏四个页签；在推荐和竖屏里长按一条视频，能选「不感兴趣」，也能看「为什么推荐给我」。
        </div>
      </Caption>
    </Film>
  )
}
