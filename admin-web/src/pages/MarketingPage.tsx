import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Switch, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, CouponBatch, createCouponBatch, issueCoupon, listCouponBatches,
  listSplash, Splash, toggleSplash, toggleCouponBatch, yuan,
} from '../api'

/**
 * 营销:优惠券批次。
 *
 * ⚠️ **平台不做补贴** —— 这些券的成本口径在「平台开关」的 marketing 总开关
 * 之下,发之前先确认那个开关是开的,否则建了也不会发出去。
 */
const TRIGGERS: Record<string, string> = {
  new_user: '新客', invite: '邀请', birthday: '生日',
  repurchase: '复购', new_dish: '上新', manual: '手动发放',
}

export default function MarketingPage() {
  const [rows, setRows] = useState<CouponBatch[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(false)
  const [splash, setSplash] = useState<Splash[]>([])
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try {
      const [b, sp] = await Promise.all([listCouponBatches(), listSplash()])
      setRows(b); setSplash(sp)
    }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, ok: string) {
    try { await fn(); message.success(ok); await load() }
    catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
             message="营销总开关在「平台开关」页。总开关关着的话,这里建的批次不会发出去。" />
      <Card size="small" title="优惠券批次"
            extra={<Button type="primary" size="small"
                           onClick={() => setOpen(true)}>新建批次</Button>}>
        <Table<CouponBatch>
          rowKey="id" loading={loading} dataSource={rows} size="middle"
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            { title: '名称', dataIndex: 'name', width: 160 },
            { title: '触发', dataIndex: 'trigger', width: 100,
              render: (v: string) => <Tag>{TRIGGERS[v] ?? v}</Tag> },
            { title: '面额', dataIndex: 'amount_cents', width: 90, align: 'right',
              render: (v: number) => yuan(v) },
            { title: '门槛', dataIndex: 'min_spend_cents', width: 100, align: 'right',
              render: (v: number) => v ? `满 ${yuan(v)}` : '无门槛' },
            { title: '有效期', dataIndex: 'valid_days', width: 90,
              render: (v: number) => `${v} 天` },
            { title: '发放 / 总量', width: 130,
              render: (_, b) => `${b.issued} / ${b.total || '不限'}` },
            { title: '已核销', dataIndex: 'used', width: 90 },
            { title: '启用', width: 80,
              render: (_, b) => (
                <Switch size="small" checked={b.active}
                        onChange={() => act(() => toggleCouponBatch(b.id),
                          b.active ? '已停用' : '已启用')} />
              ) },
            // 定向发券:给某个手机号补发一张。客服补偿用的最多
            { title: '定向发', width: 90, fixed: 'right',
              render: (_, b) => (
                <Button type="link" size="small" onClick={() => {
                  let phone = ''
                  Modal.confirm({
                    title: `定向发放「${b.name}」`,
                    content: <Input placeholder="收券人手机号" maxLength={11}
                                    onChange={(e) => { phone = e.target.value }} />,
                    okText: '发放', cancelText: '取消',
                    onOk: () => {
                      if (!/^1\d{10}$/.test(phone.trim())) {
                        message.warning('手机号不对'); throw new Error('bad')
                      }
                      return act(() => issueCoupon(phone.trim(), b.id), '已发放')
                    },
                  })
                }}>发一张</Button>
              ) },
          ]}
        />
      </Card>
      <Card size="small" title={`开屏图 ${splash.length}`} style={{ marginTop: 12 }}
            loading={loading}>
        <Table<Splash>
          rowKey="id" dataSource={splash} size="small"
          pagination={false} scroll={{ x: 'max-content' }}
          locale={{ emptyText: '没有配置开屏图' }}
          columns={[
            { title: '标题', dataIndex: 'title', width: 160 },
            { title: '副标题', dataIndex: 'subtitle', ellipsis: true },
            { title: '受众', dataIndex: 'audience', width: 100,
              render: (v: string) => <Tag>{v || '全部'}</Tag> },
            { title: '停留', dataIndex: 'countdown_seconds', width: 80,
              render: (v: number) => `${v} 秒` },
            { title: '投放期', width: 200,
              render: (_, r) => `${(r.starts_at || '').slice(0, 10)} → ${(r.ends_at || '').slice(0, 10)}` },
            { title: '上线', width: 80, fixed: 'right',
              render: (_, r) => (
                <Switch size="small" checked={r.is_active}
                        onChange={() => act(() => toggleSplash(r.id),
                          r.is_active ? '已下线' : '已上线')} />
              ) },
          ]}
        />
      </Card>
      <Modal
        open={open} title="新建优惠券批次" okText="创建" cancelText="取消"
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={(v) => act(async () => {
          await createCouponBatch({
            name: v.name,
            trigger: v.trigger,
            amount_cents: Math.round(v.amount * 100),
            min_spend_cents: Math.round((v.min_spend || 0) * 100),
            valid_days: v.valid_days,
            total: v.total || 0,
          })
          setOpen(false); form.resetFields()
        }, '已创建')}>
          <Form.Item name="name" label="批次名称" rules={[{ required: true }]}>
            <Input maxLength={30} placeholder="如:新客立减" />
          </Form.Item>
          <Form.Item name="trigger" label="触发方式" rules={[{ required: true }]}
                     initialValue="new_user">
            <Select options={Object.entries(TRIGGERS)
              .map(([v, l]) => ({ value: v, label: l }))} />
          </Form.Item>
          <Form.Item name="amount" label="面额(元)" rules={[{ required: true }]}>
            <InputNumber min={0.01} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="min_spend" label="使用门槛(元,0 = 无门槛)"
                     initialValue={0}>
            <InputNumber min={0} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="valid_days" label="有效天数" initialValue={7}
                     rules={[{ required: true }]}>
            <InputNumber min={1} max={365} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="total" label="总量(0 = 不限)" initialValue={0}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
