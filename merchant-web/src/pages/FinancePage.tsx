import { DownloadOutlined } from '@ant-design/icons'
import {
  Alert, Button, Card, Col, Form, Input, InputNumber, Modal, Progress, Row,
  Space, Statistic, Table, Tabs, Tag, message,
} from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, CommissionTier, DayStat, FinanceOrder, InvoiceRecord,
  InvoiceSummary, Merchant, Wallet, Withdrawal, applyInvoice, commissionTier,
  createWithdrawal, downloadFile, financeDaily, financeOrders, invoiceSummary,
  merchantWallet, merchantWithdrawals, myInvoices, yuan,
} from '../api'

/** 对账中心:钱包 / 日流水(逐单可查) / 提现 / 发票 / 阶梯佣金。
 *  住宿净额(离店结算/取消扣款/违约金)已并入余额与 CSV;负余额红字并解释。 */
export default function FinancePage({ shop }: { shop: Merchant }) {
  const [wallet, setWallet] = useState<Wallet | null>(null)

  const loadWallet = useCallback(async () => {
    try {
      setWallet(await merchantWallet())
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }, [])

  useEffect(() => { loadWallet() }, [loadWallet])

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      {wallet && (
        <Card size="small">
          <Row gutter={16}>
            <Col xs={12} md={4}>
              <Statistic
                title="余额"
                value={wallet.balance_cents / 100}
                precision={2}
                prefix="¥"
                valueStyle={wallet.balance_cents < 0 ? { color: '#e5484d' } : undefined}
              />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="可提现" value={wallet.withdrawable_cents / 100}
                precision={2} prefix="¥" valueStyle={{ color: '#0E8A5F' }} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="提现中" value={wallet.pending_withdrawal_cents / 100}
                precision={2} prefix="¥" />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="已提现" value={wallet.withdrawn_cents / 100}
                precision={2} prefix="¥" />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="保证金留存" value={wallet.deposit_held_cents / 100}
                precision={2} prefix="¥" />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="累计收入" value={wallet.total_earned_cents / 100}
                precision={2} prefix="¥" />
            </Col>
          </Row>
          {wallet.balance_cents < 0 && (
            <Alert
              style={{ marginTop: 8 }}
              type="error"
              showIcon
              message="余额为负:通常来自售后冲账或到店无房违约金赔付,后续收入会自动抵扣。有疑问可联系平台客服。"
            />
          )}
        </Card>
      )}
      <Tabs
        items={[
          { key: 'daily', label: '日流水', children: <DailyTab /> },
          {
            key: 'withdraw',
            label: '提现',
            children: <WithdrawTab wallet={wallet} onChanged={loadWallet} />,
          },
          { key: 'invoice', label: '发票', children: <InvoiceTab /> },
          {
            key: 'tier',
            label: shop.biz_type === 'hotel' ? '费率说明' : '阶梯佣金',
            children: <TierTab shop={shop} />,
          },
        ]}
      />
    </Space>
  )
}

