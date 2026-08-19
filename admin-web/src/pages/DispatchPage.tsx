import { Alert, Button, Card, Col, Row, Statistic, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, DispatchOverview, getDispatch, reassignOrder, yuan } from '../api'

/**
 * 运力。
 *
 * 池子里等太久的单要人工介入 —— 改派会把单退回池子重新广播。
 * 等待时长排最前面,因为那才是「该不该动手」的判据。
 */
export default function DispatchPage() {
  const [d, setD] = useState<DispatchOverview | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try { setD(await getDispatch()) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function reassign(orderNo: string) {
    try {
      await reassignOrder(orderNo)
      message.success('已退回池子重新广播')
      await load()
    } catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        {Object.entries(d?.stats ?? {}).map(([k, v]) => (
          <Col key={k} xs={12} sm={8} lg={4}>
            <Card size="small" loading={loading}>
              <Statistic title={k} value={v} valueStyle={{ fontSize: 20 }} />
            </Card>
          </Col>
        ))}
      </Row>
      <Card size="small" title={`待接池 ${d?.pool?.length ?? 0}`}
            style={{ marginBottom: 12 }} loading={loading}>
        <Table
          rowKey="order_no" size="small" dataSource={d?.pool ?? []}
          pagination={false} scroll={{ x: 'max-content' }}
          columns={[
            // 等待时长排第一列:它是「该不该动手」的判据
            { title: '已等', dataIndex: 'wait_minutes', width: 90,
              defaultSortOrder: 'descend',
              sorter: (a, b) => a.wait_minutes - b.wait_minutes,
              render: (v: number) => (
                <b style={{ color: v >= 10 ? 'var(--sz-danger)' : undefined }}>
                  {v} 分钟
                </b>
              ) },
            { title: '订单号', dataIndex: 'order_no', width: 185 },
            { title: '商家', dataIndex: 'merchant_name', ellipsis: true },
            { title: '小费', dataIndex: 'tip_cents', width: 90, align: 'right',
              render: (v: number) => v ? yuan(v) : '—' },
            { title: '', width: 90, fixed: 'right',
              render: (_, o) => (
                <Button type="link" size="small"
                        onClick={() => reassign(o.order_no)}>改派</Button>
              ) },
          ]}
        />
      </Card>
      <Card size="small" title={`配送中 ${d?.in_flight?.length ?? 0}`} loading={loading}>
        <Table
          rowKey="order_no" size="small" dataSource={d?.in_flight ?? []}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          scroll={{ x: 'max-content' }}
          columns={[
            { title: '订单号', dataIndex: 'order_no', width: 185 },
            { title: '商家', dataIndex: 'merchant_name', ellipsis: true },
            { title: '状态', dataIndex: 'status', width: 110,
              render: (v: string) => <Tag>{v}</Tag> },
            { title: '已进行', dataIndex: 'wait_minutes', width: 90,
              render: (v: number) => `${v} 分钟` },
          ]}
        />
      </Card>
    </>
  )
}
