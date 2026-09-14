import { Alert, Button, Input, Modal, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, Ticket, closeTicket, listTickets, replyTicket, resolveCreditAppeal,
} from '../api'

const CREDIT_KIND: Record<string, string> = {
  delivery_fault: '配送异常(判为顾客原因)',
  violation: '违规记录',
}
const CREDIT_STATUS: Record<string, string> = {
  open: '待复核', upheld: '已维持原判', overturned: '申诉成立,不再计分',
}

/** 客服工单。回复会推给提单人,关闭之后就不再接受追问。
 *
 *  信用分申诉也走工单(原来的申诉通道接不上的时候):这种工单要先给出「申诉成立 / 维持原判」,
 *  结论由服务端写回工单并通知顾客;没下结论之前工单关不掉(服务端 409)。 */
export default function TicketsPage() {
  const [rows, setRows] = useState<Ticket[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [cur, setCur] = useState<Ticket | null>(null)
  const [reply, setReply] = useState('')
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try { setRows(await listTickets()) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, ok: string) {
    setActing(true)
    try { await fn(); message.success(ok); setCur(null); setReply(''); await load() }
    catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
    finally { setActing(false) }
  }

  const credit = cur?.credit_appeal
  const creditOpen = credit?.status === 'open'

  function resolve(result: 'upheld' | 'overturned') {
    if (!credit) return
    if (reply.trim().length < 2) {
      message.warning('写一句复核结论(会原样告诉顾客)'); return
    }
    void act(() => resolveCreditAppeal(credit.id, result, reply.trim()),
      result === 'overturned' ? '已改判:这一条不再计分' : '已维持原判')
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Table<Ticket>
        rowKey="id" loading={loading} dataSource={rows} size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 160,
            render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
          { title: '来自', dataIndex: 'role', width: 90,
            render: (v: string) => <Tag>{
              { customer: '用户', merchant: '商家', rider: '骑手' }[v] ?? v}</Tag> },
          { title: '联系方式', width: 140,
            render: (_, t) => t.contact || t.user_phone || '—' },
          { title: '内容', dataIndex: 'content', ellipsis: true },
          // status 实测只有 open / closed 两种,没有 replied ——
          // 「回过但没关」表现为 status=open 且 reply 非空
          { title: '状态', dataIndex: 'status', width: 100,
            render: (_: string, t) => t.credit_appeal?.status === 'open'
              ? <Tag color="warning">信用分待复核</Tag>
              : t.status === 'closed'
                ? <Tag>已关闭</Tag>
                : t.reply
                  ? <Tag color="processing">已回待关</Tag>
                  : <Tag color="warning">待处理</Tag> },
          { title: '操作', width: 100, fixed: 'right',
            render: (_, t) => (
              <Button type="link" onClick={() => { setCur(t); setReply(t.reply || '') }}>
                {t.status === 'closed' ? '看详情' : '处理'}
              </Button>
            ) },
        ]}
      />
      <Modal
        open={!!cur} title={`工单 #${cur?.id ?? ''}`} width={620}
        onCancel={() => setCur(null)}
        footer={creditOpen ? [
          <Button key="uphold" loading={acting} onClick={() => resolve('upheld')}>
            维持原判
          </Button>,
          <Button key="overturn" type="primary" loading={acting}
                  onClick={() => resolve('overturned')}>
            申诉成立,不再计分
          </Button>,
        ] : cur?.status !== 'closed' ? [
          <Button key="close" loading={acting}
                  onClick={() => cur && act(() => closeTicket(cur.id), '已关闭')}>
            关闭工单
          </Button>,
          <Button key="reply" type="primary" loading={acting}
                  onClick={() => {
                    if (reply.trim().length < 1) {
                      message.warning('回复不能为空'); return
                    }
                    void act(() => replyTicket(cur!.id, reply.trim()), '已回复')
                  }}>
            回复
          </Button>,
        ] : null}
      >
        {cur && (
          <>
            {credit && (
              <Alert
                type={creditOpen ? 'warning' : 'info'} showIcon style={{ marginBottom: 12 }}
                message={`信用分申诉 · ${CREDIT_KIND[credit.kind] ?? credit.kind} #${credit.record_id}`
                  + ` · ${CREDIT_STATUS[credit.status] ?? credit.status}`}
                description={creditOpen
                  ? '申诉成立:这一条不再计入顾客的信用分(违规记录会同时推翻,处置级别跟着重算)。'
                    + '下面写的复核结论会原样回到工单里,并推送给顾客。'
                  : credit.resolve_note}
              />
            )}
            <div style={{
              background: 'var(--sz-surface-alt)', padding: 12, borderRadius: 8,
              whiteSpace: 'pre-wrap', marginBottom: 12,
            }}>{cur.content}</div>
            {cur.reply && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)' }}>已有回复</div>
                <div style={{ whiteSpace: 'pre-wrap' }}>{cur.reply}</div>
              </div>
            )}
            {cur.status !== 'closed' && (
              <Input.TextArea rows={4} value={reply} maxLength={creditOpen ? 300 : 500} showCount
                              onChange={(e) => setReply(e.target.value)}
                              placeholder={creditOpen
                                ? '复核结论(会写回工单并推送给顾客)'
                                : '回复内容(会推送给提单人)'} />
            )}
          </>
        )}
      </Modal>
    </>
  )
}