function DailyTab() {
  const [days, setDays] = useState<DayStat[]>([])
  const [detail, setDetail] = useState<{ day: string; orders: FinanceOrder[] } | null>(null)

  useEffect(() => {
    financeDaily(30).then(setDays).catch((e) =>
      message.error(e instanceof ApiError ? e.message : String(e)))
  }, [])

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button
          icon={<DownloadOutlined />}
          onClick={() => downloadFile('/merchants/me/finance/statement.csv?days=30',
            'statement-30d.csv').catch((e) =>
            message.error(e instanceof ApiError ? e.message : String(e)))}
        >
          下载对账单 CSV(近 30 天,含外卖/团购/住宿全部类型)
        </Button>
      </Space>
      <Table<DayStat>
        rowKey="day"
        dataSource={days}
        pagination={false}
        size="small"
        columns={[
          { title: '日期', dataIndex: 'day' },
          { title: '入账单数', dataIndex: 'order_count' },
          { title: '外卖流水', dataIndex: 'food_cents', render: (v: number) => yuan(v) },
          {
            title: '佣金',
            dataIndex: 'commission_cents',
            render: (v: number) => yuan(v),
          },
          {
            title: '净收入',
            dataIndex: 'net_cents',
            render: (v: number) => <b>{yuan(v)}</b>,
          },
          {
            title: '',
            render: (_, d) => (
              <Button size="small" onClick={async () => {
                try {
                  setDetail({ day: d.day, orders: await financeOrders(d.day) })
                } catch (e) {
                  message.error(e instanceof ApiError ? e.message : String(e))
                }
              }}>
                逐单明细
              </Button>
            ),
          },
        ]}
      />
      <Modal
        open={detail != null}
        title={`${detail?.day} 外卖入账明细`}
        footer={null}
        width={620}
        onCancel={() => setDetail(null)}
      >
        <Table<FinanceOrder>
          rowKey="order_no"
          dataSource={detail?.orders ?? []}
          size="small"
          pagination={false}
          columns={[
            {
              title: '单号',
              dataIndex: 'order_no',
              render: (v: string) => `…${v.slice(-8)}`,
            },
            { title: '应收', dataIndex: 'food_cents', render: (v: number) => yuan(v) },
            { title: '佣金', dataIndex: 'commission_cents', render: (v: number) => yuan(v) },
            { title: '实收', dataIndex: 'net_cents', render: (v: number) => yuan(v) },
          ]}
        />
        <div style={{ color: '#888', fontSize: 12, marginTop: 8 }}>
          住宿与团购流水见「下载对账单 CSV」,与钱包余额同源可核对
        </div>
      </Modal>
    </div>
  )
}

function WithdrawTab({ wallet, onChanged }: {
  wallet: Wallet | null
  onChanged: () => void
}) {
  const [list, setList] = useState<Withdrawal[]>([])
  const [amount, setAmount] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    merchantWithdrawals().then(setList).catch((e) =>
      message.error(e instanceof ApiError ? e.message : String(e)))
  }, [])

  useEffect(() => { load() }, [load])

  async function submit() {
    if (!amount || amount <= 0) return message.warning('请填写提现金额')
    setBusy(true)
    try {
      await createWithdrawal(Math.round(amount * 100))
      message.success('提现申请已提交,T+1 打款、零手续费')
      setAmount(null)
      load()
      onChanged()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const statusTag = (w: Withdrawal) => {
    switch (w.status) {
      case 'pending': return <Tag color="orange">处理中</Tag>
      case 'paid': return <Tag color="green">已打款</Tag>
      case 'rejected': return <Tag color="red">已驳回</Tag>
      default: return <Tag>{w.status}</Tag>
    }
  }

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <InputNumber
          min={0.01}
          value={amount}
          onChange={setAmount}
          placeholder={wallet ? `可提现 ${yuan(wallet.withdrawable_cents)}` : '金额(元)'}
          style={{ width: 220 }}
        />
        <Button type="primary" loading={busy} onClick={submit}>申请提现</Button>
        <span style={{ color: '#888', fontSize: 12 }}>T+1 打款 · 零手续费</span>
      </Space>
      <Table<Withdrawal>
        rowKey="id"
        dataSource={list}
        size="small"
        pagination={false}
        columns={[
          {
            title: '申请时间',
            dataIndex: 'created_at',
            render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
          },
          { title: '金额', dataIndex: 'amount_cents', render: (v: number) => yuan(v) },
          { title: '状态', render: (_, w) => statusTag(w) },
          {
            title: '说明',
            render: (_, w) => w.status === 'rejected'
              ? <span style={{ color: '#e5484d' }}>{w.reject_reason}</span>
              : (w.paid_note || '—'),
          },
        ]}
      />
    </div>
  )
}

