import { SoundOutlined } from '@ant-design/icons'
import {
  Alert, Badge, Button, Card, Col, Empty, Input, Modal, Row, Space, Tag,
  Tabs, message,
} from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'

import {
  ApiError, Merchant, StayOrder, stayCheckin, stayCheckout, stayConfirm,
  stayMerchantOrders, stayReject, yuan,
} from '../../api'
import { useMerchantAlerts } from '../../hooks/useMerchantAlerts'

/** 酒店前台工作台:今日四列看板(待确认/预抵/在住/预离)+ 全部订单。
 *  新住宿订单 WS 响铃 + 桌面通知;有待确认单每 15 秒提醒直到处理。 */
export default function FrontDeskPage({ shop }: { shop: Merchant }) {
  const [pending, setPending] = useState<StayOrder[]>([])
  const [arriving, setArriving] = useState<StayOrder[]>([])
  const [inhouse, setInhouse] = useState<StayOrder[]>([])
  const [leaving, setLeaving] = useState<StayOrder[]>([])
  const [all, setAll] = useState<StayOrder[]>([])
  const pendingRef = useRef(0)

  const load = useCallback(async () => {
    try {
      const [p, a, i, l, everything] = await Promise.all([
        stayMerchantOrders('pending'),
        stayMerchantOrders('arriving'),
        stayMerchantOrders('inhouse'),
        stayMerchantOrders('leaving'),
        stayMerchantOrders('all'),
      ])
      setPending(p)
      setArriving(a)
      setInhouse(i)
      setLeaving(l)
      setAll(everything)
      pendingRef.current = p.length
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }, [])

  useEffect(() => { load() }, [load])

  const { connected, soundOn, enableSound, beep, notify } = useMerchantAlerts(
    shop.id,
    (msg) => {
      if (msg.type === 'new_stay_order') {
        beep()
        notify('新住宿订单', `${msg.summary ?? ''} ${yuan(msg.total_cents ?? 0)}`)
        message.info(`🔔 新住宿订单:${msg.summary ?? ''}`)
        load()
      }
    },
  )

  // 待确认催办:每 15 秒响一次直到清零(声音开启时)
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (pendingRef.current > 0) beep()
    }, 15000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soundOn])

  // 轮询保底(WS 断线也不漏单)
  useEffect(() => {
    const timer = window.setInterval(load, 20000)
    return () => window.clearInterval(timer)
  }, [load])

  return (
    <div>
      {!soundOn && (
        <Alert
          type="warning"
          showIcon
          icon={<SoundOutlined />}
          style={{ marginBottom: 12 }}
          message="点击开启新单声音提醒(浏览器要求手动开启一次)"
          action={<Button size="small" type="primary" onClick={enableSound}>开启声音</Button>}
        />
      )}
      <Space style={{ marginBottom: 8, fontSize: 12, color: '#888' }}>
        <Badge status={connected ? 'success' : 'error'} />
        {connected ? '实时听单中' : '连接中断,轮询保底'}
      </Space>
      <Tabs
        items={[
          {
            key: 'today',
            label: '今日看板',
            children: (
              <Row gutter={12}>
                <BoardColumn title={`待确认(${pending.length})`} orders={pending} onChanged={load} highlight />
                <BoardColumn title={`今日预抵(${arriving.length})`} orders={arriving} onChanged={load} />
                <BoardColumn title={`在住(${inhouse.length})`} orders={inhouse} onChanged={load} />
                <BoardColumn title={`今日预离(${leaving.length})`} orders={leaving} onChanged={load} />
              </Row>
            ),
          },
          {
            key: 'all',
            label: '全部订单',
            children: (
              <Row gutter={[12, 12]}>
                {all.length === 0 && <Col span={24}><Empty description="还没有订单" /></Col>}
                {all.map((o) => (
                  <Col key={o.order_no} xs={24} md={12} xl={8}>
                    <OrderCard order={o} onChanged={load} />
                  </Col>
                ))}
              </Row>
            ),
          },
        ]}
      />
    </div>
  )
}

function BoardColumn({ title, orders, onChanged, highlight }: {
  title: string
  orders: StayOrder[]
  onChanged: () => void
  highlight?: boolean
}) {
  return (
    <Col xs={24} md={12} xl={6}>
      <Card
        size="small"
        title={<span style={{ color: highlight && orders.length > 0 ? '#FF5A1F' : undefined }}>{title}</span>}
        style={{ minHeight: 200 }}
      >
        {orders.length === 0
          ? <div style={{ color: '#bbb', textAlign: 'center', padding: 24 }}>无</div>
          : orders.map((o) => (
              <OrderCard key={o.order_no} order={o} onChanged={onChanged} compact />
            ))}
      </Card>
    </Col>
  )
}

