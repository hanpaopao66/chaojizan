import { Alert, Card, Col, Empty, Row, Statistic, Table, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, DashboardOut, getDashboard, yuan } from '../api'

/**
 * 数据看板。
 *
 * ## 待办不是装饰,是入口
 *
 * 「待审商家 3」这种数字光看没用 —— 看到了就是要去处理。所以每个待办
 * 都点得动,直接跳到对应的页。旧的单文件后台这里只显示数字,
 * 看完还得自己去点导航。
 *
 * ## 对账告警放最上面
 *
 * 账不平是**最该被看见**的事。它排在今日订单之前,红底,
 * 而不是压在页面最下面的一张小卡里。
 */
export default function DashboardPage() {
  const nav = useNavigate()
  const [d, setD] = useState<DashboardOut | null>(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void (async () => {
      try {
        setD(await getDashboard())
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const todos: [string, number, string][] = d ? [
    ['待审商家', d.pending.merchants, '/merchants'],
    ['待审骑手', d.pending.riders, '/riders'],
    ['待打款', d.pending.withdrawals, '/withdrawals'],
    ['待回工单', d.pending.tickets, '/tickets'],
    ['待处理售后', d.pending.after_sales, '/aftersales'],
    ['住宿待确认', d.pending.stay_orders, '/stays'],
    ['住宿售后', d.pending.stay_aftersales, '/stays'],
  ] : []

  const maxGmv = Math.max(1, ...(d?.trend_7d ?? []).map((x) => x.gmv))

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}

      {d && d.audit_alerts.length > 0 && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={`对账发现 ${d.audit_alerts.length} 处不平`}
          description={
            <Table
              size="small"
              pagination={false}
              rowKey={(r, i) => `${r.check}-${i}`}
              dataSource={d.audit_alerts.slice(0, 5)}
              columns={[
                { title: '检查项', dataIndex: 'check', width: 200 },
                { title: '问题', dataIndex: 'detail' },
              ]}
            />
          }
        />
      )}

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {d && ([
          ['今日订单', String(d.today.orders)],
          ['今日 GMV', yuan(d.today.gmv_cents)],
          ['今日平台佣金', yuan(d.today.commission_cents)],
          ['活跃商家', String(d.today.active_merchants)],
          ['活跃骑手', String(d.today.active_riders)],
          ['新用户', String(d.today.new_users)],
        ] as [string, string][]).map(([t, v]) => (
          <Col key={t} xs={12} sm={8} lg={4}>
            <Card size="small" loading={loading}>
              <Statistic title={t} value={v} valueStyle={{ fontSize: 20 }} />
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={15}>
          <Card size="small" title="近 7 日订单 / GMV" loading={loading}>
            {d && d.trend_7d.length > 0 ? (
              <div style={{
                display: 'flex', alignItems: 'flex-end', gap: 10, height: 160,
              }}>
                {d.trend_7d.map((day) => (
                  <div key={day.day} style={{
                    flex: 1, display: 'flex', flexDirection: 'column',
                    alignItems: 'center', gap: 4, height: '100%',
                    justifyContent: 'flex-end',
                  }}>
                    <span style={{ fontSize: 10, color: 'var(--sz-ink-muted)' }}>
                      {yuan(day.gmv)}
                    </span>
                    <div
                      title={`${day.day}:${day.orders} 单 / ${yuan(day.gmv)}`}
                      style={{
                        width: '70%',
                        height: Math.max(4, Math.round(day.gmv / maxGmv * 100)),
                        background: 'var(--sz-clay)', opacity: 0.85,
                        borderRadius: '4px 4px 0 0',
                      }}
                    />
                    <span style={{ fontSize: 10, color: 'var(--sz-ink-muted)' }}>
                      {day.day?.slice(5)}
                    </span>
                  </div>
                ))}
              </div>
            ) : <Empty description="还没有数据" />}
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <Card size="small" title="待办" loading={loading}>
            {todos.map(([label, n, path]) => (
              <div
                key={label}
                onClick={() => n > 0 && nav(path)}
                style={{
                  display: 'flex', justifyContent: 'space-between',
                  padding: '7px 0', borderBottom: '1px solid var(--sz-line)',
                  cursor: n > 0 ? 'pointer' : 'default',
                }}
              >
                <span style={{ color: n > 0 ? 'var(--sz-ink)' : 'var(--sz-ink-muted)' }}>
                  {label}
                </span>
                {n > 0
                  ? <Tag color="warning">{n}</Tag>
                  : <span style={{ color: 'var(--sz-ink-muted)' }}>0</span>}
              </div>
            ))}
            {d && (
              <div style={{
                marginTop: 12, fontSize: 12, color: 'var(--sz-ink-muted)',
                lineHeight: 1.9,
              }}>
                累计:{d.totals.users} 用户 · {d.totals.merchants} 商家 ·
                {d.totals.riders} 骑手 · {d.totals.orders} 单
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </>
  )
}
