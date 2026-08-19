import { Alert, Button, Input, Modal, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, listRiskOrders, RiskOrder, riskVerdict, setRiskLevel, yuan } from '../api'

/**
 * 风控。
 *
 * ## 处置原因会展示给用户,而且可申诉
 *
 * 限制一个用户不是内部标记 —— 后端会把原因展示给他,他能申诉
 * (申诉落到「判责申诉」那一页)。所以原因要写得像**能被当事人读到**的话,
 * 因为它确实会被读到。
 */
const LEVELS: { value: string; label: string; danger?: boolean }[] = [
  { value: 'limited', label: '限制', danger: true },
  { value: 'frozen', label: '冻结', danger: true },
  { value: '', label: '解除' },
]

export default function RiskPage() {
  const [rows, setRows] = useState<RiskOrder[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try { setRows(await listRiskOrders()) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, ok: string) {
    try { await fn(); message.success(ok); await load() }
    catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }

  function changeLevel(it: RiskOrder, level: string, label: string) {
    let reason = level ? '疑似异常营销行为' : ''
    Modal.confirm({
      title: `${label}用户 ${it.customer_phone}?`,
      content: level ? (
        <>
          <Alert type="warning" showIcon style={{ margin: '8px 0' }}
                 message="处置原因会展示给用户本人,他可以申诉" />
          <Input.TextArea rows={2} maxLength={200} defaultValue={reason}
                          onChange={(e) => { reason = e.target.value }} />
        </>
      ) : '解除后该用户恢复正常下单。',
      okText: '确认', cancelText: '取消',
      okButtonProps: { danger: !!level },
      onOk: () => act(
        () => setRiskLevel(it.customer_id, level, reason.trim()),
        `已${label}`),
    })
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Table<RiskOrder>
        rowKey="id" loading={loading} dataSource={rows} size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 150,
            render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
          { title: '订单号', dataIndex: 'order_no', width: 185 },
          { title: '商家', dataIndex: 'merchant_name', width: 140, ellipsis: true },
          { title: '下单人', dataIndex: 'customer_phone', width: 130 },
          { title: '命中规则', width: 200,
            render: (_, it) => (it.hits ?? []).length
              ? <Space size={2} wrap>{it.hits.map((h) => (
                  <Tag key={h} color="warning">{h}</Tag>))}</Space>
              : '—' },
          { title: '金额', dataIndex: 'total_cents', width: 100, align: 'right',
            render: (v: number) => yuan(v) },
          { title: '判定', dataIndex: 'risk_status', width: 100,
            render: (v: string) => ({
              confirmed: <Tag color="error">已确认刷单</Tag>,
              cleared: <Tag color="success">已解除</Tag>,
            }[v] ?? <Tag color="warning">待判</Tag>) },
          { title: '用户状态', dataIndex: 'customer_risk_level', width: 90,
            render: (v: string) => v
              ? <Tag color="error">{v === 'frozen' ? '已冻结' : '已限制'}</Tag>
              : <Tag>正常</Tag> },
          {
            title: '处置', width: 260, fixed: 'right',
            render: (_, it) => (
              <Space size={4} wrap>
                {!it.risk_status && (
                  <>
                    <Button size="small" danger
                            onClick={() => act(
                              () => riskVerdict(it.id, 'confirmed'), '已确认刷单')}>
                      确认刷单
                    </Button>
                    <Button size="small"
                            onClick={() => act(
                              () => riskVerdict(it.id, 'cleared'), '已解除')}>
                      解除
                    </Button>
                  </>
                )}
                {LEVELS.filter((l) => l.value !== it.customer_risk_level).map((l) => (
                  <Button key={l.label} size="small" danger={l.danger}
                          type={l.danger ? 'default' : 'link'}
                          onClick={() => changeLevel(it, l.value, l.label)}>
                    {l.label}用户
                  </Button>
                ))}
              </Space>
            ),
          },
        ]}
      />
    </>
  )
}
