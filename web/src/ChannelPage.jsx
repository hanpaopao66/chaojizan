import React, { useEffect, useRef } from 'react'

import './pages.css'
import {
  CHANNELS, Glyph, STATE_LABEL, SitePage, SplitBar, channelOf, kw, useChannelState,
} from './SiteChrome.jsx'

/* 频道页(/channel/{key},设计稿 4k):一个频道的三条规矩 + 右边一块示意。
 * 六个频道同一个模板;认不出的 key 回退到「点外卖」(服务端不校验 key,见 main.py)。
 *
 * 和稿子不一样的地方:
 * - 稿子写「列表只有两种排法:离你多远、评价多好」。App 里是三种:
 *   离我近 / 评分优先 / 月售优先,都不能花钱买;
 * - 稿子第三条「不收包装费加价,菜单价就是结算价」不对:打包费由商家定、
 *   写在菜单上,而且在佣金基数里。用户侧确实没有平台服务费,改成这句;
 * - 稿子右边是「附近示例 · 高新路 500m 内」的四家店。官网没有匿名可读的附近
 *   店铺接口,所以明确标成「示例」,店名是编的,不冒充真店;
 * - 帮我送、住宿、团购没有「附近的店」这回事,右边换成一笔样单怎么分;
 * - 打车还在筹备,没有规则可写,就照实说。
 * 频道开没开读 /channels:没开的频道页顶上写明「暂未开放」。 */

// @serif-cjk-begin
const TITLES = {
  food: ['附近的店，', '按距离排，不按谁给钱排。'],
  retail: ['买菜买水果，', '和外卖同一套规矩。'],
  stay: ['订房先看规矩：', '离店才收，取消不收。'],
  voucher: ['买了没用，', '随时全额退。'],
  errand: ['帮你送、帮你买，', '只收跑腿费的 2%。'],
  ride: ['打车还在筹备，', '规矩定了先公开。'],
}
/* 三条规矩左边那一格(.cp-rules .v)也是衬线字,里面的汉字只有这几个 */
const V = { full: '全额', refund: '全退', none: '无' }
// @serif-cjk-end

const INK = '#141413'
const EARN = '#4E6B4F'
const HOLD = '#A6763E'

const SHOP_HEAD = { head: '示例 · App 里的列表长这样', sort: '离我近 · 评分 · 月售' }

