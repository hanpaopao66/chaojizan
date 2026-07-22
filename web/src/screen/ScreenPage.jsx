import React, { useEffect, useMemo, useRef, useState } from 'react'

import { BrandIcon } from '../BrandSvg.jsx'
import ChinaMap3D from './ChinaMap3D.jsx'
import { Chart, cityOption, fmtWan, gmvOption, hourlyOption,
  statusOption, timingOption, trendOption } from './charts.jsx'
import './screen.css'

/* 全国运营大屏(公开页):/screen
   1920×1080 设计稿整体缩放;数据 10s/5s 轮询,与公开账本同源。 */

const STATS_MS = 10000
const ORDERS_MS = 5000

function usePoll(url, ms) {
  const [data, setData] = useState(null)
  useEffect(() => {
    let alive = true
    const load = () => fetch(url)
      .then(r => (r.ok ? r.json() : null))
      .then(d => alive && d && setData(d)).catch(() => {})
    load()
    const t = setInterval(load, ms)
    return () => { alive = false; clearInterval(t) }
  }, [url, ms])
  return data
}

/* 数字翻牌:值变化时 700ms 补间滚动 */
function Roll({ value, format = v => v.toLocaleString('zh-CN') }) {
  const [shown, setShown] = useState(value ?? 0)
  const fromRef = useRef(value ?? 0)
  useEffect(() => {
    if (value == null) return
    const from = fromRef.current
    fromRef.current = value
    if (from === value) { setShown(value); return }
    const t0 = performance.now()
    let raf
    const tick = now => {
      const p = Math.min(1, (now - t0) / 700)
      const eased = 1 - (1 - p) ** 3
      setShown(Math.round(from + (value - from) * eased))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value])
  return <>{value == null ? '–' : format(shown)}</>
}

function useScale(ref) {
  useEffect(() => {
    const fit = () => {
      const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080)
      if (ref.current) {
        ref.current.style.transform =
          `translate(-50%, -50%) scale(${s.toFixed(4)})`
      }
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [ref])
}

function Clock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  const p = n => String(n).padStart(2, '0')
  return (
    <span className="sc-clock">
      {now.getFullYear()}-{p(now.getMonth() + 1)}-{p(now.getDate())}
      {' '}{p(now.getHours())}:{p(now.getMinutes())}:{p(now.getSeconds())}
    </span>
  )
}

const yuanWan = c => (c == null ? '–' : `¥${fmtWan(c / 100)}`)

function ago(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return '刚刚'
  if (s < 3600) return `${Math.floor(s / 60)}分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)}小时前`
  return `${Math.floor(s / 86400)}天前`
}

function Ticker({ orders, freshIds, showGmv }) {
  const items = orders?.items ?? []
  if (!items.length) return null
  const row = keyPrefix => items.map(o => (
    <span key={`${keyPrefix}${o.id}`}
      className={`item${freshIds.has(o.id) && !keyPrefix ? ' fresh' : ''}`}>
      <span className="ago">{ago(o.created_at)}</span>
      <span className="city">{o.city || '神秘城市'}</span>
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
      <div className="cap">📣 实时订单播报</div>
      <div className="win">
        {/* 内容复制两份做无缝循环,时长随条数走 */}
        <div className="track" style={{ '--dur': `${items.length * 4.5}s` }}>
          {row('')}{row('b')}
        </div>
      </div>
    </div>
  )
}

export default function ScreenPage() {
  const rootRef = useRef(null)
  useScale(rootRef)
  useEffect(() => { document.title = '超级赞 · 全国运营大屏' }, [])

  const stats = usePoll('/screen/stats', STATS_MS)
  const orders = usePoll(`/screen/orders/latest?limit=20`, ORDERS_MS)

  /* 新订单 → 地图涟漪 + 播报高亮。首屏不炸一屏涟漪,只记 id */
  const seenRef = useRef(null)
  const [pulses, setPulses] = useState([])
  const [freshIds, setFreshIds] = useState(() => new Set())
  useEffect(() => {
    if (!orders?.items) return
    const ids = new Set(orders.items.map(o => o.id))
    if (seenRef.current === null) { seenRef.current = ids; return }
    const fresh = orders.items.filter(o => !seenRef.current.has(o.id))
    seenRef.current = ids
    if (!fresh.length) return
    setFreshIds(new Set(fresh.map(o => o.id)))
    const born = performance.now()
    setPulses(p => [...p.slice(-4), ...fresh.slice(0, 6).map((o, i) => ({
      key: `${o.id}-${born}`, lat: o.lat, lng: o.lng, born: born + i * 120,
    }))])
  }, [orders])
  useEffect(() => {           // 涟漪播完后清理,免得数组无限涨
    if (!pulses.length) return
    const t = setTimeout(() => setPulses([]), 2600)
    return () => clearTimeout(t)
  }, [pulses])

  const reg = stats?.registrations
  const showGmv = stats?.show_gmv ?? true
  const trendOpt = useMemo(() => stats && trendOption(stats.trend), [stats])
  const hourlyOpt = useMemo(() => stats && hourlyOption(stats.hourly), [stats])
  const statusOpt = useMemo(
    () => stats && statusOption(stats.status_dist), [stats])
  const cityOpt = useMemo(() => stats && cityOption(stats.cities), [stats])
  const gmvOpt = useMemo(
    () => (stats && showGmv ? gmvOption(stats.trend) : null), [stats, showGmv])

  return (
    <div className="screen-viewport">
      <div className="screen-root" ref={rootRef}>
        <header className="sc-head">
          <BrandIcon size={36} />
          <div>
            <div className="title"><b>超级赞</b> · 全国运营大屏</div>
            <div className="slogan">让利于民 · 取之有道 · 账目为证 —— 数据与公开账本同源</div>
          </div>
          <div className="spacer" />
          {stats?.demo
            ? <span className="sc-badge demo"><i className="dot" />演示数据</span>
            : <span className="sc-badge"><i className="dot" />数据实时更新</span>}
          <Clock />
        </header>

        <div className="sc-kpis">
          <div className="sc-kpi" style={{ '--kpi': '#4DA3FF' }}>
            <div className="l">用户注册数</div>
            <div className="n"><Roll value={reg?.users.total} /></div>
            <div className="d">今日新增 <b>+<Roll value={reg?.users.today} /></b></div>
          </div>
          <div className="sc-kpi" style={{ '--kpi': '#FF5A1F' }}>
            <div className="l">商家入驻数</div>
            <div className="n"><Roll value={reg?.merchants.total} /></div>
            <div className="d">今日新增 <b>+<Roll value={reg?.merchants.today} /></b></div>
          </div>
          <div className="sc-kpi" style={{ '--kpi': '#2FBF8F' }}>
            <div className="l">骑手注册数</div>
            <div className="n"><Roll value={reg?.riders.total} /></div>
            <div className="d">今日新增 <b>+<Roll value={reg?.riders.today} /></b></div>
          </div>
          <div className="sc-kpi coming" style={{ '--kpi': '#FFB84D' }}>
            <div className="l">司机入驻数 <span className="tag">打车 · 即将开通</span></div>
            <div className="n"><Roll value={reg?.drivers.total} /></div>
            <div className="d">低抽成打车,筹备中</div>
          </div>
        </div>

        <div className="sc-main">
          <div className="sc-col">
            <section className="sc-panel">
              <h3>近 7 天订单趋势</h3>
              <div className="body">{trendOpt && <Chart option={trendOpt} />}</div>
            </section>
            <section className="sc-panel">
              <h3>分时订单 <small>今日 vs 昨日</small></h3>
              <div className="body">{hourlyOpt && <Chart option={hourlyOpt} />}</div>
            </section>
            <section className="sc-panel">
              <h3>今日订单状态分布</h3>
              <div className="body">{statusOpt && <Chart option={statusOpt} />}</div>
            </section>
          </div>

          <div className="sc-center">
            <div className="sc-map-wrap">
              <ChinaMap3D cities={stats?.cities ?? []} pulses={pulses} />
            </div>
            <div className="sc-hero">
              <div className="l">全 国 累 计 订 单</div>
              <div className="n"><Roll value={stats?.orders.total} /></div>
              <div className="sub">
                今日 <b><Roll value={stats?.orders.today} /></b> 单
                {showGmv && stats?.orders.today_gmv_cents != null &&
                  <> · 今日交易额 <b>{yuanWan(stats.orders.today_gmv_cents)}</b></>}
              </div>
              <div className="sub2">
                已覆盖 <b><Roll value={stats?.coverage?.cities} /></b> 城 ·
                服务 <b><Roll value={stats?.coverage?.merchants} /></b> 商家
                {stats?.merchant_savings &&
                  <> · 对比行业约 20% 总负担,累计为商家省下
                    <b> {yuanWan(stats.merchant_savings.saved_cents)}</b></>}
              </div>
            </div>
          </div>

          <div className="sc-col">
            <section className="sc-panel" style={{ flexGrow: 1.5 }}>
              <h3>城市累计订单 TOP10</h3>
              <div className="body">{cityOpt && <Chart option={cityOpt} />}</div>
            </section>
            <section className="sc-panel" style={{ flexGrow: 1.1, minHeight: 210 }}>
              <h3>配送网络
                <small>近7天出餐超时率 {stats?.delivery.ready_late_ratio != null
                  ? `${(stats.delivery.ready_late_ratio * 100).toFixed(1)}%` : '–'}</small>
              </h3>
              <div className="body" style={{ display: 'flex', flexDirection: 'column' }}>
                <div className="sc-duo" style={{ flex: 'none', height: 74 }}>
                  <div className="tile">
                    <div className="v"><Roll value={stats?.delivery.riders_online} /></div>
                    <div className="k">骑手在线</div>
                  </div>
                  <div className="tile">
                    <div className="v">
                      {stats?.delivery.avg_minutes ?? '–'}<small> min</small>
                    </div>
                    <div className="k">今日平均配送</div>
                  </div>
                  <div className="tile">
                    <div className="v" style={{ color: '#2FBF8F' }}>
                      <Roll value={stats?.eco?.no_tableware_orders} />
                    </div>
                    <div className="k">🌱 无需餐具单</div>
                  </div>
                </div>
                <div style={{ flex: 1, position: 'relative', marginTop: 6 }}>
                  {stats?.delivery.duration_buckets &&
                    <Chart option={timingOption(stats.delivery.duration_buckets)} />}
                </div>
              </div>
            </section>
            <section className="sc-panel">
              {showGmv ? (
                <>
                  <h3>近 7 天交易额 <small>累计 {yuanWan(stats?.orders.gmv_cents)}</small></h3>
                  <div className="body">{gmvOpt && <Chart option={gmvOpt} />}</div>
                </>
              ) : (
                <>
                  <h3>平台三原则</h3>
                  <div className="body">
                    <div className="sc-principles">
                      <div className="row"><span className="big">5%</span>
                        <span className="t">商家总负担封顶,没有隐藏费用</span></div>
                      <div className="row"><span className="big">100%</span>
                        <span className="t">配送费一分不截留,全部归骑手</span></div>
                      <div className="row"><span className="big">2%</span>
                        <span className="t">团购到店核销才收费,未核销全额退</span></div>
                    </div>
                  </div>
                </>
              )}
            </section>
          </div>
        </div>

        <Ticker orders={orders} freshIds={freshIds} showGmv={showGmv} />
      </div>
    </div>
  )
}
