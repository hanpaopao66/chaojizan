import React, { useEffect, useRef, useState } from 'react'

import { BrandIcon } from '../BrandSvg.jsx'
// 数字滚动、分账条和官网同一套(900ms、段间 120ms、减少动态效果直接给终值)
import { SplitBar, useCountUp, useReducedMotion } from '../SiteChrome.jsx'
import ChinaMap from './ChinaMap.jsx'
import { CityBars, HourlyBars, StatusDonut, TimingBars, TrendChart } from './charts.jsx'
import { shortCity } from './geo.js'
import './screen.css'

/* 全国运营大屏(公开页):/screen。版式、配色、动效照设计稿「超级赞运营大屏」
 * (1920×1080,整体 transform 缩放适配任意屏幕)。
 *
 * 页面上的每个数字都来自公开接口,和公开账本同源:
 *   /screen/stats           注册、订单、趋势、分时、城市、状态、配送、住宿 / 团购 / 跑腿
 *   /screen/orders/latest   底部播报(手机号打码、坐标只到城市)
 *   /transparency/fairness  「每 100 元怎么分」、实际平均佣金率(和透明中心同一份)
 *
 * 和稿子不一样、按接口和文档核过的地方:
 * - 稿子的角标「演示数据 · 接口未连」是设计工具连不上接口时的样子。这里照实挂:
 *   接口在演示模式挂「演示数据」,这一轮没取到挂「接口未连」,都没有就不挂;
 * - 分时订单稿子只画 11–22 点,接口给的是 24 小时,全画 —— 夜里的单不能藏;
 * - 状态分布稿子是「已送达 / 配送中 / 待接单 / 已取消」四段。全屏的口径是有效订单
 *   (付了钱、没取消),没有「已取消」这一段;这里照接口的六个状态原样画;
 * - 配送时长稿子分五档(<20 / 20-30 / … / >50),接口是 15 分钟一档共四档,照接口;
 * - 「无需餐具单」接口给的是累计数,标成「累计无需餐具单」,免得当成今日;
 * - 城市 TOP10 的副标题稿子写「先把一座城跑通」,仓库里查不到这句,换成口径说明;
 * - 司机那格稿子写「计价规则公开后再开,不预热」。「计价规则公开后再开」和频道页、
 *   费率页的说法一致;「不预热」查不到出处,是一句新承诺,不替运营许;
 * - 「每 100 元」接口给到角(一位小数),照接口写,不补成两位小数装精确。
 *   稿子里「平台留存 ¥4.72」和「实际平均佣金率 4.72%」是同一个数,真实口径不是:
 *   前者按用户实付算,后者按佣金基数(菜品 + 打包 − 满减)算,两个数各写各的。 */

const STATS_MS = 10000
const ORDERS_MS = 5000
// 透明中心那份服务端缓存 1 小时,大屏十分钟拉一次足够
const FAIR_MS = 600000
const RIPPLE_S = 2.4
const RIPPLE_GAP_S = 0.8

/* 轮询一个公开接口。ok:null 还没回来 / true 这一轮拿到了 / false 这一轮没拿到
   (上一轮的数据留着,角标挂「接口未连」,不把屏清空) */
function usePoll(url, ms) {
  const [state, setState] = useState({ data: null, ok: null })
  useEffect(() => {
    let alive = true
    const load = () => fetch(url)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(data => { if (alive) setState({ data, ok: true }) })
      .catch(() => { if (alive) setState(s => ({ data: s.data, ok: false })) })
    load()
    const t = setInterval(load, ms)
    return () => { alive = false; clearInterval(t) }
  }, [url, ms])
  return state
}

const fmtInt = v => Math.round(v).toLocaleString('zh-CN')

/* 金额(分)→ 大屏写法:十万元以下写到元(¥4,932),以上写万(¥72.4 万)、亿 */
function yuan(cents) {
  const y = cents / 100
  if (Math.abs(y) >= 1e8) return `¥${(y / 1e8).toFixed(2)} 亿`
  if (Math.abs(y) >= 1e5) return `¥${(y / 1e4).toFixed(1)} 万`
  return `¥${Math.round(y).toLocaleString('zh-CN')}`
}

/* 数字:值变了从旧值滚到新值;没取到是「–」,和真的 0 分开 */
function Num({ value, format = fmtInt }) {
  const v = useCountUp(value ?? null)
  return <>{value == null || v == null ? '–' : format(v)}</>
}