const PAGES = {
  food: {
    label: '点外卖 · 商家负担 5% 封顶',
    lede: '列表只有三种排法：离你多近、评分多高、月售多少。没有「推荐」位，没有「广告」标，排名买不到。',
    rules: [
      ['5%', HOLD, '商家付菜品和打包费的 5%，订单完成才收；配送费一分不抽'],
      [V.full, EARN, '你付的配送费和小费全部给骑手，账单上单列一行'],
      ['0', INK, '用户这边不收「平台服务费」；打包费由商家定，菜单上写明'],
    ],
    side: {
      kind: 'shops', ...SHOP_HEAD,
      items: [
        ['张记面馆', '牛肉面 · 4.8 分', '210m'], ['李婶砂锅粥', '粥点 · 4.9 分', '340m'],
        ['川香居家常菜', '川菜 · 4.6 分', '420m'], ['老陈卤味', '卤味 · 4.7 分', '480m'],
      ],
      fee: '配送费 ¥5 全给骑手',
    },
  },
  retail: {
    label: '买菜买水果 · 商家负担 5% 封顶',
    lede: '和点外卖同一套配送、同一套账：商家 5% 封顶、订单完成才收，配送费全额给骑手。列表同样只按距离、评分、月售排。',
    rules: [
      ['5%', HOLD, '商家付商品和打包费的 5%，订单完成才收；配送费一分不抽'],
      [V.full, EARN, '配送费和小费全部给骑手，账单上单列一行'],
      ['0', INK, '用户这边不收「平台服务费」'],
    ],
    side: {
      kind: 'shops', ...SHOP_HEAD,
      items: [
        ['街口水果店', '水果 · 4.8 分', '260m'], ['早市蔬菜铺', '蔬菜 · 4.7 分', '390m'],
        ['便民生鲜', '肉禽蛋 · 4.6 分', '450m'], ['社区粮油店', '米面粮油 · 4.8 分', '520m'],
      ],
      fee: '配送费 ¥5 全给骑手',
    },
  },
  stay: {
    label: '住宿 · 5%，离店才收',
    lede: '订房平台普遍抽 12%–20%，还要求独家。这里只收房费的 5%，客人离店之后才收，不签排他条款。',
    rules: [
      ['5%', HOLD, '只收房费的 5%，客人离店之后才收'],
      ['0', INK, '取消、拒单、未入住，平台一分不收'],
      [V.none, INK, '没有排他条款，也没有竞价排名'],
    ],
    side: {
      kind: 'sample', cap: '一笔样单 · 住宿', total: 35600, what: '大床房 · 离店后结算',
      rows: [['商家 · 房费 − 5%', 33820, EARN], ['平台 · 房费 5%，离店后收', 1780, HOLD]],
      extra: ['取消、未入住', '¥0'],
      foot: '同一单在收 12%–20% 的订房平台，是 ¥43–71。',
    },
  },
  voucher: {
    label: '超值团购 · 核销才收 2%',
    lede: '商家只在你到店核销时付 2%；券没用，随时可以全额退。不靠「过期不退」挣钱。',
    rules: [
      ['2%', HOLD, '到店核销时收售价的 2%，没核销不收'],
      [V.refund, EARN, '没用的券随时全额退，没有「过期不退」'],
      ['0', INK, '用户买券不另收平台服务费'],
    ],
    side: {
      kind: 'sample', cap: '一张样券 · 双人套餐', total: 6800, what: '到店核销后才分账',
      rows: [['商家 · 售价 − 2%', 6664, EARN], ['平台 · 核销时收 2%', 136, HOLD]],
      extra: ['没核销就退', '全额 ¥68.00'],
      foot: '券卖出去但没核销，平台不收钱，用户随时能退。',
    },
  },
  errand: {
    label: '帮我送 / 帮我买 · 跑腿费只收 2%',
    lede: '平台只收跑腿费的 2%，账单上单列一行；帮买的商品款不抽成，剩下的跑腿费和小费全给骑手。',
    rules: [
      ['2%', HOLD, '只收跑腿费的 2%，账单上单列一行'],
      ['98%', EARN, '跑腿费剩下的 98% 和小费，全部给骑手'],
      ['0', INK, '帮买的商品款、垫付款不抽成'],
    ],
    side: {
      kind: 'sample', cap: '一笔样单 · 帮我送', total: 1200, what: '送文件 · 3.2km',
      rows: [['骑手 · 跑腿费 − 2%', 1176, EARN], ['平台 · 跑腿费 2%', 24, HOLD]],
      extra: ['小费', '全给骑手'],
      foot: '帮我买的单，商品款在账单上单列，不算进 2%。',
    },
  },
  ride: {
    label: '打车 · 筹备中',
    lede: '现在还不能叫车，计价和抽成也还没定。定下来之前先把规则公开，和其他频道记在同一套账本里。',
    rules: [],
    side: { kind: 'open' },
  },
}

