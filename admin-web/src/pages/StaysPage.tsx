import { Alert, Card, DatePicker, Select, Space, Table, Tag } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, listStayAftersales, listStayOrders, StayAfterSale, StayOrder, yuan,
} from '../api'

/**
 * 住宿。
 *
 * 资金三行(房费 → 佣金 → 商家实收)和商家对账页、公开账本**同源**。
 * 这一页只读 —— 住宿的处置动作在商家端和售后流程里,平台不在这里改单。
 */
const STATUS: Record<string, string> = {
  paid: '待商家确认', confirmed: '待入住', checked_in: '在住',
  completed: '已离店', cancelled: '已取消', rejected: '商家拒单', noshow: '未入住',
}

export default function StaysPage() {
  const [status, setStatus] = useState('')
  const [day, setDay] = useState('')
  const [orders, setOrders] = useState<StayOrder[]>([])
  const [after, setAfter] = useState<StayAfterSale[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try {
      const [o, a] = await Promise.all([
        listStayOrders(status, day), listStayAftersales(),
      ])
      setOrders(o); setAfter(a)
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [status, day])
  useEffect(() => { void load() }, [load])

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Card size="small" title="住宿订单" style={{ marginBottom: 12 }}
            extra={
              <Space>
                <Select value={status} onChange={setStatus} style={{ width: 140 }}
                        options={[{ value: '', label: '全部状态' },
                          ...Object.entries(STATUS).map(([v, l]) => ({ value: v, label: l }))]} />
                <DatePicker onChange={(_, s) => setDay(s as string)}
                            placeholder="按入住日" />
              </Space>
            }>
        <Table<StayOrder>
          rowKey="order_no" loading={loading} dataSource={orders} size="middle"
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            { title: '单号', dataIndex: 'order_no', width: 185 },
            { title: '酒店', dataIndex: 'hotel', width: 150, ellipsis: true },
            { title: '房型×间', width: 150,
              render: (_, o) => `${o.room_type} × ${o.rooms_qty}` },
            { title: '入住-离店', width: 190,
              render: (_, o) => `${o.checkin_date} → ${o.checkout_date}(${o.nights} 晚)` },
            { title: '入住人', dataIndex: 'guest_name', width: 100 },
            { title: '状态', dataIndex: 'status', width: 110,
              render: (v: string) => <Tag>{STATUS[v] ?? v}</Tag> },
            // 资金三行:和商家对账页、公开账本同源
            { title: '房费', dataIndex: 'total_cents', width: 100, align: 'right',
              render: (v: number) => yuan(v) },
            { title: '佣金', dataIndex: 'fee_cents', width: 100, align: 'right',
              render: (v: number) => (
                <span style={{ color: 'var(--sz-hold)' }}>{yuan(v)}</span>) },
            { title: '商家实收', dataIndex: 'net_cents', width: 110, align: 'right',
              render: (v: number) => (
                <b style={{ color: 'var(--sz-earn)' }}>{yuan(v)}</b>) },
            { title: '退款', dataIndex: 'refund_cents', width: 100, align: 'right',
              render: (v: number) => v ? yuan(v) : '—' },
          ]}
        />
      </Card>
      <Card size="small" title={`住宿售后 ${after.length}`}>
        <Table<StayAfterSale>
          rowKey="id" loading={loading} dataSource={after} size="middle"
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 150,
              render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
            { title: '单号', dataIndex: 'order_no', width: 185 },
            { title: '酒店', dataIndex: 'hotel', width: 150, ellipsis: true },
            { title: '类型', dataIndex: 'kind', width: 110,
              render: (v: string) => <Tag>{v}</Tag> },
            { title: '说明', dataIndex: 'note', ellipsis: true },
            { title: '状态', dataIndex: 'status', width: 100,
              render: (v: string) => <Tag>{v}</Tag> },
            { title: '退款', dataIndex: 'refund_cents', width: 100, align: 'right',
              render: (v: number) => v ? yuan(v) : '—' },
            { title: '违约金', dataIndex: 'penalty_cents', width: 100, align: 'right',
              render: (v: number) => v ? yuan(v) : '—' },
          ]}
        />
      </Card>
    </>
  )
}