const STATUS_COLORS: Record<string, string> = {
  paid: 'orange', confirmed: 'blue', checked_in: 'green', completed: 'default',
}

function OrderCard({ order, onChanged, compact }: {
  order: StayOrder
  onChanged: () => void
  compact?: boolean
}) {
  async function act(fn: () => Promise<StayOrder>, done?: (o: StayOrder) => string) {
    try {
      const updated = await fn()
      if (done) message.success(done(updated))
      onChanged()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  function confirmOrder() {
    Modal.confirm({
      title: '确认订单',
      content: `确认后请为客人保留房间:${order.room_type_name}×${order.rooms_qty},` +
        `${order.checkin_date} 入住 ${order.nights} 晚`,
      okText: '确认',
      onOk: () => act(() => stayConfirm(order.order_no), () => '已确认,客人会收到通知'),
    })
  }

  function rejectOrder() {
    let reason = '满房,暂时无法接待'
    Modal.confirm({
      title: '拒单原因(会展示给客人,订单全额退款)',
      content: (
        <Input.TextArea
          defaultValue={reason}
          maxLength={100}
          onChange={(e) => { reason = e.target.value }}
        />
      ),
      okText: '确认拒单',
      okButtonProps: { danger: true },
      onOk: () => {
        if (reason.trim().length < 2) {
          message.warning('请填写拒单原因')
          return Promise.reject()
        }
        return act(() => stayReject(order.order_no, reason.trim()),
          () => '已拒单,房费将全额退回客人')
      },
    })
  }

  function checkinOrder() {
    Modal.confirm({
      title: '办理入住',
      content: `请核对入住人:${order.guest_name} ${order.guest_phone}`,
      okText: '办理入住',
      onOk: () => act(() => stayCheckin(order.order_no), () => '已办理入住'),
    })
  }

  function checkoutOrder() {
    Modal.confirm({
      title: '办理离店',
      content: `离店后结算:实收 = 房费 ${yuan(order.total_cents)} − 5% 佣金,入账到店铺钱包`,
      okText: '办理离店',
      onOk: () => act(() => stayCheckout(order.order_no),
        (o) => `已离店,实收 ${yuan(o.net_cents)}(佣金 ${yuan(o.fee_cents)})`),
    })
  }

  const actions = order.status === 'paid'
    ? [
        <Button key="r" size="small" onClick={rejectOrder}>拒单</Button>,
        <Button key="c" size="small" type="primary" onClick={confirmOrder}>确认</Button>,
      ]
    : order.status === 'confirmed'
      ? [<Button key="i" size="small" type="primary" onClick={checkinOrder}>办理入住</Button>]
      : order.status === 'checked_in'
        ? [<Button key="o" size="small" type="primary" onClick={checkoutOrder}>办理离店</Button>]
        : []

  return (
    <Card size="small" style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <b>{order.room_type_name} × {order.rooms_qty}</b>
        <Tag color={STATUS_COLORS[order.status]}>{order.status_label}</Tag>
      </div>
      <div style={{ fontSize: 13, color: '#555' }}>
        {order.checkin_date} → {order.checkout_date}({order.nights} 晚) · {yuan(order.total_cents)}
      </div>
      <div style={{ fontSize: 13 }}>
        {order.guest_name} · <a href={`tel:${order.guest_phone}`}>{order.guest_phone}</a>
      </div>
      {order.arrival_note && (
        <div style={{ fontSize: 12, color: '#888' }}>备注:{order.arrival_note}</div>
      )}
      {!compact && (
        <div style={{ fontSize: 12, color: '#888' }}>{order.cancel_policy_text}</div>
      )}
      {order.status === 'completed' && (
        <div style={{ fontSize: 12, color: '#0E8A5F', fontWeight: 600 }}>
          实收 {yuan(order.net_cents)}(佣金 {yuan(order.fee_cents)})
        </div>
      )}
      {order.refund_cents > 0 && (
        <div style={{ fontSize: 12, color: '#e5484d' }}>
          已退款 {yuan(order.refund_cents)}({order.refund_note})
        </div>
      )}
      {order.status === 'noshow' && (
        <div style={{ fontSize: 12, color: '#888' }}>
          系统已按政策处理:扣首晚 {yuan(order.net_cents)} 归你,其余退客人
        </div>
      )}
      {actions.length > 0 && (
        <div style={{ marginTop: 8, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          {actions}
        </div>
      )}
    </Card>
  )
}
