import { PrinterOutlined, SoundOutlined } from '@ant-design/icons'
import {
  Alert, Badge, Button, Card, Col, Input, InputNumber, Modal, Radio, Row,
  Space, Tag, Tooltip, message,
} from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'

import {
  ApiError, FOOD_STATUS_LABELS, FoodOrder, Merchant, customerNote,
  flagOrder, foodPickupVerify, foodRefundItem, foodReprint, foodTransition,
  foodUrgeReply, myFoodOrders, saveCustomerNote, yuan,
} from '../../api'
import { useMerchantAlerts } from '../../hooks/useMerchantAlerts'

const ONGOING = new Set(['accepted', 'ready', 'picked_up'])
const DONE = new Set(['delivered', 'completed', 'cancelled'])

/** 外卖接单台:三栏看板(轻量 KDS)。新单 WS 响铃+桌面通知,
 *  有待接单每 15 秒催办;催单橙色横幅一键回复。 */
export default function FoodOrdersPage({ shop }: { shop: Merchant }) {
  const [orders, setOrders] = useState<FoodOrder[]>([])
  const [urged, setUrged] = useState<Set<string>>(new Set())
  const [searchQ, setSearchQ] = useState('')
  const [searchResults, setSearchResults] = useState<FoodOrder[] | null>(null)
  const pendingRef = useRef(0)

  // 搜单:顾客打电话来查单时用(订单号片段/取餐码/手机尾号,≥3 字符)
  async function doSearch(q: string) {
    const trimmed = q.trim()
    if (trimmed.length < 3) {
      setSearchResults(null)
      if (trimmed) message.warning('至少输入 3 个字符')
      return
    }
    try {
      setSearchResults(await myFoodOrders(trimmed))
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  const load = useCallback(async () => {
    try {
      const list = await myFoodOrders()
      setOrders(list)
      pendingRef.current = list.filter((o) => o.status === 'paid').length
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const timer = window.setInterval(load, 15000)
    return () => window.clearInterval(timer)
  }, [load])

  const { connected, soundOn, enableSound, beep, notify } = useMerchantAlerts(
    shop.id,
    (msg) => {
      if (msg.type === 'new_order') {
        beep()
        notify('新订单', `${msg.summary ?? ''} ${yuan(msg.total_cents ?? 0)}`)
        message.info(`🔔 新订单:${msg.summary ?? ''}`)
        load()
      } else if (msg.type === 'urge' && msg.order_no) {
        beep()
        const orderNo = msg.order_no
        setUrged((prev) => new Set(prev).add(orderNo))
        message.warning({
          content: (
            <Space>
              🔥 用户催单:{msg.summary ?? ''}
              <Button
                size="small"
                onClick={async () => {
                  try {
                    await foodUrgeReply(orderNo, '马上好,正在加急制作!')
                    message.success('已回复用户')
                  } catch (e) {
                    message.error(e instanceof ApiError ? e.message : String(e))
                  }
                }}
              >
                回复:马上好
              </Button>
            </Space>
          ),
          duration: 8,
        })
      }
    },
  )

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (pendingRef.current > 0) beep()
    }, 15000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soundOn])

  const pending = orders.filter((o) => o.status === 'paid')
  const ongoing = orders.filter((o) => ONGOING.has(o.status))
  const done = orders.filter((o) => DONE.has(o.status))

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
        <Input.Search
          size="small"
          allowClear
          placeholder="搜单:订单号/取餐码/手机尾号"
          style={{ width: 240 }}
          value={searchQ}
          onChange={(e) => {
            setSearchQ(e.target.value)
            if (!e.target.value.trim()) setSearchResults(null)
          }}
          onSearch={doSearch}
        />
      </Space>
      {searchResults !== null && (
        <Card size="small" title={`搜索结果(${searchResults.length})`}
          style={{ marginBottom: 12 }}
          extra={<Button size="small" onClick={() => {
            setSearchQ(''); setSearchResults(null)
          }}>清除</Button>}>
          {searchResults.length === 0 && (
            <span style={{ color: '#999' }}>没有匹配的订单</span>
          )}
          <Row gutter={12}>
            {searchResults.map((o) => (
              <Col key={o.order_no} span={8}>
                <OrderCard order={o} urged={false} onChanged={load} />
              </Col>
            ))}
          </Row>
        </Card>
      )}
      <Row gutter={12}>
        <BoardColumn title={`待接单(${pending.length})`} highlight={pending.length > 0}>
          {pending.map((o) => (
            <OrderCard key={o.order_no} order={o} urged={urged.has(o.order_no)} onChanged={load} />
          ))}
        </BoardColumn>
        <BoardColumn title={`进行中(${ongoing.length})`}>
          {ongoing.map((o) => (
            <OrderCard key={o.order_no} order={o} urged={urged.has(o.order_no)} onChanged={load} />
          ))}
        </BoardColumn>
        <BoardColumn title={`历史(${done.length})`}>
          {done.slice(0, 30).map((o) => (
            <OrderCard key={o.order_no} order={o} urged={false} onChanged={load} />
          ))}
        </BoardColumn>
      </Row>
    </div>
  )
}

