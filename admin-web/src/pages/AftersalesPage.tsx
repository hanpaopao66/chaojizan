import { Alert, Button, Image, Input, Modal, Select, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { AfterSale, ApiError, listAfterSales, riderFault, yuan } from '../api'

/**
 * 售后仲裁。
 *
 * ## 判骑手责任是**赔钱**动作
 *
 * 点下去会全额退用户(含配送费),商家和骑手的收入都不动 ——
 * 差额由骑手保障金承担。所以确认框里要把金额和后果写清楚,
 * 不是弹一个「确定吗」。
 */
export default function AftersalesPage() {
  const [days, setDays] = useState(7)
  const [rows, setRows] = useState<AfterSale[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try { setRows(await listAfterSales(days)) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [days])
  useEffect(() => { void load() }, [load])

  function judge(a: AfterSale) {
    let reason = ''
    Modal.confirm({
      title: '判骑手责任?',
      width: 560,
      content: (
        <>
          <Alert type="warning" showIcon style={{ margin: '8px 0' }}
                 message={`将全额退用户 ${yuan(a.total_cents)}(含配送费)`}
                 description="商家与骑手收入不受影响,差额由骑手保障金承担。" />
          <Input.TextArea rows={2} maxLength={200} placeholder="判责理由"
                          onChange={(e) => { reason = e.target.value }} />
        </>
      ),
      okText: '确认判骑手责任',
      okButtonProps: { danger: true },
      cancelText: '再看看',
      onOk: async () => {
        if (reason.trim().length < 2) {
          message.warning('请写清判责理由')
          throw new Error('理由太短')
        }
        setActing(true)
        try {
          const r = await riderFault(a.id, reason.trim())
          message.success(`已赔付 ${yuan(r.refunded_cents)}`)
          await load()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          throw e
        } finally { setActing(false) }
      },
    })
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Space style={{ marginBottom: 12 }}>
        <Select value={days} onChange={setDays} style={{ width: 120 }}
                options={[7, 14, 30].map((d) => ({ value: d, label: `近 ${d} 天` }))} />
      </Space>
      <Table<AfterSale>
        rowKey="id" loading={loading} dataSource={rows} size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 160,
            render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
          { title: '订单号', dataIndex: 'order_no', width: 190 },
          { title: '原因', dataIndex: 'reason', ellipsis: true },
          { title: '凭证', width: 120,
            render: (_, a) => a.images?.length ? (
              <Image.PreviewGroup>
                {a.images.slice(0, 3).map((u) => (
                  <Image key={u} src={u} width={32} height={32}
                         style={{ objectFit: 'cover', marginRight: 4 }} />
                ))}
              </Image.PreviewGroup>
            ) : '—' },
          { title: '订单额', dataIndex: 'total_cents', width: 100, align: 'right',
            render: (v: number) => yuan(v) },
          { title: '已退', dataIndex: 'refund_cents', width: 100, align: 'right',
            render: (v: number) => v ? yuan(v) : '—' },
          { title: '判责', dataIndex: 'fault', width: 100,
            render: (v: string) => v ? <Tag>{v}</Tag> : <Tag color="warning">未判</Tag> },
          { title: '操作', width: 130, fixed: 'right',
            render: (_, a) => !a.fault ? (
              <Button type="link" danger size="small" disabled={acting}
                      onClick={() => judge(a)}>判骑手责任</Button>
            ) : null },
        ]}
      />
    </>
  )
}
