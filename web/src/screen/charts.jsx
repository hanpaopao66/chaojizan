import React, { useLayoutEffect, useRef, useState } from 'react'

import { shortCity } from './geo.js'

/* 大屏的几张小图:手写 SVG,照设计稿的样子(原来是 ECharts)。
 *
 * 稿子里的图是 viewBox 380×148 + preserveAspectRatio="none" 拉满面板 —— 字和圆点
 * 会被横向压扁。这里量出面板的实际像素再按像素画,字形不变形。量的是布局尺寸
 * (clientWidth),整屏 transform 缩放不影响它。
 *
 * 颜色全走 screen.css 里的令牌(类名上色),这里不写色值。 */

function useBox() {
  const ref = useRef(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const read = () => setBox(b => (b.w === el.clientWidth && b.h === el.clientHeight
      ? b : { w: el.clientWidth, h: el.clientHeight }))
    read()
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, box]
}

/* 纵轴上限取「好看的整数」:1 / 2 / 2.5 / 5 × 10^n,不小于最大值 */
export function niceCeil(v) {
  if (!(v > 0)) return 1
  const mag = 10 ** Math.floor(Math.log10(v))
  for (const s of [1, 2, 2.5, 5, 10]) if (s * mag >= v) return s * mag
  return 10 * mag
}

const fmt = n => (n == null ? '–' : Math.round(n).toLocaleString('zh-CN'))

