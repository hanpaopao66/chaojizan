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
 */
const ACTIONS: { value: IssueAction; label: string; effect: string }[] = [
  { value: 'continue_delivery', label: '让骑手继续送',
    effect: '订单回到配送中,骑手接着送。地址补充清楚了用这个' },
  { value: 'mark_delivered', label: '判定已送达',
    effect: '订单直接完成,骑手照常拿配送费。人已收到但没点确认时用' },
  { value: 'refund', label: '退款',
    effect: '退用户钱并结束订单。餐损毁、确实送不到时用' },
]

const KINDS: Record<string, string> = {
  no_answer: '联系不上收件人',
  wrong_address: '地址有误',
  damaged: '餐品损坏',
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
              {ACTIONS.map((a) => (
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
