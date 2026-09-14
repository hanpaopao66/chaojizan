import { Alert, Button, Descriptions, Image, Input, Modal, Radio, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, DeliveryIssue, IssueAction, listDeliveryIssues, resolveDeliveryIssue,
} from '../api'

/**
 * 配送异常仲裁。
 *
 * 骑手在路上按「异常上报」之后落到这里:找不到人、地址错、餐洒了。
 * 三种处置的后果完全不同,所以选项旁边写的是**会发生什么**,
 * 不是「继续/送达/退款」三个词。
 *
 * 后两种**是在判谁的责任**,而且各自是一个信用分的扣分项(server/app/services/credit.py):
 * 「按送达处理」判的是顾客原因;「退款」判谁看异常的种类 —— 到店未出餐、餐品不齐是商家那一环的
 * 问题,判商家责任、商家承担退款;其余(餐损、丢餐……)判骑手责任、平台先行赔付。
 * 判谁由服务端按种类定(services/delivery_fault,列表里带着 refund_fault),这里只照着写后果,
 * 不自己按种类另猜一份。以前这里写的是「判定已送达」「退款」,看不出在判谁 —— 服务端却一直
 * 按判责记(appeals 里判谁的责任谁申诉),所以名字和后果都写明白。
 */
const yuan = (cents?: number) => (cents == null ? '' : `¥${(cents / 100).toFixed(2)}`)

function actionsFor(issue: DeliveryIssue): { value: IssueAction; label: string; effect: string }[] {
  const merchantFault = issue.refund_fault === 'merchant'
  const amount = yuan(issue.refund_preview_cents)
  return [
    { value: 'continue_delivery', label: '让骑手继续送',
      effect: '订单回到配送中,骑手接着送。地址补充清楚了、商家出了餐或补齐了用这个。不判谁的责任' },
    { value: 'mark_delivered', label: '判为顾客原因,按送达处理',
      effect: '联系不上、地址有误,责任在顾客:订单按送达处理,24 小时后自动完成,骑手照常拿配送费。'
        + '记为顾客原因,扣顾客信用分,顾客 72 小时内可以申诉' },
    merchantFault
      ? { value: 'refund', label: '判为商家责任,商家承担退款',
          effect: `到店没出餐、餐没装齐,是商家那一环的问题:订单结束,餐费${amount ? ` ${amount}` : ''}`
            + '由商家承担退给顾客(这单的净额冲回,平台佣金也不收),配送费和小费照常给骑手、不退。'
            + '记为商家责任,扣商家信用分、不扣骑手的;商家 72 小时内可以在「售后判责」申诉' }
      : { value: 'refund', label: '判为骑手责任,平台先行赔付',
          effect: `餐在配送途中损坏、丢失,责任在骑手:平台全额${amount ? ` ${amount}` : ''}退给顾客并结束订单,`
            + '骑手照常拿配送费、不扣钱。记为骑手责任,扣骑手信用分,骑手 72 小时内可以申诉' },
  ]
}

/** 取值对着 `schemas.py` 的 Literal。同样别照感觉编 ——
 *  第一版写的 `no_answer` / `damaged` 后端根本没有这两个值。 */
const KINDS: Record<string, string> = {
  cannot_contact: '联系不上收件人',
  wrong_address: '地址有误',
  food_damaged: '餐品损坏',
  not_ready: '到店未出餐',
  items_missing: '餐不齐',
  other: '其他',
}

export default function IssuesPage() {
  const [rows, setRows] = useState<DeliveryIssue[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [cur, setCur] = useState<DeliveryIssue | null>(null)
  const [action, setAction] = useState<IssueAction>('continue_delivery')
  const [note, setNote] = useState('')
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try { setRows(await listDeliveryIssues('open')) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function submit() {
    if (!cur) return
    setActing(true)
    try {
      await resolveDeliveryIssue(cur.id, action, note.trim())
      message.success('已处置')
      setCur(null); setNote('')
      await load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally { setActing(false) }
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
             message="骑手在路上上报的异常。压着不处理,骑手就一直卡在那单上。" />
      <Table<DeliveryIssue>
        rowKey="id" loading={loading} dataSource={rows} size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '订单号', dataIndex: 'order_no', width: 190 },
          { title: '异常', dataIndex: 'kind', width: 140,
            render: (v: string) => <Tag color="warning">{KINDS[v] ?? v}</Tag> },
          { title: '骑手', width: 150,
            render: (_, i) => `${i.rider_name || '—'} ${i.rider_phone || ''}` },
          { title: '说明', dataIndex: 'note', ellipsis: true },
          { title: '凭证', width: 70,
            render: (_, i) => i.photo_url
              ? <Image src={i.photo_url} width={32} height={32}
                       style={{ objectFit: 'cover' }} />
              : '—' },
          { title: '操作', width: 90, fixed: 'right',
            render: (_, i) => (
              <Button type="link" onClick={() => {
                setCur(i); setAction('continue_delivery'); setNote('')
              }}>处置</Button>
            ) },
        ]}
      />
      <Modal
        open={!!cur} title={`处置异常 · ${cur?.order_no ?? ''}`} width={640}
        onCancel={() => setCur(null)} onOk={submit} confirmLoading={acting}
        okText="确认处置" cancelText="取消"
      >
        {cur && (
          <>
            <Descriptions column={1} size="small" bordered
                          style={{ marginBottom: 12 }}>
              <Descriptions.Item label="异常类型">{KINDS[cur.kind] ?? cur.kind}</Descriptions.Item>
              <Descriptions.Item label="骑手说明">{cur.note || '—'}</Descriptions.Item>
              <Descriptions.Item label="送达地址">{cur.address || '—'}</Descriptions.Item>
              <Descriptions.Item label="收件人电话">{cur.contact_phone || '—'}</Descriptions.Item>
              <Descriptions.Item label="订单状态">{cur.order_status}</Descriptions.Item>
            </Descriptions>
            {cur.photo_url && (
              <Image src={cur.photo_url} width={180} style={{ marginBottom: 12 }} />
            )}
            <Radio.Group value={action} onChange={(e) => setAction(e.target.value)}>
              {actionsFor(cur).map((a) => (
                <Radio key={a.value} value={a.value}
                       style={{ display: 'block', padding: '6px 0' }}>
                  <b>{a.label}</b>
                  <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)',
                                marginLeft: 24 }}>{a.effect}</div>
                </Radio>
              ))}
            </Radio.Group>
            <Input.TextArea rows={2} maxLength={300} value={note}
                            style={{ marginTop: 12 }}
                            onChange={(e) => setNote(e.target.value)}
                            placeholder="处置说明(选填)" />
          </>
        )}
      </Modal>
    </>
  )
}