function useScale(ref) {
  useEffect(() => {
    const fit = () => {
      const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080)
      if (ref.current) ref.current.style.transform = `translate(-50%, -50%) scale(${s.toFixed(4)})`
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [ref])
}

/* 北京时间:「今日」的日界是北京时间零点(接口按 Asia/Shanghai 切),时钟跟它一致 */
function Clock() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const d = new Date(now + 8 * 3600e3)
  const p = n => String(n).padStart(2, '0')
  return (
    <span className="sc-clock" title="北京时间">
      {d.getUTCFullYear()}-{p(d.getUTCMonth() + 1)}-{p(d.getUTCDate())}
      {' '}{p(d.getUTCHours())}:{p(d.getUTCMinutes())}:{p(d.getUTCSeconds())}
    </span>
  )
}

function ago(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return '刚刚'
  if (s < 3600) return `${Math.floor(s / 60)}分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)}小时前`
  return `${Math.floor(s / 86400)}天前`
}

function Panel({ tone, title, note, aside, className = '', style, children }) {
  return (
    <section className={`sc-panel ${className}`} style={style}>
      <header className="sc-ph">
        <i className={`sc-tone-${tone}`} />
        <h2>{title}</h2>
        {note != null && <small>{note}</small>}
        {aside != null && <small className="aside">{aside}</small>}
      </header>
      {children}
    </section>
  )
}

function Ticker({ items, ok, fresh, showGmv, still }) {
  const row = copy => items.map(o => (
    <span key={`${copy}${o.id}`} className={`item${fresh.has(o.id) ? ' fresh' : ''}`}
      aria-hidden={copy ? 'true' : undefined}>
      <span className="ago">{ago(o.created_at)}</span>
      {o.city && <span className="city">{shortCity(o.city)}</span>}
      <span>用户 {o.phone} 在</span>
      <span className="shop">「{o.merchant}」</span>
      <span>下单</span>
      {showGmv && o.amount_cents != null &&
        <span className="amt">¥{(o.amount_cents / 100).toFixed(1)}</span>}
      <span className="st">{o.status_label}</span>
    </span>
  ))
  return (
    <div className="sc-ticker">
      <div className="cap"><i className="sc-dot" />实时订单播报</div>
      <div className="win">
        {items.length ? (
          // 同样的内容接两份,滚到一半回到开头,看起来是无缝的;时长跟条数走,速度不变。
          // 减少动态效果时不滚,只放一份
          <div className={`track${still ? ' still' : ''}`}
            style={{ '--dur': `${items.length * 6.5}s` }}>
            {row('')}{!still && row('b')}
          </div>
        ) : <span className="empty">{ok === false ? '接口未连' : ok ? '还没有订单' : ''}</span>}
      </div>
    </div>
  )
}