function BoardColumn({ title, highlight, children }: {
  title: string
  highlight?: boolean
  children: React.ReactNode
}) {
  return (
    <Col xs={24} md={8}>
      <Card
        size="small"
        title={<span style={{ color: highlight ? '#FF5A1F' : undefined }}>{title}</span>}
        style={{ minHeight: 300 }}
        styles={{ body: { maxHeight: 'calc(100vh - 300px)', overflowY: 'auto' } }}
      >
        {children}
      </Card>
    </Col>
  )
}

function OrderCard({ order, urged, onChanged }: {
  order: FoodOrder
  urged: boolean
  onChanged: () => void
}) {
  async function act(fn: () => Promise<unknown>, done?: string) {
    try {
      await fn()
      if (done) message.success(done)
      onChanged()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  function flagOrder_() {
    let kind: 'claim' | 'review' | 'other' = 'claim'
    let reason = ''
    Modal.confirm({
      title: '标记这一单异常',
      width: 520,
      content: (
        <div>
          <Alert
            type="info" showIcon style={{ marginBottom: 12 }}
            message="标记只上报平台核查,不会自动处置这位顾客"
            description="我们不给商家拉黑顾客的权力 —— 那会变成报复工具。职业索赔是跨店行为,平台会把多家店的标记放在一起看;有结果会在消息中心通知你。"
          />
          <Radio.Group defaultValue="claim" style={{ marginBottom: 8 }}
            onChange={(e) => { kind = e.target.value }}>
            <Radio value="claim">疑似职业索赔</Radio>
            <Radio value="review">疑似恶意差评</Radio>
            <Radio value="other">其他</Radio>
          </Radio.Group>
          <Input.TextArea
            rows={3} maxLength={300}
            placeholder="写清楚为什么可疑(至少 5 个字) —— 平台要靠这段话去核查"
            onChange={(e) => { reason = e.target.value }}
          />
        </div>
      ),
      okText: '上报平台',
      onOk: async () => {
        try {
          const r = await flagOrder(order.order_no, kind, reason.trim())
          message.info(r.note, 8)
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          return Promise.reject()
        }
      },
    })
  }

  function reject() {
    let reason = '菜品售罄,暂时无法接单'
    Modal.confirm({
      title: '拒单原因(会展示给用户,订单将全额退款)',
      content: (
        <Input.TextArea defaultValue={reason} maxLength={200}
          onChange={(e) => { reason = e.target.value }} />
      ),
      okText: '确认拒单',
      okButtonProps: { danger: true },
      onOk: () => {
        if (reason.trim().length < 2) {
          message.warning('请填写拒单原因')
          return Promise.reject()
        }
        return act(() => foodTransition(order.order_no, 'cancelled', reason.trim()), '已拒单并全额退款')
      },
    })
  }

  function refundSheet() {
    const items = order.items.filter((i) => i.price_cents > 0)
    let dishId = items[0]?.dish_id ?? 0
    let qty = 1
    Modal.confirm({
      title: '缺货退款(选缺货菜品,对应金额退给用户)',
      content: (
        <Space direction="vertical" style={{ width: '100%' }}>
          <select
            style={{ width: '100%', padding: 6 }}
            onChange={(e) => { dishId = Number(e.target.value) }}
          >
            {items.map((i) => (
              <option key={i.dish_id} value={i.dish_id}>
                {i.name}(共 {i.quantity} 份)
              </option>
            ))}
          </select>
          <InputNumber min={1} defaultValue={1} style={{ width: '100%' }}
            onChange={(v) => { qty = v ?? 1 }} addonAfter="份" />
        </Space>
      ),
      okText: '确认退款',
      onOk: () => act(() => foodRefundItem(order.order_no, dishId, qty), '已退款'),
    })
  }

  function pickupVerify() {
    let code = ''
    Modal.confirm({
      title: '核销取餐码',
      content: (
        <Input maxLength={4} placeholder="顾客报的 4 位取餐码" autoFocus
          onChange={(e) => { code = e.target.value.trim() }} />
      ),
      okText: '确认交餐',
      onOk: () => act(() => foodPickupVerify(order.order_no, code), '已交餐,订单完成'),
    })
  }

  const actions: React.ReactNode[] = []
  // 标记异常单:只在已完结的单上给入口 —— 进行中的单该先把它做完,
  // 而"这单可疑"的判断也要等结果出来才成立
  if (['completed', 'delivered', 'cancelled'].includes(order.status)) {
    actions.push(
      <Button key="flag" size="small" onClick={flagOrder_}>标记异常</Button>,
    )
  }
  if (order.status === 'paid') {
    actions.push(
      <Button key="refund" size="small" onClick={refundSheet}>缺货退款</Button>,
      <Button key="reject" size="small" danger onClick={reject}>拒单</Button>,
      <Button key="accept" size="small" type="primary"
        onClick={() => act(() => foodTransition(order.order_no, 'accepted'), '已接单')}>
        接单
      </Button>,
    )
  } else if (order.status === 'accepted') {
    actions.push(
      <Button key="refund" size="small" onClick={refundSheet}>缺货退款</Button>,
      <Button key="ready" size="small" type="primary"
        onClick={() => act(() => foodTransition(order.order_no, 'ready'), '已出餐')}>
        出餐完成
      </Button>,
    )
  } else if (order.status === 'ready') {
    if (order.pickup) {
      actions.push(
        <Button key="verify" size="small" type="primary" onClick={pickupVerify}>核销取餐码</Button>,
      )
    }
    if (order.self_delivery) {
      actions.push(
        <Button key="pick" size="small" type="primary"
          onClick={() => act(() => foodTransition(order.order_no, 'picked_up'), '已开始配送')}>
          开始配送(自送)
        </Button>,
      )
    }
  } else if (order.status === 'picked_up' && order.self_delivery) {
    actions.push(
      <Button key="deliver" size="small" type="primary"
        onClick={() => act(() => foodTransition(order.order_no, 'delivered'), '已送达')}>
        已送达
      </Button>,
    )
  }

  const prepMinutes = order.accepted_at
    ? Math.floor((Date.now() - new Date(order.accepted_at).getTime()) / 60000)
    : null

  return (
    <Card
      size="small"
      style={{
        marginBottom: 8,
        border: order.ready_late ? '1.5px solid #e5484d' : undefined,
      }}
    >
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <b style={{ flex: 1 }}>
          {order.items.map((i) => `${i.name}×${i.quantity}`).join('、')}
        </b>
        {urged && <Tag color="orange">催</Tag>}
        {order.pickup && (
          <Tag color="blue">自取{order.pickup_code ? ` ${order.pickup_code}` : ''}</Tag>
        )}
        <Tag>{FOOD_STATUS_LABELS[order.status] ?? order.status}</Tag>
        <Button
          size="small"
          type="text"
          icon={<PrinterOutlined />}
          title="补打小票(云打印)"
          onClick={() => act(() => foodReprint(order.order_no), '已发送到云打印机')}
        />
      </div>
      {order.status === 'accepted' && prepMinutes != null && (
        <div style={{
          fontSize: 12, fontWeight: 600,
          color: order.ready_late ? '#e5484d' : '#0E8A5F',
        }}>
          {order.ready_late ? `⚠ 出餐超时 · 已备餐 ${prepMinutes} 分钟` : `备餐中 · 已 ${prepMinutes} 分钟`}
        </div>
      )}
      <div style={{ fontSize: 13, color: '#555' }}>
        {yuan(order.total_cents)}{order.address ? ` · ${order.address}` : ''}
      </div>
      {order.remark && <div style={{ fontSize: 12, color: '#888' }}>备注:{order.remark}</div>}
      {/* 本店对这位顾客的备注:"302 那位不要香菜" —— 老客维护靠这个,
          在接单台上就能看到、就能改,回头再找就没人记了 */}
      <CustomerNoteLine order={order} />
      {order.status === 'cancelled' && order.cancel_reason && (
        <div style={{ fontSize: 12, color: '#e5484d' }}>取消原因:{order.cancel_reason}</div>
      )}
      {order.refund_cents > 0 && (
        <div style={{ fontSize: 12, color: '#e5484d' }}>
          已退款 {yuan(order.refund_cents)}({order.refund_note})
        </div>
      )}
      {actions.length > 0 && (
        <div style={{ marginTop: 6, display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          {actions}
        </div>
      )}
    </Card>
  )
}


/**
 * 接单台上的顾客备注行。
 *
 * 「302 那位不要香菜」—— 老客维护靠这个。放在接单台而不是单独一个页面:
 * 备注要在**看到这单的时候**就出现,回头再去翻就没人记了。
 *
 * 只对本店可见 —— 这是顾客的个人信息,商家能记是因为他在服务这个人,
 * 不是因为他拥有这份数据。
 */
function CustomerNoteLine({ order }: { order: FoodOrder }) {
  const [note, setNote] = useState<string | null>(null)
  const [tags, setTags] = useState<string[]>([])

  useEffect(() => {
    let alive = true
    customerNote(order.customer_id)
      .then((r) => { if (alive) { setNote(r.note); setTags(r.tags) } })
      .catch(() => { if (alive) setNote('') })
    return () => { alive = false }
  }, [order.customer_id])

  if (note === null) return null

  function edit() {
    let draft = note ?? ''
    let draftTags = tags.join(' ')
    Modal.confirm({
      title: '这位顾客的备注(只你自己看得到)',
      content: (
        <div>
          <Input.TextArea
            rows={2} maxLength={200} defaultValue={draft}
            placeholder="如:不要香菜,喜欢多辣"
            onChange={(e) => { draft = e.target.value }}
          />
          <Input
            style={{ marginTop: 8 }} maxLength={80}
            defaultValue={draftTags}
            placeholder="口味标签,空格分隔:忌香菜 重辣"
            onChange={(e) => { draftTags = e.target.value }}
          />
        </div>
      ),
      okText: '保存',
      onOk: async () => {
        const t = draftTags.split(/\s+/).filter(Boolean).slice(0, 8)
        try {
          await saveCustomerNote(order.customer_id, draft.trim(), t)
          setNote(draft.trim())
          setTags(t)
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          return Promise.reject()
        }
      },
    })
  }

  return (
    <div style={{ fontSize: 12, marginTop: 2 }}>
      {tags.map((t) => (
        <Tag key={t} color="blue" style={{ marginInlineEnd: 4 }}>{t}</Tag>
      ))}
      <Tooltip title="只你自己看得到,不跨店">
        <a onClick={edit} style={{ color: note ? '#1677ff' : '#bbb' }}>
          {note || '＋记一句'}
        </a>
      </Tooltip>
    </div>
  )
}