/* 近 7 天订单:单系列面积线。只标最后一天和最高的一天,其余看形状 */
export function TrendChart({ trend }) {
  const [ref, { w, h }] = useBox()
  const pts = trend || []
  const base = h - 24
  const top = 18
  const max = niceCeil(Math.max(0, ...pts.map(t => t.orders)))
  const x = i => 20 + (i * (w - 40)) / Math.max(1, pts.length - 1)
  const y = v => base - (v / max) * (base - top)
  const line = pts.map((t, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(t.orders).toFixed(1)}`).join('')
  const peak = pts.reduce((m, t, i) => (t.orders > pts[m].orders ? i : m), 0)
  // 最后一天(今天)总标;最高那天有单才标 —— 一周全是 0 时不在两头各写一个 0
  const marked = new Set(pts.length ? [pts.length - 1, ...(pts[peak].orders > 0 ? [peak] : [])] : [])
  return (
    <div className="sc-chart" ref={ref}>
      {w > 0 && pts.length > 0 && (
        <svg width={w} height={h} role="img"
          aria-label={`近 7 天订单:${pts.map(t => `${t.day} ${t.orders} 单`).join(',')}`}>
          <line className="grid base" x1="14" x2={w - 12} y1={base} y2={base} />
          <line className="grid" x1="14" x2={w - 12} y1={(base + top) / 2} y2={(base + top) / 2} />
          <line className="grid" x1="14" x2={w - 12} y1={top} y2={top} />
          <path className="sc-trend-area" d={`${line}L${x(pts.length - 1)} ${base}L${x(0)} ${base}Z`} />
          <path className="sc-trend-line" d={line} />
          {pts.map((t, i) => (
            <g key={t.day}>
              <circle className="sc-trend-dot" cx={x(i)} cy={y(t.orders)} r="3">
                <title>{`${t.day} · ${fmt(t.orders)} 单`}</title>
              </circle>
              {marked.has(i) && (
                <text className="val" x={x(i)} y={y(t.orders) - 9} textAnchor="middle">{fmt(t.orders)}</text>
              )}
              <text className="tick" x={x(i)} y={h - 6} textAnchor="middle">{t.day.replace(/^0/, '')}</text>
            </g>
          ))}
        </svg>
      )}
    </div>
  )
}

/* 分时订单:24 个小时,每小时一对柱(昨日在左、今日在右),偶数点标刻度 */
export function HourlyBars({ today, yesterday }) {
  const [ref, { w, h }] = useBox()
  const t = today || []
  const yd = yesterday || []
  const base = h - 22
  const top = 8
  const max = niceCeil(Math.max(0, ...t, ...yd))
  const slot = (w - 28) / 24
  const bw = Math.min(9, slot * 0.4)
  const hgt = v => ((v || 0) / max) * (base - top)
  return (
    <div className="sc-chart" ref={ref}>
      {w > 0 && t.length === 24 && (
        <svg width={w} height={h} role="img" aria-label="今日与昨日每小时的订单数">
          <line className="grid base" x1="14" x2={w - 12} y1={base} y2={base} />
          {t.map((v, i) => {
            const cx = 14 + slot * (i + 0.5)
            return (
              <g key={i}>
                <title>{`${i} 时 · 今日 ${fmt(v)} 单 · 昨日 ${fmt(yd[i])} 单`}</title>
                <rect className="sc-bar-yday" x={cx - bw - 0.75} y={base - hgt(yd[i])} width={bw} height={hgt(yd[i])} />
                <rect className="sc-bar-today" x={cx + 0.75} y={base - hgt(v)} width={bw} height={hgt(v)} />
                {/* 整个时段做悬停区,不用对准细柱 */}
                <rect className="hit" x={cx - slot / 2} y={top} width={slot} height={base - top} />
                {i % 2 === 0 && <text className="tick" x={cx} y={h - 6} textAnchor="middle">{i}</text>}
              </g>
            )
          })}
        </svg>
      )}
    </div>
  )
}

/* 今日订单状态:环 + 图例。状态名和顺序原样用接口的(status_dist),不合并、不改名。
 * 配色按流程走 —— 待接单是黏土色,制作到取餐是赭色两档,配送中蓝,送达到完成绿色两档;
 * 相邻两段一深一浅,红绿色弱模拟下相邻段的 OKLab 色差也在 8.9 以上(稿子原来的
 * 绿 / 黏土一对只有 3.6,几乎是一个颜色)。图例每行都写着状态名和单数,
 * 颜色不是唯一的识别手段 */
const R = 45
const C = 2 * Math.PI * R
export function StatusDonut({ dist }) {
  const rows = dist || []
  const total = rows.reduce((s, d) => s + d.count, 0)
  const live = rows.filter(d => d.count > 0)
  const gap = live.length > 1 ? 2 : 0
  let acc = 0
  const segs = live.map(d => {
    const len = (d.count / total) * C
    const seg = { key: d.status, dash: `${Math.max(0, len - gap).toFixed(2)} ${(C - Math.max(0, len - gap)).toFixed(2)}`,
      offset: (-acc).toFixed(2), title: `${d.label} ${d.count} 单` }
    acc += len
    return seg
  })
  return (
    <div className="sc-donut">
      <svg viewBox="0 0 120 120" width="120" height="120" role="img"
        aria-label={`今日订单状态:${rows.map(d => `${d.label} ${d.count} 单`).join(',')}`}>
        <circle className="track" cx="60" cy="60" r={R} />
        {segs.map(s => (
          <circle key={s.key} className={`seg sc-st-${s.key}`} cx="60" cy="60" r={R}
            strokeDasharray={s.dash} strokeDashoffset={s.offset} transform="rotate(-90 60 60)">
            <title>{s.title}</title>
          </circle>
        ))}
      </svg>
      <div className="legend">
        {rows.map(d => (
          <div key={d.status} className={`row sc-st-${d.status}`}>
            <i />
            <span className="k">{d.label}</span>
            <span className="v">{fmt(d.count)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* 近 7 天配送时长分布(取餐→送达)。分桶照接口:0–15 / 15–30 / 30–45 / 45 分以上 */
const TIMING = ['<15分', '15-30', '30-45', '>45分']
export function TimingBars({ buckets }) {
  const [ref, { w, h }] = useBox()
  const b = buckets || []
  const base = h - 18
  const top = 14
  const max = niceCeil(Math.max(0, ...b))
  const slot = (w - 28) / Math.max(1, b.length)
  const bw = Math.min(52, slot * 0.7)
  const hgt = v => (v / max) * (base - top)
  return (
    <div className="sc-chart" ref={ref}>
      {w > 0 && b.length > 0 && (
        <svg width={w} height={h} role="img"
          aria-label={`近 7 天配送时长分布:${b.map((v, i) => `${TIMING[i] ?? i} ${v} 单`).join(',')}`}>
          <line className="grid base" x1="14" x2={w - 12} y1={base} y2={base} />
          {b.map((v, i) => {
            const cx = 14 + slot * (i + 0.5)
            return (
              <g key={i}>
                <rect className="sc-bar-timing" x={cx - bw / 2} y={base - hgt(v)} width={bw} height={hgt(v)}>
                  <title>{`${TIMING[i] ?? i} · ${fmt(v)} 单`}</title>
                </rect>
                {v > 0 && <text className="val" x={cx} y={base - hgt(v) - 4} textAnchor="middle">{fmt(v)}</text>}
                <text className="tick" x={cx} y={h - 4} textAnchor="middle">{TIMING[i] ?? i}</text>
              </g>
            )
          })}
        </svg>
      )}
    </div>
  )
}

/* 城市累计订单 TOP10:横条。固定十行的格子,城市少的时候下面空着,不把一行拉满整块 */
export function CityBars({ cities }) {
  const rows = (cities || []).slice(0, 10)
  const max = Math.max(1, ...rows.map(c => c.orders))
  return (
    <div className="sc-cities" role="list">
      {rows.map(c => (
        <div key={c.city} className="row" role="listitem">
          <span className="k" title={c.city}>{shortCity(c.city)}</span>
          <span className="track"><span style={{ width: `${(c.orders / max) * 100}%` }} /></span>
          <span className="v">{fmt(c.orders)}</span>
        </div>
      ))}
    </div>
  )
}
