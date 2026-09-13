import { Card, Radio, Space, Statistic, Table, Tag } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'

import { CommunityDay, CommunityStats, communityStats } from '../../api_community'
import { Muted, fail } from './shared'
import './stats.css'

/**
 * 社区数据(#370):每天的消息数、活跃会话、投稿量、审核中位时长、举报量、处置量。
 *
 * 六个数量级差得很远(消息几万、处置几条),所以是**一数一张小图**、各自一根轴,
 * 不叠在一张双轴图里;下面的表是同一份数(悬停看得到的,表里都有)。
 * 没有新加图表库:SVG 手画,十几行的事不值得多一个依赖。口径和透明中心同一套 SQL。
 */
type Key = Exclude<keyof CommunityDay, 'day'>

const METRICS: { key: Key; label: string; unit: string; total: 'sum' | 'server' }[] = [
  { key: 'messages', label: '消息数', unit: '条', total: 'sum' },
  { key: 'active_chats', label: '活跃会话', unit: '个', total: 'server' },
  { key: 'video_submissions', label: '投稿量', unit: '个', total: 'sum' },
  { key: 'review_median_hours', label: '审核中位时长', unit: '小时', total: 'server' },
  { key: 'reports', label: '举报量', unit: '张', total: 'sum' },
  { key: 'sanctions', label: '处置量', unit: '次', total: 'sum' },
]

export default function StatsPage() {
  const [days, setDays] = useState(30)
  const [s, setS] = useState<CommunityStats | null>(null)
  const [loading, setLoading] = useState(false)
  const load = useCallback(async () => {
    setLoading(true)
    try { setS(await communityStats(days)) } catch (e) { fail(e) } finally { setLoading(false) }
  }, [days])
  useEffect(() => { void load() }, [load])

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space wrap>
        <Radio.Group value={days} optionType="button" onChange={(e) => setDays(e.target.value)}
          options={[{ value: 7, label: '近 7 天' }, { value: 30, label: '近 30 天' }, { value: 90, label: '近 90 天' }]} />
        {s && <Muted>从 {s.since} 起,按北京时间分天</Muted>}
      </Space>
      {s && (
        <Card size="small">
          <Space wrap size={24}>
            <Statistic title="待处理的聊天举报" value={s.open.chat_reports} />
            <Statistic title="待处理的视频举报" value={s.open.video_reports} />
            <Statistic title="待处理的社区申诉" value={s.open.social_appeals} />
            <Statistic title="视频审核队列" value={s.open.review_queue} />
          </Space>
        </Card>
      )}
      <div className="cviz" style={{ opacity: loading && s ? 0.5 : 1, transition: 'opacity .2s' }}>
        <div className="cviz-grid">
          {METRICS.map((m) => {
            const total = s ? (s.totals[m.key] as number | null) : null
            return (
              <div className="cviz-card" key={m.key}>
                <h4>{m.label}</h4>
                <div className="v">{total == null ? '—' : total.toLocaleString('zh-CN')}
                  <small>{m.unit}{m.total === 'sum' ? `,${days} 天合计` : m.key === 'active_chats' ? `,${days} 天去重` : `,${days} 天中位数`}</small></div>
                {s ? <Line days={s.items} k={m.key} unit={m.unit} label={m.label} /> : <div style={{ height: 120 }} />}
              </div>
            )
          })}
        </div>
      </div>
      {s && (
        <Card size="small" title="逐日明细">
          <Table<CommunityDay> rowKey="day" size="small" dataSource={[...s.items].reverse()} pagination={{ pageSize: 15 }}
            scroll={{ x: 760 }}
            columns={[
              { title: '日期', dataIndex: 'day', width: 110 },
              ...METRICS.map((m) => ({
                title: `${m.label}(${m.unit})`, dataIndex: m.key, align: 'right' as const,
                render: (v: number | null) => (v == null ? <Muted>—</Muted> : v.toLocaleString('zh-CN')),
              })),
            ]} />
          <Space direction="vertical" size={2} style={{ marginTop: 8 }}>
            {Object.entries(s.notes).map(([k, v]) => <Muted key={k}><Tag>{METRICS.find((m) => m.key === k)?.label ?? k}</Tag>{v}</Muted>)}
          </Space>
        </Card>
      )}
    </Space>
  )
}

// ---------------------------------------------------------------- 小折线图

const W = 300
const H = 120
const PAD = { l: 34, r: 30, t: 10, b: 20 }

function niceMax(v: number): number {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  const n = v / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p
}