function InvoiceTab() {
  const [period, setPeriod] = useState(dayjs().subtract(1, 'month').format('YYYY-MM'))
  const [summary, setSummary] = useState<InvoiceSummary | null>(null)
  const [records, setRecords] = useState<InvoiceRecord[]>([])
  const [form] = Form.useForm<{ title: string; taxNo: string; email: string }>()

  const load = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([invoiceSummary(period), myInvoices()])
      setSummary(s)
      setRecords(r)
      form.setFieldsValue({ title: s.title, taxNo: s.tax_no, email: s.email })
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }, [period, form])

  useEffect(() => { load() }, [load])

  async function apply() {
    const values = await form.validateFields()
    try {
      await applyInvoice(period, values.title, values.taxNo, values.email)
      message.success('开票申请已提交')
      load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <Row gutter={16}>
      <Col xs={24} md={10}>
        <Card size="small" title="按月开平台服务费发票">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Input
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="YYYY-MM"
              style={{ width: 140 }}
            />
            {summary && (
              <div style={{ fontSize: 13, lineHeight: 2 }}>
                外卖佣金:{yuan(summary.commission_cents)}<br />
                团购服务费:{yuan(summary.voucher_fee_cents)}<br />
                住宿服务费:{yuan(summary.stay_fee_cents)}<br />
                <b>合计可开票:{yuan(summary.total_cents)}</b>
                {summary.requested && <Tag style={{ marginLeft: 8 }}>该月已申请</Tag>}
                {!summary.period_ended && (
                  <Tag color="orange" style={{ marginLeft: 8 }}>当月账未结,月底后可开</Tag>
                )}
              </div>
            )}
            <Form form={form} layout="vertical">
              <Form.Item name="title" label="发票抬头" rules={[{ required: true }]}>
                <Input maxLength={100} />
              </Form.Item>
              <Form.Item name="taxNo" label="税号" rules={[{ required: true }]}>
                <Input maxLength={30} />
              </Form.Item>
              <Form.Item name="email" label="接收邮箱" rules={[{ required: true }]}>
                <Input maxLength={100} />
              </Form.Item>
            </Form>
            <Button
              type="primary"
              disabled={!summary || summary.requested || !summary.period_ended
                || summary.total_cents <= 0}
              onClick={apply}
            >
              申请开票
            </Button>
          </Space>
        </Card>
      </Col>
      <Col xs={24} md={14}>
        <Card size="small" title="开票记录">
          <Table<InvoiceRecord>
            rowKey="id"
            dataSource={records}
            size="small"
            pagination={false}
            columns={[
              { title: '月份', dataIndex: 'period' },
              { title: '金额', dataIndex: 'amount_cents', render: (v: number) => yuan(v) },
              { title: '状态', dataIndex: 'status' },
              { title: '抬头', dataIndex: 'title' },
            ]}
          />
        </Card>
      </Col>
    </Row>
  )
}

function TierTab({ shop }: { shop: Merchant }) {
  const [tier, setTier] = useState<CommissionTier | null>(null)

  useEffect(() => {
    if (shop.biz_type === 'hotel') return
    commissionTier().then(setTier).catch((e) =>
      message.error(e instanceof ApiError ? e.message : String(e)))
  }, [shop.biz_type])

  if (shop.biz_type === 'hotel') {
    return (
      <Alert
        type="info"
        showIcon
        message="住宿佣金固定 5%,离店(核销)后才产生"
        description="订单取消、拒单、客人未入住,平台分文不取;对账页每一笔的佣金都可逐单核对,也可在公开账本复算。"
      />
    )
  }
  if (!tier) return null
  const next = tier.next_tier_from
  const progress = next ? Math.min(100, Math.round(
    (tier.this_month_completed / next) * 100)) : 100
  return (
    <Card size="small" style={{ maxWidth: 520 }}>
      <div style={{ lineHeight: 2.2 }}>
        当前费率:<b>{(tier.commission_rate * 100).toFixed(1)}%</b>(5% 是上限,单量越大自动降档)<br />
        上月完成 {tier.last_month_completed} 单 · 本月已完成 {tier.this_month_completed} 单
        {next != null && tier.next_tier_rate != null && (
          <>
            <Progress percent={progress} />
            再完成 <b>{tier.orders_to_next}</b> 单,下月费率降到
            <b> {(tier.next_tier_rate * 100).toFixed(1)}%</b>
          </>
        )}
      </div>
    </Card>
  )
}
