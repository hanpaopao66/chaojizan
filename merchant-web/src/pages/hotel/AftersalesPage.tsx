import {
  Button, Card, Empty, Input, InputNumber, Modal, Space, Tag, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, StayAfterSale, merchantStayAftersales, respondStayAftersale, yuan,
} from '../../api'

const KIND_LABELS = { no_room: '到店无房', nego_refund: '协商退款' }
const STATUS_LABELS: Record<string, [string, string]> = {
  pending: ['待处理', 'orange'],
  accepted: ['已通过', 'green'],
  auto_accepted: ['已通过(超时自动成立)', 'green'],
  rejected: ['未通过', 'default'],
}

/** 售后处理:到店无房 2 小时不响应按成立处理(倒计时红字提醒);
 *  协商退同意时填退款金额,平台只留证不强制。 */
export default function AftersalesPage() {
  const [list, setList] = useState<StayAfterSale[]>([])
  const [, setTick] = useState(0)

  const load = useCallback(async () => {
    try {
      setList(await merchantStayAftersales())
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }, [])

  useEffect(() => { load() }, [load])
  // 倒计时每 30 秒重算一次
  useEffect(() => {
    const timer = window.setInterval(() => setTick((n) => n + 1), 30000)
    return () => window.clearInterval(timer)
  }, [])

  function minutesLeft(a: StayAfterSale): number {
    const created = new Date(a.created_at).getTime()
    return Math.max(0, Math.round((created + 2 * 3600e3 - Date.now()) / 60000))
  }

  function respond(a: StayAfterSale, accept: boolean) {
    let note = ''
    let refundYuan: number | null = null
    const isNego = a.kind === 'nego_refund'
    Modal.confirm({
      title: accept
        ? (isNego ? '同意协商退' : '确认无房,认罚')
        : '拒绝该申请',
      content: (
        <Space direction="vertical" style={{ width: '100%' }}>
          {accept && !isNego && (
            <span>
              将全额退款 {yuan(a.total_cents)},并从你的余额中扣除首晚 30%
              违约金赔付客人(平台分文不取)。
            </span>
          )}
          {accept && isNego && (
            <>
              <span>房费 {yuan(a.total_cents)},你同意退多少?</span>
              <InputNumber
                style={{ width: '100%' }}
                min={0}
                max={a.total_cents / 100}
                placeholder="退款金额(元)"
                onChange={(v) => { refundYuan = v }}
              />
            </>
          )}
          <Input.TextArea
            maxLength={300}
            placeholder={accept ? '给客人的说明(选填)' : '拒绝原因(会展示给客人)'}
            onChange={(e) => { note = e.target.value }}
          />
        </Space>
      ),
      okText: '确定',
      okButtonProps: accept ? {} : { danger: true },
      onOk: async () => {
        if (accept && isNego && refundYuan == null) {
          message.warning('请填写退款金额')
          return Promise.reject()
        }
        try {
          await respondStayAftersale(a.id, accept, note.trim(),
            accept && isNego ? Math.round((refundYuan ?? 0) * 100) : undefined)
          message.success('已处理')
          load()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          return Promise.reject()
        }
      },
    })
  }

  if (list.length === 0) return <Empty description="没有售后申请" />

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      {list.map((a) => {
        const [label, color] = STATUS_LABELS[a.status] ?? [a.status, 'default']
        return (
          <Card key={a.id} size="small">
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Tag color={a.kind === 'no_room' ? 'red' : 'blue'}>
                {KIND_LABELS[a.kind]}
              </Tag>
              <span>单号 …{a.order_no.slice(-6)} · {a.guest_name} · 房费 {yuan(a.total_cents)}</span>
              <span style={{ flex: 1 }} />
              <Tag color={color}>{label}</Tag>
            </div>
            {a.note && <div style={{ fontSize: 13 }}>客人说明:{a.note}</div>}
            {a.merchant_note && (
              <div style={{ fontSize: 12, color: '#888' }}>我的回应:{a.merchant_note}</div>
            )}
            {(a.status === 'accepted' || a.status === 'auto_accepted') && (
              <div style={{ fontSize: 12, color: '#0E8A5F' }}>
                退款 {yuan(a.refund_cents)}
                {a.penalty_cents > 0 && `(含违约金 ${yuan(a.penalty_cents)})`}
              </div>
            )}
            {a.status === 'pending' && (
              <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                {a.kind === 'no_room' && (
                  <span style={{ color: '#e5484d', fontSize: 12 }}>
                    剩 {minutesLeft(a)} 分钟未响应将自动按成立处理
                  </span>
                )}
                <span style={{ flex: 1 }} />
                <Button size="small" onClick={() => respond(a, false)}>拒绝</Button>
                <Button size="small" type="primary" onClick={() => respond(a, true)}>
                  {a.kind === 'no_room' ? '确认无房,认罚' : '同意退款'}
                </Button>
              </div>
            )}
          </Card>
        )
      })}
    </Space>
  )
}