const fmtN = (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(v >= 100000 ? 0 : 1)}万`
  : Number.isInteger(v) ? v.toLocaleString('zh-CN') : v.toFixed(1))

function Line({ days, k, unit, label }: { days: CommunityDay[]; k: Key; unit: string; label: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const vals = days.map((d) => d[k] as number | null)
  const max = niceMax(Math.max(0, ...vals.map((v) => v ?? 0)))
  const n = days.length
  const x = (i: number) => PAD.l + (n <= 1 ? 0 : (i * (W - PAD.l - PAD.r)) / (n - 1))
  const y = (v: number) => PAD.t + (H - PAD.t - PAD.b) * (1 - v / max)

  // 没有数的日子(比如当天没有审核结论,中位时长为空)断开,不连成一条假线
  const segments: [number, number][][] = []
  let cur: [number, number][] = []
  vals.forEach((v, i) => {
    if (v == null) { if (cur.length) segments.push(cur); cur = [] } else cur.push([x(i), y(v)])
  })
  if (cur.length) segments.push(cur)

  const lastIdx = [...vals.keys()].reverse().find((i) => vals[i] != null)
  const pick = (clientX: number) => {
    const r = svgRef.current?.getBoundingClientRect()
    if (!r || n === 0) return
    const px = ((clientX - r.left) / r.width) * W
    const i = Math.round(((px - PAD.l) / (W - PAD.l - PAD.r)) * (n - 1))
    setHover(Math.max(0, Math.min(n - 1, i)))
  }
  const hv = hover == null ? null : vals[hover]

  return (
    <div style={{ position: 'relative' }}>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" tabIndex={0}
           aria-label={`${label}:近 ${n} 天,每天一个点。用左右方向键逐日查看`}
           onPointerMove={(e) => pick(e.clientX)} onPointerLeave={() => setHover(null)}
           onBlur={() => setHover(null)}
           onKeyDown={(e) => {
             if (e.key === 'ArrowLeft') setHover((h) => Math.max(0, (h ?? n) - 1))
             if (e.key === 'ArrowRight') setHover((h) => Math.min(n - 1, (h ?? -1) + 1))
           }}>
        {/* 横向发丝线:0、一半、顶 */}
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(max * f)} y2={y(max * f)} stroke="var(--viz-grid)" strokeWidth={1} />
            <text className="tick" x={PAD.l - 6} y={y(max * f) + 3} textAnchor="end">{fmtN(max * f)}</text>
          </g>
        ))}
        {n > 0 && (
          <>
            <text className="tick" x={PAD.l} y={H - 4} textAnchor="start">{days[0].day.slice(5)}</text>
            <text className="tick" x={W - PAD.r} y={H - 4} textAnchor="end">{days[n - 1].day.slice(5)}</text>
          </>
        )}
        {segments.map((seg, si) => (
          <g key={si}>
            {seg.length > 1 && (
              <path d={`M${seg[0][0]},${y(0)} ${seg.map(([a, b]) => `L${a},${b}`).join(' ')} L${seg[seg.length - 1][0]},${y(0)} Z`}
                    fill="var(--viz-series-1)" opacity={0.1} />
            )}
            <path d={seg.map(([a, b], i) => `${i ? 'L' : 'M'}${a},${b}`).join(' ')} fill="none"
                  stroke="var(--viz-series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          </g>
        ))}
        {/* 末端点 + 数值:只标最后一个,别的交给悬停和下面的表 */}
        {lastIdx != null && hover == null && (
          <>
            <circle cx={x(lastIdx)} cy={y(vals[lastIdx] as number)} r={4} fill="var(--viz-series-1)"
                    stroke="var(--viz-surface)" strokeWidth={2} />
            <text className="tick" x={x(lastIdx) + 7} y={y(vals[lastIdx] as number) + 3}
                  style={{ fill: 'var(--viz-text)' }}>{fmtN(vals[lastIdx] as number)}</text>
          </>
        )}
        {hover != null && (
          <>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={H - PAD.b} stroke="var(--viz-text-2)" strokeWidth={1} />
            {hv != null && <circle cx={x(hover)} cy={y(hv)} r={4} fill="var(--viz-series-1)"
                                   stroke="var(--viz-surface)" strokeWidth={2} />}
          </>
        )}
      </svg>
      {hover != null && (
        <div className="tip" style={{
          left: `${(x(hover) / W) * 100}%`, top: 0,
          transform: `translateX(${x(hover) > W * 0.6 ? 'calc(-100% - 8px)' : '8px'})`,
        }}>
          <b>{hv == null ? '没有数据' : `${fmtN(hv)} ${unit}`}</b>
          <span className="key" />{label} · {days[hover].day}
        </div>
      )}
    </div>
  )
}