const yuan2 = c => `¥${(c / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

function ShopList({ side, ch }) {
  return (
    <div className="cp-side">
      <div className="cp-side-head"><span>{side.head}</span><span className="sort">{side.sort}</span></div>
      {side.items.map(([name, meta, dist], i) => (
        <div key={name} className="sz-card cp-shop sz-enter" style={{ '--i': i }}>
          <div className="thumb" />
          <div className="tx"><div className="nm">{name}</div><div className="muted meta">{meta}</div></div>
          <div className="rt"><div className="num dist">{dist}</div><div className="earn fee">{side.fee}</div></div>
        </div>
      ))}
      <p className="note">店名是示例。真实的店在 App 里按你的位置列出，排序只有上面这三种，没有付费位。{ch.key === 'food' && <> 每一单怎么分，见<a href="/rates">费率页的样单</a>。</>}</p>
    </div>
  )
}

function SampleCard({ side, ch }) {
  const segs = side.rows.map(([k, v, c], i) => ({ key: k, value: v, color: c, opacity: i === 0 || c === HOLD ? 1 : 0.5 }))
  return (
    <div className="cp-side">
      <div className="sz-card cp-sample sz-enter">
        <div className="bar" style={{ background: ch.color }} />
        <div className="body">
          <div className="sz-cap">{side.cap}</div>
          <div className="rt-total"><span className="num">{yuan2(side.total)}</span><span className="muted">{side.what}</span></div>
          <SplitBar className="rt-bar" gap={2} segments={segs}
            label={side.rows.map(([k, v]) => `${k} ${yuan2(v)}`).join('，')} />
          <div className="sz-rows">
            {side.rows.map(([k, v, c]) => (
              <div key={k}><span className="k">{k}</span><span className="num" style={{ color: c }}>{yuan2(v)}</span></div>
            ))}
            <div className="muted"><span className="k">{side.extra[0]}</span><span>{side.extra[1]}</span></div>
          </div>
          <p className="rt-else">{side.foot}</p>
        </div>
      </div>
    </div>
  )
}

function OpenList({ stateOf }) {
  const open = CHANNELS.filter(c => stateOf(c.key) === 'open')
  return (
    <div className="cp-side">
      <div className="cp-side-head"><span>现在开着的频道</span></div>
      {open.map((c, i) => (
        <a key={c.key} href={`/channel/${c.key}`} className="sz-card cp-shop sz-enter" style={{ '--i': i }}>
          <Glyph ch={c} size={40} fontSize={19} />
          <div className="tx"><div className="nm">{c.fullName ?? c.name}</div><div className="muted meta">看这个频道的规矩</div></div>
          <div className="rt"><span className="muted">→</span></div>
        </a>
      ))}
      <p className="note">打车的计价规则公开后，会先出现在<a href="/rates">费率页</a>。</p>
    </div>
  )
}

export default function ChannelPage({ channelKey }) {
  const ch = channelOf(channelKey) || channelOf('food')
  const page = PAGES[ch.key]
  const title = TITLES[ch.key]
  const { stateOf } = useChannelState()
  const st = stateOf(ch.key)
  // 手机上频道条是横滑的,当前频道在最右边时一进来看不到 —— 把它滚进来。
  // 只动横向 scrollLeft,不用 scrollIntoView(那个会顺手把整页也滚一下)
  const pillsRef = useRef(null)
  useEffect(() => {
    const box = pillsRef.current
    const on = box?.querySelector('.cp-pill.on')
    if (box && on && box.scrollWidth > box.clientWidth) {
      box.scrollLeft = Math.max(0, on.offsetLeft - box.offsetLeft - 20)
    }
  }, [ch.key])
  return (
    <SitePage active="services" title={`超级赞 · ${ch.fullName ?? ch.name}:${title.join('')}`}>
      <div className="cp-pills-wrap">
        <nav className="cp-pills" aria-label="频道" ref={pillsRef}>
          {CHANNELS.map(c => {
            const on = c.key === ch.key
            const cs = stateOf(c.key)
            return (
              <a key={c.key} href={`/channel/${c.key}`} aria-current={on ? 'page' : undefined}
                className={`cp-pill ${on ? 'on' : ''} ${cs === 'open' ? '' : 'dim'}`}>
                <span className="g" style={{ background: on ? c.tint.replace('.12)', '.25)') : c.tint, color: c.color }}>{c.glyph}</span>
                {c.coming ? `${c.name} · 筹备中` : c.name}
              </a>
            )
          })}
        </nav>
      </div>

      <div className="sz-page cp-page">
        <div className="sz-cols cp-cols">
          <div>
            <div className="cp-head">
              <Glyph ch={ch} off={st === 'coming'} size={48} fontSize={24} />
              <div className="sz-eyebrow">频道 · {page.label}</div>
            </div>
            {st === 'closed' && (
              <p className="cp-closed">这个频道{STATE_LABEL.closed}：规则和费率都已经写在代码里，后台还没打开。开放以后，App 首页会出现它。</p>
            )}
            <h1 className="sz-h1 cp-h1">{kw(title[0])}<br />{kw(title[1])}</h1>
            <p className="sz-lede">{page.lede}</p>
            {page.rules.length > 0 && (
              <div className="cp-rules">
                {page.rules.map(([v, c, t]) => (
                  <div key={t}><span className="num v" style={{ color: c }}>{v}</span><span>{t}</span></div>
                ))}
              </div>
            )}
          </div>
          {page.side.kind === 'shops' && <ShopList side={page.side} ch={ch} />}
          {page.side.kind === 'sample' && <SampleCard side={page.side} ch={ch} />}
          {page.side.kind === 'open' && <OpenList stateOf={stateOf} />}
        </div>
      </div>
    </SitePage>
  )
}
