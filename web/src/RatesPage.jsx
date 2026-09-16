import React from 'react'

import './pages.css'
import {
  CHANNELS, STATE_LABEL, SitePage, SplitBar, useChannelState, useJson,
} from './SiteChrome.jsx'
import RatesFilm from './films/RatesFilm.jsx'

/* 费率页(/rates,设计稿 4c):一张表 + 一笔样单。
 *
 * 和稿子不一样的几处,都是稿子里的事实不对:
 * - 点外卖「不收什么」稿子写「配送费、包装费」。打包费**在**佣金基数里
 *   (基数 = 菜品 + 打包费 − 商家自己出的优惠,services/payment_core),
 *   不收的是配送费和小费;
 * - 引言稿子写「这些成本按月公开在开源仓里」。开源仓的 docs/finance 目前只有
 *   说明、还没有逐月报告;按月公示的是透明中心的「月度财报」(收入侧实时聚合);
 * - 样单底下稿子写「同一单在别处:商家到手约 ¥15–17,平台拿 ¥6–8」。
 *   这组数我们核不了,改成站上一直在用的那句:行业商家总负担普遍 20% 以上,
 *   这一单(菜价 ¥21)就是 ¥4 多。
 * 哪些频道开着读 /channels,和首页、App 首页是同一份配置。
 *
 * 表上方是「同一把尺量六个频道」那支片子(films/RatesFilm.jsx,官网动画集第二批),
 * 开没开由这一页读好传进去,和底下的表挂同一句「暂未开放」。 */

const ROWS = {
  food: { rate: '5%', when: '订单完成才收', not: '配送费、小费' },
  retail: { rate: '5%', when: '同外卖', not: '配送费、小费' },
  stay: { rate: '5%', when: '离店后收房费的 5%', not: '取消、未入住' },
  voucher: { rate: '2%', when: '到店核销才收', not: '未核销的券，随时全退' },
  errand: { rate: '2%', when: '只收跑腿费的 2%', not: '商品款、垫付款' },
  ride: { rate: '—', when: '计价规则公开后再定', not: '—' },
}

const pct = r => `${(r * 100).toFixed(2)}%`

export default function RatesPage() {
  const { stateOf } = useChannelState()
  const fair = useJson('/transparency/fairness')
  const real = fair?.commission?.real_rate_30d
  return (
    <SitePage
      active="rates"
      title="超级赞 · 费率:抽多少、什么时候抽"
      desc="超级赞每个频道的费率明细:外卖和买菜 5% 封顶、团购到店核销才收 2%、跑腿 2%、住宿离店才计佣,配送费 100% 归骑手。聊天、视频、音乐、论坛、小程序一概不收钱。每一条都写清楚什么时候抽、抽在谁头上,和公开账本对得上。"
    >
      <div className="sz-page">
        <div className="sz-eyebrow">费率</div>
        <h1 className="sz-h1">抽多少、什么时候抽、<br />为什么是这个数。</h1>
        <p className="sz-lede rt-lede">5% 是上限不是目标。它要付服务器、带宽、短信、客服和核账；平台收入在透明中心按月公示，结余了就往下调，调了会留痕。</p>

        <div className="sz-film-slot"><RatesFilm stateOf={stateOf} /></div>

        <div className="sz-cols rt-cols">
          <div>
            <div className="rates rt-table">
              <div className="row head"><div>频道</div><div>平台收</div><div>什么时候收</div><div>不收什么</div></div>
              {CHANNELS.map(ch => {
                const r = ROWS[ch.key]
                const st = stateOf(ch.key)
                return (
                  <div key={ch.key} className="row">
                    <div className="ch">
                      <span className="sz-dot" style={{ background: st === 'closed' ? '#E2DED2' : ch.color }} />
                      <span className="nm">{ch.coming ? `${ch.name}（筹备）` : (ch.fullName ?? ch.name)}</span>
                      {st === 'closed' && <span className="st">{STATE_LABEL.closed}</span>}
                    </div>
                    <div className={ch.coming ? 'muted' : 'rate'}>{r.rate}</div>
                    <div data-k="什么时候收">{r.when}</div>
                    <div className="muted" data-k="不收">{r.not}</div>
                  </div>
                )
              })}
            </div>
            <p className="note">外卖、买菜的 5% 按「菜品 + 打包费 − 商家自己出的优惠」算：商家让利，平台跟着少收；平台补贴不扣商家的钱。取消的单不收。上月完成 500 单起降到 4.5%，1000 单起 4%，按月自动降档、只降不升。</p>
            {real != null && (
              <p className="note">近 {fair.window_days ?? 30} 天全平台实际平均佣金率 <b className="num hold">{pct(real)}</b>，承诺上限 {pct(fair.commission.promised_cap ?? 0.05)}。每一档有多少家店，见<a href="/transparency#fairness">透明中心</a>。</p>
            )}
          </div>

          <div className="sz-card rt-sample sz-enter">
            <div className="bar" style={{ background: '#943F2F' }} />
            <div className="body">
              <div className="sz-cap">一笔样单 · 点外卖</div>
              <div className="rt-total">
                <span className="num">¥26.00</span>
                <span className="muted">牛肉面 ×1、卤蛋 ×2 + 配送费 ¥5</span>
              </div>
              <SplitBar className="rt-bar" gap={2} label="商家 19.95 元，骑手 5 元，平台 1.05 元"
                segments={[
                  { key: 'm', value: 1995, color: '#4E6B4F' },
                  { key: 'r', value: 500, color: '#4E6B4F', opacity: 0.5 },
                  { key: 'p', value: 105, color: '#A6763E' },
                ]} />
              <div className="sz-rows">
                <div><span className="k">商家 · 菜价 ¥21 − 5%</span><span className="num earn">¥19.95</span></div>
                <div><span className="k">骑手 · 配送费全额</span><span className="num earn">¥5.00</span></div>
                <div><span className="k">平台 · 菜价 5%</span><span className="num hold">¥1.05</span></div>
                <div className="muted"><span className="k">用户额外付平台</span><span className="num thin">¥0</span></div>
              </div>
              <p className="rt-else">同一单在行业平台：商家总负担普遍 20%+，这一单就是 ¥4 多。</p>
            </div>
          </div>
        </div>
      </div>
    </SitePage>
  )
}