export default function ScreenPage() {
  const rootRef = useRef(null)
  useScale(rootRef)
  useEffect(() => { document.title = '超级赞 · 全国运营大屏' }, [])
  const reduced = useReducedMotion()

  const statsQ = usePoll('/screen/stats', STATS_MS)
  const ordersQ = usePoll('/screen/orders/latest?limit=20', ORDERS_MS)
  const fairQ = usePoll('/transparency/fairness', FAIR_MS)
  const stats = statsQ.data
  const items = ordersQ.data?.items ?? []

  /* 新订单 → 播报那一条闪一下、地图上那座城泛一圈涟漪。
     首屏只记下已有的单,不炸一屏涟漪 */
  const seenRef = useRef(null)
  const [fresh, setFresh] = useState(() => new Set())
  const [pulses, setPulses] = useState([])
  useEffect(() => {
    const list = ordersQ.data?.items
    if (!list) return
    const ids = new Set(list.map(o => o.id))
    if (seenRef.current === null) { seenRef.current = ids; return }
    const neu = list.filter(o => !seenRef.current.has(o.id))
    seenRef.current = ids
    if (!neu.length) return
    setFresh(new Set(neu.map(o => o.id)))
    if (reduced) return
    const now = Date.now()
    setPulses(p => [
      ...p.filter(x => x.until > now),
      ...neu.slice(0, 6).map((o, i) => ({
        key: `${o.id}-${now}`, lat: o.lat, lng: o.lng, city: o.city,
        delay: i * RIPPLE_GAP_S, until: now + (i * RIPPLE_GAP_S + RIPPLE_S) * 1000,
      })),
    ].slice(-12))
  }, [ordersQ.data, reduced])
  useEffect(() => {           // 播完的涟漪摘掉,数组不无限涨
    if (!pulses.length) return undefined
    const wait = Math.min(...pulses.map(p => p.until)) - Date.now()
    const t = setTimeout(() => setPulses(p => p.filter(x => x.until > Date.now())), Math.max(50, wait + 50))
    return () => clearTimeout(t)
  }, [pulses])

  const reg = stats?.registrations
  const showGmv = stats?.show_gmv ?? true
  const drivers = reg?.drivers
  const trendSum = stats ? stats.trend.reduce((s, t) => s + t.orders, 0) : null
  const statusSum = stats ? stats.status_dist.reduce((s, d) => s + d.count, 0) : null
  const dl = stats?.delivery
  const savings = showGmv ? stats?.merchant_savings : null

  const fair = fairQ.data
  const per = fair?.per100
  const keep = per ? Math.round((per.commission - per.subsidy) * 10) / 10 : null
  const rate = fair?.commission
  const pct = (v, d = 2) => (v == null ? '–' : `${(v * 100).toFixed(d)}%`)

  // 两个轮询的接口有一个这一轮没取到,就挂「接口未连」(屏上留着的是上一轮的数)
  const warn = [stats?.demo && '演示数据',
    (statsQ.ok === false || ordersQ.ok === false) && '接口未连'].filter(Boolean).join(' · ')

  return (
    <div className="screen-viewport">
      <div className="sc-rotate-tip">本页为投屏大屏,手机建议横屏观看</div>
      <div className="screen-root" ref={rootRef}>
        <header className="sc-head">
          <BrandIcon size={36} />
          <div>
            <h1 className="sc-title">超级赞 · 全国运营大屏</h1>
            <div className="sc-slogan">让利于民 · 取之有道 · 账目为证 —— 数据与公开账本同源</div>
          </div>
          <div className="sc-spacer" />
          {warn && <span className="sc-pill warn"><i className="sc-dot" />{warn}</span>}
          <span className="sc-pill live"><i className="sc-dot" />每 {STATS_MS / 1000} 秒刷新</span>
          <Clock />
        </header>

        <div className="sc-kpis">
          {[['users', '用户注册数', 'food'], ['merchants', '商家入驻数', 'hold'],
            ['riders', '骑手注册数', 'earn']].map(([k, label, tone]) => (
            <div key={k} className="sc-kpi">
              <i className={`bar sc-tone-${tone}`} />
              <div className="body">
                <div className="l">{label}</div>
                <div className="n"><Num value={reg?.[k].total} /></div>
                <div className="d">今日新增 <b>+<Num value={reg?.[k].today} /></b></div>
              </div>
            </div>
          ))}
          <div className="sc-kpi">
            <i className="bar sc-tone-dim" />
            <div className="body">
              <div className="l">司机入驻数 <span className="sc-tag">打车 · 筹备中</span></div>
              {drivers && !drivers.coming
                ? <div className="n"><Num value={drivers.total} /></div>
                : <div className="n off">—</div>}
              <div className="d">计价规则公开后再开</div>
            </div>
          </div>
        </div>

        <div className="sc-main">
          <div className="sc-col">
            <Panel tone="food" title="近 7 天订单趋势"
              aside={<>合计 <Num value={trendSum} /> 单</>}>
              <TrendChart trend={stats?.trend} />
            </Panel>
            <Panel tone="hold" title="分时订单" note="今日 vs 昨日"
              aside={<span className="sc-legend"><span><i className="today" />今日</span><span><i className="yday" />昨日</span></span>}>
              <HourlyBars today={stats?.hourly.today} yesterday={stats?.hourly.yesterday} />
            </Panel>
            <Panel tone="earn" title="今日订单状态分布" aside={<><Num value={statusSum} /> 单</>}>
              <StatusDonut dist={stats?.status_dist} />
            </Panel>
          </div>

          <div className="sc-center">
            <div className="sc-hero">
              <div className="l">全 国 累 计 订 单</div>
              <div className="n"><Num value={stats?.orders.total} /></div>
              <div className="sub">
                今日 <b><Num value={stats?.orders.today} /></b> 单
                {showGmv && stats?.orders.today_gmv_cents != null &&
                  <> · 今日交易额 <b><Num value={stats.orders.today_gmv_cents} format={yuan} /></b></>}
              </div>
              <div className="sub2">
                已覆盖 <b><Num value={stats?.coverage?.cities} /></b> 城 ·
                服务 <b><Num value={stats?.coverage?.merchants} /></b> 商家
                {savings && <> · 对比行业约 {Math.round(savings.industry_rate * 100)}% 总负担,累计为商家省下
                  {' '}<b className="earn"><Num value={savings.saved_cents} format={yuan} /></b></>}
              </div>
            </div>
            <ChinaMap cities={stats?.cities} pulses={pulses} />
            <div className="sc-map-foot">
              <span>住宿今日 <b><Num value={stats?.stays?.today_orders} /></b> 单 ·
                {' '}<b><Num value={stats?.stays?.today_roomnights} /></b> 间夜 ·
                在住 <b><Num value={stats?.stays?.inhouse_rooms} /></b> 间</span>
              <span>团购今日核销 <b><Num value={stats?.vouchers?.today_redeemed} /></b> 张</span>
              <span>跑腿今日 <b><Num value={stats?.errands?.today_orders} /></b> 单</span>
            </div>
          </div>

          <div className="sc-col">
            <Panel tone="food" title="城市累计订单 TOP10" aside="按商家所在城市计"
              style={{ flexGrow: 1.5 }}>
              <CityBars cities={stats?.cities} />
            </Panel>
            <Panel tone="earn" title="配送网络" style={{ flexGrow: 1.1 }}
              aside={`近 7 天出餐超时率 ${pct(dl?.ready_late_ratio, 1)}`}>
              <div className="sc-tiles">
                <div className="tile">
                  <div className="v earn"><Num value={dl?.riders_online} /></div>
                  <div className="k">骑手在线</div>
                </div>
                <div className="tile">
                  <div className="v">{dl?.avg_minutes == null ? '–'
                    : <>{Math.round(dl.avg_minutes)}<small> 分</small></>}</div>
                  <div className="k">今日平均配送</div>
                </div>
                <div className="tile">
                  <div className="v earn"><Num value={stats?.eco?.no_tableware_orders} /></div>
                  <div className="k">累计无需餐具单</div>
                </div>
              </div>
              <TimingBars buckets={dl?.duration_buckets} />
            </Panel>
            <Panel tone="hold" title="每 100 元怎么分" className="sc-per100"
              aside={`近 ${fair?.window_days ?? 30} 天实算,非示意图`}>
              {per ? (
                <>
                  <SplitBar height={12} gap={3}
                    label={`商家 ${per.merchant} 元,骑手 ${per.rider} 元,平台留存 ${keep} 元`}
                    segments={[
                      { key: 'm', value: per.merchant, color: 'var(--sc-earn)' },
                      { key: 'r', value: per.rider, color: 'var(--sc-earn)', opacity: 0.5 },
                      { key: 'p', value: Math.max(0, keep), color: 'var(--sc-hold)' },
                    ]} />
                  <div className="rows">
                    <div className="row"><i className="m" /><span className="k">商家实收</span>
                      <span className="v">¥{per.merchant.toFixed(1)}</span></div>
                    <div className="row"><i className="r" /><span className="k">骑手所得(配送费 + 小费)</span>
                      <span className="v">¥{per.rider.toFixed(1)}</span></div>
                    <div className="row"><i className="p" /><span className="k">平台留存(佣金 − 补贴)</span>
                      <span className="v hold">{keep < 0 ? '−' : ''}¥{Math.abs(keep).toFixed(1)}</span></div>
                  </div>
                </>
              ) : (
                <div className="rows empty">
                  {fair ? '近 30 天还没有可以算的完成订单' : fairQ.ok === false ? '接口未连' : '读取中…'}
                </div>
              )}
              <div className="foot">
                实际平均佣金率 <b>{pct(rate?.real_rate_30d)}</b> · 承诺上限 {pct(rate?.promised_cap)} ·
                恒等式由每日 04:00 核账背书
              </div>
            </Panel>
          </div>
        </div>

        <Ticker items={items} ok={ordersQ.ok} fresh={fresh} showGmv={showGmv} still={reduced} />
      </div>
    </div>
  )
}
